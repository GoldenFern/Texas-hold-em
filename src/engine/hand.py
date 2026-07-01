"""手牌评估器 —— 从 7 张牌中选出最佳 5 张牌型。

核心算法：生成所有 C(7,5)=21 种 5 牌组合，逐一评估，返回最佳。

评分系统：
    每手牌被编码为一个元组 (牌型等级, *踢脚序列)，元组比较即手牌比较。
    - 高牌:     (0, k1, k2, k3, k4, k5)
    - 一对:     (1, pair_rank, k1, k2, k3)
    - 两对:     (2, high_pair, low_pair, kicker)
    - 三条:     (3, trips_rank, k1, k2)
    - 顺子:     (4, top_card)
    - 同花:     (5, k1, k2, k3, k4, k5)
    - 葫芦:     (6, trips_rank, pair_rank)
    - 四条:     (7, quad_rank, kicker)
    - 同花顺:   (8, top_card)
    - 皇家同花顺: (9,)
"""

from __future__ import annotations

import itertools
from collections import Counter
from typing import Dict, Iterator, List, Optional, Sequence, Tuple

from src.engine.card import Card, Cards
from src.utils.constants import HandRank, Rank


# 手牌分数类型：可比较的元组
HandScore = Tuple[int, ...]

# 评估结果
class HandResult:
    """一手牌的完整评估结果。

    Attributes:
        hand_rank: 牌型等级。
        score: 用于比较的数值元组。
        best_five: 组成最佳牌型的 5 张牌。
        description: 中文描述。
    """

    __slots__ = ("hand_rank", "score", "best_five", "description")

    def __init__(
        self,
        hand_rank: HandRank,
        score: Tuple[int, ...],
        best_five: Cards,
    ) -> None:
        self.hand_rank = hand_rank
        self.score = score
        self.best_five = best_five
        self.description = hand_rank.display_name

    def __repr__(self) -> str:
        cards_str = " ".join(c.short_str for c in self.best_five)
        return f"HandResult({self.description}: {cards_str})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, HandResult):
            return NotImplemented
        return self.score == other.score

    def __lt__(self, other: HandResult) -> bool:
        if not isinstance(other, HandResult):
            return NotImplemented
        return self.score < other.score

    def __le__(self, other: HandResult) -> bool:
        if not isinstance(other, HandResult):
            return NotImplemented
        return self.score <= other.score

    def __gt__(self, other: HandResult) -> bool:
        if not isinstance(other, HandResult):
            return NotImplemented
        return self.score > other.score

    def __ge__(self, other: HandResult) -> bool:
        if not isinstance(other, HandResult):
            return NotImplemented
        return self.score >= other.score


class HandEvaluator:
    """手牌评估器。

    静态方法集，用于评估 5 或 7 张牌中的最佳手牌。
    """

    # Ace-low 顺子 (A-2-3-4-5) 的特殊映射
    _ACE_LOW_STRAIGHT_RANKS = frozenset({14, 2, 3, 4, 5})

    @staticmethod
    def evaluate(cards: Sequence[Card]) -> HandResult:
        """从序列中的所有牌中选出最佳 5 张牌型。

        支持 5–7 张牌作为输入。对 7 张牌，枚举所有 21 种 5 牌组合。
        """
        n = len(cards)
        if n < 5:
            raise ValueError(f"至少需要 5 张牌，目前仅有 {n} 张")
        if n == 5:
            return HandEvaluator._evaluate_five(list(cards))
        # 6 或 7 张牌：取所有 5 牌组合，找最佳
        best: Optional[HandResult] = None
        for combo in itertools.combinations(cards, 5):
            result = HandEvaluator._evaluate_five(list(combo))
            if best is None or result > best:
                best = result
        assert best is not None
        return best

    @staticmethod
    def _evaluate_five(cards: List[Card]) -> HandResult:
        """评估恰好 5 张牌的手牌。"""
        ranks = sorted((c.rank.value for c in cards), reverse=True)
        suits = [c.suit for c in cards]
        rank_counts = Counter(ranks)
        most_common = rank_counts.most_common()

        is_flush = len(set(suits)) == 1
        is_straight, straight_high = HandEvaluator._check_straight(ranks)

        # 同花顺 / 皇家同花顺
        if is_flush and is_straight:
            if straight_high == 14:  # A-high straight flush = Royal
                return HandResult(HandRank.ROYAL_FLUSH, (9,), cards)
            return HandResult(HandRank.STRAIGHT_FLUSH, (8, straight_high), cards)

        # 四条
        if most_common[0][1] == 4:
            quad_rank = most_common[0][0]
            kicker = most_common[1][0]
            return HandResult(
                HandRank.FOUR_OF_A_KIND, (7, quad_rank, kicker), cards
            )

        # 葫芦
        if most_common[0][1] == 3 and most_common[1][1] == 2:
            trips_rank = most_common[0][0]
            pair_rank = most_common[1][0]
            return HandResult(
                HandRank.FULL_HOUSE, (6, trips_rank, pair_rank), cards
            )

        # 同花（非顺）
        if is_flush:
            return HandResult(
                HandRank.FLUSH, (5, *ranks), cards
            )

        # 顺子（非同花）
        if is_straight:
            return HandResult(
                HandRank.STRAIGHT, (4, straight_high), cards
            )

        # 三条
        if most_common[0][1] == 3:
            trips_rank = most_common[0][0]
            kickers = sorted(
                [r for r in ranks if r != trips_rank], reverse=True
            )
            return HandResult(
                HandRank.THREE_OF_A_KIND,
                (3, trips_rank, *kickers),
                cards,
            )

        # 两对
        if most_common[0][1] == 2 and most_common[1][1] == 2:
            high_pair = max(most_common[0][0], most_common[1][0])
            low_pair = min(most_common[0][0], most_common[1][0])
            kicker = most_common[2][0]
            return HandResult(
                HandRank.TWO_PAIR,
                (2, high_pair, low_pair, kicker),
                cards,
            )

        # 一对
        if most_common[0][1] == 2:
            pair_rank = most_common[0][0]
            kickers = sorted(
                [r for r in ranks if r != pair_rank], reverse=True
            )
            return HandResult(
                HandRank.ONE_PAIR,
                (1, pair_rank, *kickers),
                cards,
            )

        # 高牌
        return HandResult(
            HandRank.HIGH_CARD, (0, *ranks), cards
        )

    @staticmethod
    def _check_straight(ranks: List[int]) -> Tuple[bool, int]:
        """检查 5 个降序排列的 rank 是否构成顺子。

        Returns:
            (是否为顺子, 顺子的顶牌值)。
        """
        unique = sorted(set(ranks), reverse=True)
        if len(unique) != 5:
            return False, 0
        # 普通顺子
        if unique[0] - unique[4] == 4:
            return True, unique[0]
        # Ace-low 顺子: A-2-3-4-5 → top=5
        if unique == [14, 5, 4, 3, 2]:
            return True, 5
        return False, 0

    @staticmethod
    def compare(cards_a: Sequence[Card], cards_b: Sequence[Card]) -> int:
        """比较两手牌。

        Returns:
            1: A 胜, -1: B 胜, 0: 平局。
        """
        result_a = HandEvaluator.evaluate(cards_a)
        result_b = HandEvaluator.evaluate(cards_b)
        if result_a > result_b:
            return 1
        if result_a < result_b:
            return -1
        return 0

    @staticmethod
    def compare_results(
        result_a: HandResult, result_b: HandResult
    ) -> int:
        """比较两个已评估的手牌结果。

        Returns:
            1: A 胜, -1: B 胜, 0: 平局。
        """
        if result_a > result_b:
            return 1
        if result_a < result_b:
            return -1
        return 0
