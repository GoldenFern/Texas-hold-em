"""AI 策略引擎测试 —— 多人翻前表、翻后 MC、听牌/outs、品质判定。"""

from __future__ import annotations

import random

import pytest

from src.ai import strategy as st
from src.engine.card import Card
from src.utils._card_helpers import count_outs


def cards(s: str) -> list[Card]:
    """快捷构造牌列表。"""
    return Card.from_str_multi(s)


# ============================================================
# 翻牌前多人胜率表
# ============================================================

class TestPreflopHandStrength:
    def test_aa_strongest(self) -> None:
        assert st.preflop_hand_strength(cards("Ah As")) >= 80

    def test_returns_float_not_truncated(self) -> None:
        val = st.preflop_hand_strength(cards("Ah Ks"))
        assert isinstance(val, float)

    def test_trash_hand_weak(self) -> None:
        assert st.preflop_hand_strength(cards("2h 7c")) < 40

    def test_multiway_decreases(self) -> None:
        """同一手牌的胜率随对手数单调下降。"""
        for hand in ("Ah As", "Ah Ks", "7h 7c", "2h 7c"):
            vals = [
                st.preflop_hand_strength(cards(hand), n)
                for n in range(1, 9)
            ]
            assert vals == sorted(vals, reverse=True), f"{hand}: {vals}"

    def test_multiway_aa_realistic(self) -> None:
        """AA vs 5 对手应显著低于 vs 1（旧指数公式偏差 +26pp 的回归）。"""
        vs1 = st.preflop_hand_strength(cards("Ah As"), 1)
        vs5 = st.preflop_hand_strength(cards("Ah As"), 5)
        assert vs1 > 80
        assert 40 < vs5 < 55  # 真值约 48–49（equity share）

    def test_all_suited_beat_offsuit(self) -> None:
        """全部 78 对同花/非同花组合无倒挂。"""
        for hi in range(3, 15):
            for lo in range(2, hi):
                s = st._load_table()[(hi, lo, True)][0]
                o = st._load_table()[(hi, lo, False)][0]
                assert s > o, f"({hi},{lo}) suited {s} <= offsuit {o}"

    def test_pairs_monotonic(self) -> None:
        """口袋对子胜率随点数单调上升。"""
        vals = [
            st.preflop_hand_strength(
                [Card.from_str(f"{r}h"), Card.from_str(f"{r}s")]
            )
            for r in "23456789TJQKA"
        ]
        assert vals == sorted(vals)

    def test_out_of_range_opponents_clamped(self) -> None:
        assert st.preflop_hand_strength(cards("Ah As"), 0) ==             st.preflop_hand_strength(cards("Ah As"), 1)
        assert st.preflop_hand_strength(cards("Ah As"), 99) ==             st.preflop_hand_strength(cards("Ah As"), 8)

    def test_invalid_input(self) -> None:
        assert st.preflop_hand_strength([]) == 0.0


# ============================================================
# 翻牌后 MC
# ============================================================

class TestPostflopHandStrength:
    def test_top_set_very_strong(self) -> None:
        strength = st.postflop_hand_strength(
            cards("Ah Ad"), cards("As Kd 2c"),
        )
        assert strength > 0.85

    def test_deterministic_without_rng(self) -> None:
        """未注入 rng 时同输入同输出（状态派生种子）。"""
        a = st.postflop_hand_strength(cards("Ah Kh"), cards("Qh Jh 2c"))
        b = st.postflop_hand_strength(cards("Ah Kh"), cards("Qh Jh 2c"))
        assert a == b

    def test_rng_injectable(self) -> None:
        a = st.postflop_hand_strength(
            cards("Ah Kh"), cards("Qh Jh 2c"), rng=random.Random(1),
        )
        b = st.postflop_hand_strength(
            cards("Ah Kh"), cards("Qh Jh 2c"), rng=random.Random(1),
        )
        assert a == b

    def test_turn_enumerates_rivers(self) -> None:
        """转牌圈结果稳定（河牌精确枚举，方差仅来自对手抽样）。"""
        strength = st.postflop_hand_strength(
            cards("Ah Ad"), cards("As Kd 2c 2d"),
        )
        assert strength > 0.9

    def test_preflop_fallback(self) -> None:
        v = st.postflop_hand_strength(cards("Ah As"), [])
        assert 0.8 < v < 0.9


# ============================================================
# 听牌与 outs
# ============================================================

class TestDraws:
    def test_flush_draw_with_hole_cards(self) -> None:
        fd, _ = st.has_draw(cards("Ah Kh"), cards("Qh Jh 2c"))
        assert fd is True

    def test_board_only_flush_draw_not_counted(self) -> None:
        """纯公共牌 4 同花不算 Hero 的听牌（旧 bug 回归）。"""
        fd, _ = st.has_draw(cards("As Kd"), cards("Qh Jh 2h 3h"))
        assert fd is False

    def test_made_flush_not_a_draw(self) -> None:
        """已成同花不再报听牌（旧 bug 回归）。"""
        info = count_outs(cards("Ah Kh"), cards("Qh Jh 2h"))
        assert info.made_flush is True
        assert info.flush_draw is False

    def test_flush_draw_outs_nine(self) -> None:
        info = count_outs(cards("Ah Kh"), cards("Qh Jh 2c"))
        assert info.flush_draw is True
        assert info.outs >= 9  # 9 张同花补牌（可能叠加顺子 outs）

    def test_open_ended_vs_gutshot(self) -> None:
        """两头顺(8 outs)与卡顺(4 outs)可区分（旧实现无法区分）。"""
        oesd = count_outs(cards("9h 8d"), cards("7c 6s 2h"))
        assert oesd.straight_draw == "oesd"
        assert oesd.outs == 8

        gutshot = count_outs(cards("9h 8d"), cards("6c 5s Ah"))
        assert gutshot.straight_draw == "gutshot"
        assert gutshot.outs == 4

    def test_no_draw(self) -> None:
        fd, sd = st.has_draw(cards("Ah Kd"), cards("2c 7s Jh"))
        assert fd is False
        assert sd is False

    def test_too_few_community(self) -> None:
        assert st.has_draw(cards("Ah Kh"), []) == (False, False)


# ============================================================
# 手牌品质
# ============================================================

class TestHandQuality:
    def test_premium_hands(self) -> None:
        assert st.is_premium_hand(cards("Ah As")) is True
        assert st.is_premium_hand(cards("Kh Ks")) is True
        assert st.is_premium_hand(cards("2h 7c")) is False

    def test_playable_hands(self) -> None:
        assert st.is_playable_hand(cards("Ah Ks")) is True
        assert st.is_playable_hand(cards("2h 7c")) is False
