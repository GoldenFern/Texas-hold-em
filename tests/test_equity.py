"""EquityCalculator 胜率计算测试。"""

import pytest

from src.engine.card import Card
from src.analysis.equity import EquityCalculator


def cards(s: str) -> list[Card]:
    return Card.from_str_multi(s)


class TestEquityCalculator:
    """胜率计算器测试。"""

    def test_heads_up_preflop_aa_vs_kk(self) -> None:
        """AA vs KK 翻牌前胜率。"""
        calc = EquityCalculator(num_simulations=2000, seed=42)
        hand_a = cards("Ah As")
        hand_b = cards("Kh Ks")
        win_a, win_b, tie = calc.heads_up_equity(hand_a, hand_b)

        # AA 应显著领先 (约 81% vs 19%)
        assert win_a > win_b
        assert win_a > 0.75
        assert win_b < 0.25

    def test_heads_up_preflop_pair_vs_overcards(self) -> None:
        """22 vs AK — 小对子轻微领先。"""
        calc = EquityCalculator(num_simulations=2000, seed=42)
        hand_a = cards("2h 2s")
        hand_b = cards("Ad Kh")
        win_a, win_b, tie = calc.heads_up_equity(hand_a, hand_b)

        # 22 vs AK 约 52% vs 47%, close race
        assert 0.45 < win_a < 0.58
        assert 0.40 < win_b < 0.55

    def test_heads_up_dominated_hands(self) -> None:
        """AK vs AQ — 统治局面。"""
        calc = EquityCalculator(num_simulations=2000, seed=42)
        hand_a = cards("Ah Kh")
        hand_b = cards("As Qd")
        win_a, win_b, tie = calc.heads_up_equity(hand_a, hand_b)

        # AK 应显著领先 AQ
        assert win_a > win_b
        assert win_a > 0.65

    def test_postflop_made_hand_vs_draw(self) -> None:
        """翻牌后：成牌 vs 听牌。"""
        calc = EquityCalculator(num_simulations=2000, seed=42)
        # A 有顶对顶踢脚, B 有同花听牌
        hand_a = cards("Ah Kh")   # top pair top kicker on K-high board
        hand_b = cards("Qc Jc")   # flush draw
        community = cards("Kc 8c 2d")  # K-high, club draw

        result = calc.calculate([hand_a, hand_b], community)
        keys = list(result.keys())
        # 顶对 vs 同花听牌：顶对轻微领先
        win_a = result[keys[0]][0]
        win_b = result[keys[1]][0]
        assert 0.50 < win_a < 0.70
        assert 0.25 < win_b < 0.50

    def test_result_sum_to_one(self) -> None:
        """胜率 + 平率 + 负率 = 1.0。"""
        calc = EquityCalculator(num_simulations=500, seed=42)
        hand_a = cards("Ah Kh")
        hand_b = cards("2s 2d")
        result = calc.calculate([hand_a, hand_b])
        for desc, stats in result.items():
            total = sum(stats)
            assert abs(total - 1.0) < 0.01, f"{desc}: sum={total}"

    def test_multi_player(self) -> None:
        """多人底池胜率计算。"""
        calc = EquityCalculator(num_simulations=1000, seed=42)
        hands = [
            cards("Ah As"),   # AA
            cards("Kh Ks"),   # KK
            cards("Qh Qs"),   # QQ
        ]
        result = calc.calculate(hands)
        keys = list(result.keys())
        # AA 应有最高胜率
        win_rates = [result[k][0] for k in keys]
        assert win_rates[0] > win_rates[1]
        assert win_rates[1] > win_rates[2]

    def test_preflop_matchup(self) -> None:
        """翻牌前对决快捷方法。"""
        calc = EquityCalculator(num_simulations=500, seed=42)
        result = calc.preflop_matchup("Ah Kh", "2s 2d")
        assert "win_a" in result
        assert "win_b" in result
        assert "tie" in result

    def test_known_dead_cards(self) -> None:
        """已知死牌影响胜率。"""
        calc = EquityCalculator(num_simulations=1000, seed=42)
        hand_a = cards("Ah Kh")
        hand_b = cards("Qs Qd")
        # 有一张 Q 已死
        dead = cards("Qh")
        result = calc.calculate([hand_a, hand_b], dead_cards=dead)
        keys = list(result.keys())
        # B 的胜率应低于没有死牌的情况
        win_b = result[keys[1]][0]
        # QQ 少了一张，胜率降低
        assert win_b < 0.55
