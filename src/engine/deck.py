"""扑克牌堆 —— 标准 52 张牌，支持洗牌与发牌。"""

from __future__ import annotations

import random
from typing import List

from src.engine.card import Card
from src.utils.constants import Rank, Suit


class Deck:
    """标准 52 张扑克牌堆。

    支持洗牌、发牌、重置操作。可作为迭代器使用。
    """

    def __init__(self) -> None:
        self._cards: List[Card] = []
        self.reset()

    # ---- 基本操作 ----

    def reset(self) -> None:
        """重置为一副完整的 52 张牌（未洗牌）。"""
        self._cards = [
            Card(rank=rank, suit=suit)
            for suit in Suit
            for rank in Rank
        ]

    def shuffle(self) -> None:
        """Fisher–Yates 洗牌。"""
        random.shuffle(self._cards)

    def deal(self, n: int = 1) -> List[Card]:
        """从牌堆顶部发 n 张牌。

        Args:
            n: 发牌数量。

        Returns:
            发出的牌列表。

        Raises:
            ValueError: 牌堆剩余牌不足。
        """
        if n < 0:
            raise ValueError(f"发牌数量不能为负: {n}")
        if n > len(self._cards):
            raise ValueError(
                f"牌堆仅剩 {len(self._cards)} 张牌，无法发 {n} 张"
            )
        dealt: List[Card] = []
        for _ in range(n):
            dealt.append(self._cards.pop())
        return dealt

    def deal_one(self) -> Card:
        """发一张牌。"""
        return self.deal(1)[0]

    # ---- 信息 ----

    def __len__(self) -> int:
        return len(self._cards)

    def __bool__(self) -> bool:
        return len(self._cards) > 0

    @property
    def remaining(self) -> int:
        """剩余牌数。"""
        return len(self._cards)

    def __iter__(self):
        return iter(self._cards)

    def __repr__(self) -> str:
        return f"Deck(remaining={len(self._cards)})"
