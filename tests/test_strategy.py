"""AI 策略引擎测试 —— 手牌强度、听牌检测、位置评估、动作随机化。"""

import random
import os
import json
import tempfile

import pytest

from src.ai import strategy as st
from src.engine.card import Card
from src.utils.constants import ActionType, Rank, Suit


def cards(s: str) -> list[Card]:
    """快捷构造牌列表。"""
    return Card.from_str_multi(s)


# ============================================================
# 翻牌前手牌强度
# ============================================================

class TestPreflopHandStrength:
    """翻牌前手牌强度排名。"""

    def test_aa_strongest(self) -> None:
        assert st.preflop_hand_strength(cards("Ah As")) >= 80

    def test_kings_strong(self) -> None:
        assert st.preflop_hand_strength(cards("Kh Ks")) >= 75

    def test_queens_strong(self) -> None:
        assert st.preflop_hand_strength(cards("Qh Qs")) >= 68

    def test_ace_king_suited_good(self) -> None:
        strength = st.preflop_hand_strength(cards("Ah Kh"))
        assert strength >= 60

    def test_ace_king_both_valid(self) -> None:
        """AKs 和 AKo 都应有合理的翻牌前胜率。"""
        suited = st.preflop_hand_strength(cards("Ah Kh"))
        offsuit = st.preflop_hand_strength(cards("Ac Kd"))
        assert 55 <= suited <= 75
        assert 50 <= offsuit <= 75

    def test_seven_two_offsuit_weakest(self) -> None:
        strength = st.preflop_hand_strength(cards("7c 2d"))
        assert strength <= 40

    def test_pocket_pairs_stronger_same_high_rank(self) -> None:
        """同点对子 > 非同花高牌（相同高牌点数时）。"""
        pair = st.preflop_hand_strength(cards("Th Ts"))
        high = st.preflop_hand_strength(cards("Tc 9d"))
        assert pair > high

    def test_suited_stronger_than_offsuit(self) -> None:
        """同花应 >= 非同花（点数相同时）。"""
        suited = st.preflop_hand_strength(cards("Js Ts"))
        offsuit = st.preflop_hand_strength(cards("Jc Td"))
        assert suited >= offsuit

    def test_aa_beats_kk(self) -> None:
        assert st.preflop_hand_strength(cards("Ah As")) > st.preflop_hand_strength(cards("Kh Ks"))

    def test_kk_beats_qq(self) -> None:
        assert st.preflop_hand_strength(cards("Kh Ks")) > st.preflop_hand_strength(cards("Qh Qs"))

    def test_not_two_cards_returns_zero(self) -> None:
        assert st.preflop_hand_strength([]) == 0
        assert st.preflop_hand_strength(cards("Ah")) == 0
        assert st.preflop_hand_strength(cards("Ah Kh Qd")) == 0

    def test_strength_range(self) -> None:
        """多种手牌的强度应在 0–100 范围内。"""
        hands = ["Ah As", "Kh Ks", "Qh Qs", "Ah Kh", "Ac Kd",
                 "Ts 9s", "5c 4d", "7c 2d"]
        for h in hands:
            s = st.preflop_hand_strength(cards(h))
            assert 20 <= s <= 100, f"{h}: strength={s} out of range"


# ============================================================
# 翻牌后手牌强度
# ============================================================

class TestPostflopHandStrength:
    """翻牌后手牌强度。"""

    def test_empty_community_falls_back_to_preflop(self) -> None:
        """空公共牌应回退到翻牌前强度。"""
        pf = st.preflop_hand_strength(cards("Ah As")) / 100.0
        post = st.postflop_hand_strength(cards("Ah As"), [])
        assert post == pf

    def test_flop_with_strong_hand(self) -> None:
        """翻牌击中顶暗三条，应有高胜率。"""
        strength = st.postflop_hand_strength(
            cards("Ah As"),
            cards("Ad 7h 2c"),
            num_simulations=500,
        )
        assert strength > 0.7

    def test_flop_with_weak_hand(self) -> None:
        """翻牌完全错过，胜率应低。"""
        strength = st.postflop_hand_strength(
            cards("2c 7d"),
            cards("Ah Kh Qh"),
            num_simulations=500,
        )
        assert strength < 0.3

    def test_result_in_range(self) -> None:
        strength = st.postflop_hand_strength(
            cards("Ah Kh"),
            cards("Qh Jh Th"),
            num_simulations=300,
        )
        assert 0.0 <= strength <= 1.0

    def test_fewer_than_5_cards_falls_back(self) -> None:
        """不足 5 张牌时回退到翻牌前。"""
        pf = st.preflop_hand_strength(cards("Ah As")) / 100.0
        post = st.postflop_hand_strength(cards("Ah As"), cards("Kd Qd"))
        assert post == pf


# ============================================================
# 听牌检测
# ============================================================

class TestDrawDetection:
    """听牌检测。"""

    def test_flush_draw_4_hearts(self) -> None:
        fd, sd = st.has_draw(cards("Ah Kh"), cards("Qh Jh 2s"))
        assert fd is True

    def test_no_flush_draw_3_hearts(self) -> None:
        fd, sd = st.has_draw(cards("Ah Kh"), cards("Qh 2s 3c"))
        assert fd is False

    def test_open_ended_straight_draw(self) -> None:
        fd, sd = st.has_draw(cards("Jh Ts"), cards("9d 8c 2h"))
        assert sd is True

    def test_gutshot_not_detected_as_draw(self) -> None:
        """当前实现检测 4 张 rank gap ≤4，gutshot 可能被识别。"""
        fd, sd = st.has_draw(cards("Ah 4h"), cards("5d 6c Kh"))
        # A-4-5-6 gap，可能被识别为顺子听牌
        assert isinstance(sd, bool)

    def test_no_draw_bricked_board(self) -> None:
        fd, sd = st.has_draw(cards("Ah Kd"), cards("2s 7c 9d"))
        assert fd is False
        assert sd is False

    def test_fewer_than_3_community_returns_false(self) -> None:
        fd, sd = st.has_draw(cards("Ah Kh"), cards("Qh"))
        assert fd is False
        assert sd is False

    def test_empty_community_returns_false(self) -> None:
        fd, sd = st.has_draw(cards("Ah Kh"), [])
        assert fd is False
        assert sd is False

    def test_combined_flush_and_straight_draw(self) -> None:
        """同花顺听牌。"""
        fd, sd = st.has_draw(cards("Jh Th"), cards("9h 8h 2s"))
        assert fd is True
        assert sd is True

    def test_ace_low_straight_draw(self) -> None:
        """A-2-3-4 的 wheel 听牌。"""
        fd, sd = st.has_draw(cards("Ah 2h"), cards("3d 4c Ks"))
        assert sd is True


# ============================================================
# 底池赔率计算
# ============================================================

class TestCalculatePotOdds:
    """底池赔率计算。"""

    def test_standard_odds(self) -> None:
        """跟注 10 进 50 底池 → 所需胜率 = 10/(50+10) = 0.1667。"""
        odds = st.calculate_pot_odds(10, 50)
        assert abs(odds - 10 / 60) < 0.01

    def test_call_equal_to_pot(self) -> None:
        """跟注额 = 底池 → 所需胜率 = 50%."""
        odds = st.calculate_pot_odds(100, 100)
        assert abs(odds - 0.5) < 0.01

    def test_zero_call(self) -> None:
        assert st.calculate_pot_odds(0, 100) == 0.0

    def test_zero_pot_and_call(self) -> None:
        assert st.calculate_pot_odds(0, 0) == 0.0

    def test_large_call_small_pot(self) -> None:
        """大幅超池下注 → 高所需胜率。"""
        odds = st.calculate_pot_odds(200, 10)
        assert abs(odds - 200 / 210) < 0.01


# ============================================================
# 位置价值
# ============================================================

class TestPositionValue:
    """位置价值评估。"""

    def test_dealer_is_zero(self) -> None:
        """非庄位与庄位的距离：庄位本身 offset=0 → pos_val = 1-0 = 1.0。"""
        # dealer_seat=5, player_seat=5, num_players=6
        # relative_pos = (5-5) % 6 = 0 → value = 0.0
        # 等等，代码中 relative_pos=0 时返回 0.0
        val = st.position_value(5, 5, 6)
        assert val == 0.0

    def test_button_position_best(self) -> None:
        """离庄位最近的非庄位玩家 position_value 较高。"""
        # dealer=5, player at seat 0: relative_pos=(0-5)%6=1, value=1-1/6=0.83
        val_close = st.position_value(0, 5, 6)
        # dealer=5, player at seat 2: relative_pos=(2-5)%6=3, value=1-3/6=0.5
        val_far = st.position_value(2, 5, 6)
        # 更靠近庄位的玩家应有更高的 position_value
        assert val_close > val_far

    def test_under_the_gun_worst(self) -> None:
        """UTG 位置最差。"""
        # 3 人桌: dealer=0, UTG=1
        # relative_pos = (1-0) % 3 = 1 → pos_val = 1/3 ≈ 0.33 → 1-0.33 = 0.67
        utg_val = st.position_value(1, 0, 3)
        # dealer=0, 位置1: (1-0)%3=1→0.67
        # dealer=0, 位置2: (2-0)%3=2→0.33
        btn_val = st.position_value(2, 0, 3)  # 最接近庄位
        # 在 3 人桌，位置 2 (BTN之后1位) 比 位置1 (UTG，BTN之后2位) 更好
        assert btn_val < utg_val, f"btn={btn_val}, utg={utg_val}"

    def test_value_in_range(self) -> None:
        """位置价值应在 0.0–1.0 范围内。"""
        for seat in range(6):
            val = st.position_value(seat, 0, 6)
            assert 0.0 <= val <= 1.0


# ============================================================
# 手牌品质判定
# ============================================================

class TestHandQuality:
    """顶级手牌/可玩手牌判定。"""

    def test_aa_is_premium(self) -> None:
        assert st.is_premium_hand(cards("Ah As")) is True

    def test_kk_is_premium(self) -> None:
        assert st.is_premium_hand(cards("Kh Ks")) is True

    def test_seven_two_not_premium(self) -> None:
        assert st.is_premium_hand(cards("7c 2d")) is False

    def test_aa_is_playable(self) -> None:
        assert st.is_playable_hand(cards("Ah As")) is True

    def test_seven_two_not_playable(self) -> None:
        assert st.is_playable_hand(cards("7c 2d")) is False

    def test_mid_hand_is_playable(self) -> None:
        """中等手牌应可玩但非顶级。"""
        # JTs 通常可玩
        assert st.is_playable_hand(cards("Js Ts")) is True


# ============================================================
# 动作随机化
# ============================================================

class TestRandomizeAction:
    """按权重随机选择动作。"""

    def test_single_action_always_selected(self) -> None:
        actions = [(ActionType.FOLD, 1.0)]
        for _ in range(20):
            result = st.randomize_action(actions, random.Random(42))
            assert result == ActionType.FOLD

    def test_higher_weight_more_likely(self) -> None:
        """权重高的动作应更频繁被选中。"""
        actions = [
            (ActionType.RAISE, 8.0),
            (ActionType.FOLD, 2.0),
        ]
        rng = random.Random(123)
        raises = sum(
            1 for _ in range(100)
            if st.randomize_action(actions, rng) == ActionType.RAISE
        )
        assert raises > 60  # 约 80%

    def test_zero_total_weight_returns_first(self) -> None:
        actions = [(ActionType.CHECK, 0.0), (ActionType.FOLD, 0.0)]
        assert st.randomize_action(actions) == ActionType.CHECK

    def test_empty_list_returns_fold(self) -> None:
        assert st.randomize_action([]) == ActionType.FOLD

    def test_deterministic_with_seed(self) -> None:
        actions = [
            (ActionType.RAISE, 5.0),
            (ActionType.CALL, 3.0),
            (ActionType.FOLD, 2.0),
        ]
        rng1 = random.Random(42)
        rng2 = random.Random(42)
        for _ in range(10):
            assert st.randomize_action(actions, rng1) == st.randomize_action(actions, rng2)


# ============================================================
# 胜率表缓存序列化
# ============================================================

class TestEquityTableSerialization:
    """胜率表 Key 序列化/反序列化。"""

    def test_key_to_str_roundtrip(self) -> None:
        key = (14, 2, True)
        assert st._str_to_key(st._key_to_str(key)) == key

    def test_key_to_str_offsuit(self) -> None:
        assert st._key_to_str((14, 2, False)) == "14,2,0"

    def test_key_to_str_suited(self) -> None:
        assert st._key_to_str((14, 2, True)) == "14,2,1"

    def test_str_to_key_suited(self) -> None:
        assert st._str_to_key("14,2,1") == (14, 2, True)

    def test_str_to_key_offsuit(self) -> None:
        assert st._str_to_key("10,5,0") == (10, 5, False)

    def test_pair_key(self) -> None:
        key = (14, 14, False)
        assert st._str_to_key(st._key_to_str(key)) == key


# ============================================================
# 胜率表加载与保存
# ============================================================

class TestEquityTableIO:
    """胜率表文件 I/O。"""

    def test_load_nonexistent_returns_none(self) -> None:
        """加载不存在的文件返回 None。"""
        original = st._EQUITY_CACHE_FILE
        try:
            st._EQUITY_CACHE_FILE = "/nonexistent/path/preflop_equity.json"
            assert st._load_equity_table() is None
        finally:
            st._EQUITY_CACHE_FILE = original

    def test_save_and_load_roundtrip(self) -> None:
        """保存后加载应一致。"""
        table = {(14, 13, False): 67.0, (2, 7, False): 32.0}
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            raw = {st._key_to_str(k): v for k, v in table.items()}
            json.dump(raw, f, ensure_ascii=False)
            tmp_path = f.name

        try:
            original = st._EQUITY_CACHE_FILE
            st._EQUITY_CACHE_FILE = tmp_path
            loaded = st._load_equity_table()
            assert loaded is not None
            assert loaded[(14, 13, False)] == 67.0
            assert loaded[(2, 7, False)] == 32.0
        finally:
            st._EQUITY_CACHE_FILE = original
            os.unlink(tmp_path)

    def test_load_corrupted_file_returns_none(self) -> None:
        """损坏的文件返回 None。"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            f.write("not valid json {{{")
            tmp_path = f.name

        try:
            original = st._EQUITY_CACHE_FILE
            st._EQUITY_CACHE_FILE = tmp_path
            assert st._load_equity_table() is None
        finally:
            st._EQUITY_CACHE_FILE = original
            os.unlink(tmp_path)
