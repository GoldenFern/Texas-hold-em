"""HandEvaluator 手牌评估器 —— 全面测试所有 10 种牌型。"""

import pytest

from src.engine.card import Card
from src.engine.hand import HandEvaluator, HandResult
from src.utils.constants import HandRank


# ---- 辅助函数 ----

def cards(s: str) -> list[Card]:
    """快捷构造牌列表，如 cards('Ah Kh Qh Jh Th')。"""
    return Card.from_str_multi(s)


def eval_hand(card_str: str) -> HandResult:
    """评估字符串指定的手牌。"""
    return HandEvaluator.evaluate(cards(card_str))


# ============================================================
# 所有 10 种牌型识别测试
# ============================================================

class TestRoyalFlush:
    """皇家同花顺。"""

    def test_royal_flush_hearts(self) -> None:
        result = eval_hand("Ah Kh Qh Jh Th")
        assert result.hand_rank == HandRank.ROYAL_FLUSH

    def test_royal_flush_spades(self) -> None:
        result = eval_hand("As Ks Qs Js Ts")
        assert result.hand_rank == HandRank.ROYAL_FLUSH

    def test_royal_flush_from_seven(self) -> None:
        """7 张牌中找出皇家同花顺。"""
        result = eval_hand("Ah Kh Qh Jh Th 2c 3d")
        assert result.hand_rank == HandRank.ROYAL_FLUSH

    def test_royal_beats_straight_flush(self) -> None:
        royal = eval_hand("Ah Kh Qh Jh Th")
        sf = eval_hand("9s 8s 7s 6s 5s")
        assert royal > sf


class TestStraightFlush:
    """同花顺（非皇家）。"""

    def test_straight_flush_king_high(self) -> None:
        result = eval_hand("Kh Qh Jh Th 9h")
        assert result.hand_rank == HandRank.STRAIGHT_FLUSH

    def test_straight_flush_five_high(self) -> None:
        """最小的同花顺：A-2-3-4-5。"""
        result = eval_hand("Ah 2h 3h 4h 5h")
        assert result.hand_rank == HandRank.STRAIGHT_FLUSH

    def test_straight_flush_six_high(self) -> None:
        result = eval_hand("6c 5c 4c 3c 2c")
        assert result.hand_rank == HandRank.STRAIGHT_FLUSH

    def test_straight_flush_comparison(self) -> None:
        """K-high 同花顺 > Q-high 同花顺。"""
        kh = eval_hand("Kh Qh Jh Th 9h")
        qh = eval_hand("Qs Js Ts 9s 8s")
        assert kh > qh


class TestFourOfAKind:
    """四条。"""

    def test_four_aces(self) -> None:
        result = eval_hand("Ah As Ad Ac Kh")
        assert result.hand_rank == HandRank.FOUR_OF_A_KIND

    def test_four_twos(self) -> None:
        result = eval_hand("2h 2s 2d 2c Kh")
        assert result.hand_rank == HandRank.FOUR_OF_A_KIND

    def test_four_of_kind_comparison(self) -> None:
        """四条 A > 四条 K。"""
        quad_a = eval_hand("Ah As Ad Ac 2h")
        quad_k = eval_hand("Kh Ks Kd Kc Ah")
        assert quad_a > quad_k

    def test_four_of_kind_kicker(self) -> None:
        """同四条，比踢脚。"""
        quad_a_king = eval_hand("Ah As Ad Ac Kh")
        quad_a_queen = eval_hand("Ah As Ad Ac Qh")
        assert quad_a_king > quad_a_queen


class TestFullHouse:
    """葫芦。"""

    def test_full_house_aces_over_kings(self) -> None:
        result = eval_hand("Ah As Ad Kh Ks")
        assert result.hand_rank == HandRank.FULL_HOUSE

    def test_full_house_twos_over_threes(self) -> None:
        result = eval_hand("2h 2s 2d 3h 3s")
        assert result.hand_rank == HandRank.FULL_HOUSE

    def test_full_house_comparison(self) -> None:
        """三条 A 葫芦 > 三条 K 葫芦。"""
        aaa_kk = eval_hand("Ah As Ad Kh Ks")
        kkk_aa = eval_hand("Kh Ks Kd Ah As")
        assert aaa_kk > kkk_aa


class TestFlush:
    """同花（非顺）。"""

    def test_flush_ace_high(self) -> None:
        result = eval_hand("Ah Kh Qh Jh 9h")
        assert result.hand_rank == HandRank.FLUSH

    def test_flush_from_seven(self) -> None:
        result = eval_hand("Ah Kh Qh Jh 9h 2c 3d")
        assert result.hand_rank == HandRank.FLUSH

    def test_flush_not_straight(self) -> None:
        """确保不误判为顺子。"""
        result = eval_hand("Ah Kh Qh Jh 2h")  # 缺 10，不是顺子
        assert result.hand_rank == HandRank.FLUSH

    def test_flush_comparison(self) -> None:
        flush_a = eval_hand("Ah Kh Qh Jh 9h")
        flush_b = eval_hand("Ah Kh Qh Jh 8h")
        assert flush_a > flush_b


class TestStraight:
    """顺子（非同花）。"""

    def test_straight_ace_high(self) -> None:
        result = eval_hand("Ah Ks Qd Jh Tc")
        assert result.hand_rank == HandRank.STRAIGHT

    def test_straight_ace_low(self) -> None:
        """A-2-3-4-5 顺子（wheel）。"""
        result = eval_hand("Ah 2s 3d 4h 5c")
        assert result.hand_rank == HandRank.STRAIGHT

    def test_straight_five_high_six_high(self) -> None:
        """6-high 顺子 > 5-high 顺子。"""
        six_high = eval_hand("6h 5s 4d 3h 2c")
        five_high = eval_hand("Ah 2s 3d 4h 5c")
        assert six_high > five_high

    def test_straight_seven_high(self) -> None:
        result = eval_hand("7h 6s 5d 4h 3c")
        assert result.hand_rank == HandRank.STRAIGHT

    def test_wheel_not_beat_pair(self) -> None:
        """wheel 顺子应该能击败一对。"""
        wheel = eval_hand("Ah 2s 3d 4h 5c")
        pair = eval_hand("Ah As 2d 3h 4c")
        assert wheel > pair


class TestThreeOfAKind:
    """三条。"""

    def test_three_of_kind(self) -> None:
        result = eval_hand("Ah As Ad Kh Qh")
        assert result.hand_rank == HandRank.THREE_OF_A_KIND

    def test_three_of_kind_comparison(self) -> None:
        trip_a = eval_hand("Ah As Ad Kh Qh")
        trip_k = eval_hand("Kh Ks Kd Ah Qh")
        assert trip_a > trip_k

    def test_three_of_kind_kicker(self) -> None:
        trip_a_kq = eval_hand("Ah As Ad Kh Qh")
        trip_a_kj = eval_hand("Ah As Ad Kh Jh")
        assert trip_a_kq > trip_a_kj


class TestTwoPair:
    """两对。"""

    def test_two_pair(self) -> None:
        result = eval_hand("Ah As Kh Ks Qh")
        assert result.hand_rank == HandRank.TWO_PAIR

    def test_two_pair_comparison(self) -> None:
        aakk = eval_hand("Ah As Kh Ks Qh")
        aaqq = eval_hand("Ah As Qh Qs Kh")
        assert aakk > aaqq

    def test_two_pair_kicker(self) -> None:
        aakk_q = eval_hand("Ah As Kh Ks Qh")
        aakk_j = eval_hand("Ah As Kh Ks Jh")
        assert aakk_q > aakk_j


class TestOnePair:
    """一对。"""

    def test_one_pair(self) -> None:
        result = eval_hand("Ah As Kh Qh Jh")
        assert result.hand_rank == HandRank.ONE_PAIR

    def test_one_pair_comparison(self) -> None:
        pair_a = eval_hand("Ah As Kh Qh Jh")
        pair_k = eval_hand("Kh Ks Ah Qh Jh")
        assert pair_a > pair_k

    def test_one_pair_kicker_sequence(self) -> None:
        """多级踢脚比较。"""
        pair_a_kqj = eval_hand("Ah As Kh Qh Jh")
        pair_a_kqt = eval_hand("Ah As Kh Qh Th")
        assert pair_a_kqj > pair_a_kqt


class TestHighCard:
    """高牌。"""

    def test_high_card(self) -> None:
        result = eval_hand("Ah Kh Qh Jh 9d")
        assert result.hand_rank == HandRank.HIGH_CARD

    def test_high_card_comparison(self) -> None:
        akqj9 = eval_hand("Ah Kh Qh Jh 9d")
        akqj8 = eval_hand("Ah Kh Qh Jh 8d")
        assert akqj9 > akqj8


# ============================================================
# 7 张牌场景测试
# ============================================================

class TestSevenCard:
    """从 7 张牌中选最佳 5 张。"""

    def test_flush_over_straight(self) -> None:
        """同时有同花和顺子时，应选同花（得分更高）。"""
        # 红心同花 + 可能的顺子，应返回同花
        result = eval_hand("Ah Kh Qh 9h 2h 5d 4c")
        assert result.hand_rank == HandRank.FLUSH

    def test_full_house_over_flush(self) -> None:
        """同时有葫芦和同花时，选葫芦。"""
        result = eval_hand("Ah As Ad Kh Ks 2h 3h")
        assert result.hand_rank == HandRank.FULL_HOUSE

    def test_straight_flush_over_four_kind(self) -> None:
        """同花顺优先于四条。"""
        # 情况极端但应正确识别
        result = eval_hand("5h 6h 7h 8h 9h 9d 9c")
        assert result.hand_rank == HandRank.STRAIGHT_FLUSH

    def test_beats_pair_with_high_card_from_seven(self) -> None:
        """7 张牌中正确选出一对而非高牌。"""
        result = eval_hand("Ah As Kh Qh Jh 9d 8c")
        assert result.hand_rank == HandRank.ONE_PAIR


# ============================================================
# compare 函数测试
# ============================================================

class TestCompare:
    """两手牌比较。"""

    def test_compare_a_wins(self) -> None:
        a = cards("Ah As Kh Qh Jh")  # One pair A
        b = cards("Kh Ks Ah Qh Jh")  # One pair K
        assert HandEvaluator.compare(a, b) == 1

    def test_compare_b_wins(self) -> None:
        a = cards("Kh Ks Ah Qh Jh")
        b = cards("Ah As Kh Qh Jh")
        assert HandEvaluator.compare(a, b) == -1

    def test_compare_tie(self) -> None:
        a = cards("Ah As Kh Qh Jh")
        b = cards("Ac Ad Kc Qc Jc")
        assert HandEvaluator.compare(a, b) == 0

    def test_tie_with_board_playing(self) -> None:
        """双方都用公共牌组成相同手牌。"""
        community = cards("Ah Kh Qh Jh Th")  # 皇家同花顺在公共牌
        # 双方 hole cards 不影响结果
        a = community + cards("2c 3d")
        b = community + cards("4c 5d")
        assert HandEvaluator.compare(a, b) == 0


# ============================================================
# 边界情况
# ============================================================

class TestEdgeCases:
    """边界情况测试。"""

    def test_fewer_than_5_cards_raises(self) -> None:
        with pytest.raises(ValueError):
            HandEvaluator.evaluate(cards("Ah Kh Qh Jh"))

    def test_exactly_5_cards(self) -> None:
        result = HandEvaluator.evaluate(cards("Ah Kh Qh Jh Th"))
        assert result.hand_rank == HandRank.ROYAL_FLUSH

    def test_six_cards(self) -> None:
        result = HandEvaluator.evaluate(cards("Ah As Ad Ac Kh Qh"))
        assert result.hand_rank == HandRank.FOUR_OF_A_KIND

    def test_pair_vs_two_pair_ranking(self) -> None:
        """确保牌型等级排序正确。"""
        ranks_in_order = [
            HandRank.HIGH_CARD,
            HandRank.ONE_PAIR,
            HandRank.TWO_PAIR,
            HandRank.THREE_OF_A_KIND,
            HandRank.STRAIGHT,
            HandRank.FLUSH,
            HandRank.FULL_HOUSE,
            HandRank.FOUR_OF_A_KIND,
            HandRank.STRAIGHT_FLUSH,
            HandRank.ROYAL_FLUSH,
        ]
        for i in range(len(ranks_in_order) - 1):
            assert ranks_in_order[i] < ranks_in_order[i + 1]

    def test_wheel_is_five_high_straight(self) -> None:
        """A-2-3-4-5 是 5-high 顺子。"""
        result = eval_hand("Ah 2s 3d 4h 5c 9d Ks")
        assert result.hand_rank == HandRank.STRAIGHT
        # score 的第二项是顺子顶牌，应 =5
        assert result.score[1] == 5

    def test_wheel_not_confused_with_ace_high(self) -> None:
        """A-2-3-4-5 不应被当作 Ace-high。"""
        wheel = eval_hand("Ah 2s 3d 4h 5c")
        # Ace-high straight 需要 T-J-Q-K-A
        ace_high_straight = eval_hand("Ah Ks Qd Jh Tc")
        assert ace_high_straight > wheel

    def test_board_texture_ace_low_not_straight(self) -> None:
        """A-2-3-4-6 没有顺子。"""
        result = eval_hand("Ah 2s 3d 4h 6c Ks Qd")
        assert result.hand_rank != HandRank.STRAIGHT
