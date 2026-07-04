"""手牌评估器 —— 基于 Treys (TwoPlusTwo 查表算法) 的高性能评估。

使用业界成熟的 Treys 库替代原来自行实现的枚举组合算法。
Treys 内部使用 Cactus Kev 改进版的预计算查找表，O(1) 完成 5 张牌评估。

公开 API 保持不变，下游代码无需任何改动。
"""

from __future__ import annotations

import itertools
from collections import Counter
from typing import Dict, Iterator, List, Optional, Sequence, Tuple

from treys import Card as TreysCard
from treys import Evaluator

from src.engine.card import Card, Cards
from src.utils.constants import HandRank, Rank


# ================================================================
# Treys 初始化（模块级单例）
# ================================================================

_treys = Evaluator()

# Treys rank_class → 我们的 HandRank 枚举
# Treys rank_class 是 0-indexed，0=StraightFlush, ..., 9=HighCard
_TREYS_RANK_MAP: Dict[int, HandRank] = {
    0: HandRank.STRAIGHT_FLUSH,  # 含皇家同花顺（额外检测区分）
    1: HandRank.STRAIGHT_FLUSH,
    2: HandRank.FOUR_OF_A_KIND,
    3: HandRank.FULL_HOUSE,
    4: HandRank.FLUSH,
    5: HandRank.STRAIGHT,
    6: HandRank.THREE_OF_A_KIND,
    7: HandRank.TWO_PAIR,
    8: HandRank.ONE_PAIR,
    9: HandRank.HIGH_CARD,
}


# ================================================================
# HandScore 类型 & HandResult 类（公开 API 不变）
# ================================================================

# 手牌分数类型：可比较的元组
HandScore = Tuple[int, ...]


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


# ================================================================
# HandEvaluator
# ================================================================

class HandEvaluator:
    """手牌评估器。

    内部使用 Treys（TwoPlusTwo 查表算法）进行牌型识别，
    输出结果格式与之前完全相同，下游无需改动。
    """

    # Ace-low 顺子 (A-2-3-4-5) 的特殊映射
    _ACE_LOW_STRAIGHT_RANKS = frozenset({14, 2, 3, 4, 5})

    # ---- 转换 ----

    @staticmethod
    def _to_treys(card: Card) -> int:
        """将项目 Card 转为 Treys 内部整数表示。"""
        return TreysCard.new(card.short_str)

    # ---- 公开 API ----

    @staticmethod
    def evaluate(cards: Sequence[Card]) -> HandResult:
        """从序列中的所有牌中选出最佳 5 张牌型。

        支持 5–7 张牌作为输入。使用 Treys 查表算法快速评估。
        """
        n = len(cards)
        if n < 5:
            raise ValueError(f"至少需要 5 张牌，目前仅有 {n} 张")
        if n == 5:
            return HandEvaluator._evaluate_five(list(cards))

        # 6 或 7 张牌：用 Treys 分数枚举所有 C(n,5) 组合找最佳
        treys_cards = [HandEvaluator._to_treys(c) for c in cards]
        best_score = 7463  # Treys 分数 1-7462，7463 为哨兵值
        best_combo: List[Card] = []

        for indices in itertools.combinations(range(n), 5):
            combo_treys = [treys_cards[i] for i in indices]
            score = _treys.evaluate(combo_treys, [])
            if score < best_score:
                best_score = score
                best_combo = [cards[i] for i in indices]  # type: ignore[index]

        return HandEvaluator._evaluate_five(best_combo)

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

    # ---- 内部评估 ----

    @staticmethod
    def _evaluate_five(cards: List[Card]) -> HandResult:
        """评估恰好 5 张牌的手牌。

        使用 Treys 做牌型分类，自行提取踢脚构造 score 元组。
        """
        treys_cards = [HandEvaluator._to_treys(c) for c in cards]
        treys_score = _treys.evaluate(treys_cards, [])
        rank_class = _treys.get_rank_class(treys_score)

        ranks = sorted((c.rank.value for c in cards), reverse=True)
        rank_counts = Counter(ranks)
        most_common = rank_counts.most_common()

        is_flush = len(set(c.suit for c in cards)) == 1
        is_straight, straight_high = HandEvaluator._check_straight(ranks)

        # 同花顺 / 皇家同花顺（Treys rank_class 0 或 1）
        if rank_class <= 1:
            if is_straight and straight_high == 14:  # A-high = 皇家
                return HandResult(HandRank.ROYAL_FLUSH, (9,), cards)
            return HandResult(
                HandRank.STRAIGHT_FLUSH, (8, straight_high), cards
            )

        # 四条
        if rank_class == 2:
            quad_rank = most_common[0][0]
            kicker = most_common[1][0]
            return HandResult(
                HandRank.FOUR_OF_A_KIND, (7, quad_rank, kicker), cards
            )

        # 葫芦
        if rank_class == 3:
            trips_rank = most_common[0][0]
            pair_rank = most_common[1][0]
            return HandResult(
                HandRank.FULL_HOUSE, (6, trips_rank, pair_rank), cards
            )

        # 同花（非顺）
        if rank_class == 4:
            return HandResult(
                HandRank.FLUSH, (5, *ranks), cards
            )

        # 顺子（非同花）
        if rank_class == 5:
            return HandResult(
                HandRank.STRAIGHT, (4, straight_high), cards
            )

        # 三条
        if rank_class == 6:
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
        if rank_class == 7:
            high_pair = max(most_common[0][0], most_common[1][0])
            low_pair = min(most_common[0][0], most_common[1][0])
            kicker = most_common[2][0]
            return HandResult(
                HandRank.TWO_PAIR,
                (2, high_pair, low_pair, kicker),
                cards,
            )

        # 一对
        if rank_class == 8:
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
