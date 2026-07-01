"""扑克牌表示 —— Card、Suit、Rank。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Union

from src.utils.constants import Rank, Suit


@dataclass(frozen=True, slots=True)
class Card:
    """一张扑克牌。

    Attributes:
        rank: 点数（2–14）。
        suit: 花色。
    """

    rank: Rank
    suit: Suit

    # ---- 工厂方法 ----

    @classmethod
    def from_str(cls, s: str) -> Card:
        """从字符串构造，如 'Ah' = A♥, 'Td' = T♦, '2c' = 2♣。"""
        if len(s) < 2:
            raise ValueError(f"无效的牌字符串: {s!r}")
        rank_char = s[0].upper()
        suit_char = s[1].lower()

        rank_map: dict[str, Rank] = {
            "2": Rank.TWO, "3": Rank.THREE, "4": Rank.FOUR,
            "5": Rank.FIVE, "6": Rank.SIX, "7": Rank.SEVEN,
            "8": Rank.EIGHT, "9": Rank.NINE, "T": Rank.TEN,
            "J": Rank.JACK, "Q": Rank.QUEEN, "K": Rank.KING,
            "A": Rank.ACE,
        }
        suit_map: dict[str, Suit] = {
            "c": Suit.CLUBS, "d": Suit.DIAMONDS,
            "h": Suit.HEARTS, "s": Suit.SPADES,
        }

        if rank_char not in rank_map:
            raise ValueError(f"无效的牌面点数: {rank_char!r}")
        if suit_char not in suit_map:
            raise ValueError(f"无效的牌面花色: {suit_char!r}")

        return cls(rank=rank_map[rank_char], suit=suit_map[suit_char])

    @classmethod
    def from_str_multi(cls, s: str) -> List[Card]:
        """从空格分隔的字符串批量构造，如 'Ah Kd Qs'。"""
        if not s.strip():
            return []
        return [cls.from_str(token) for token in s.split()]

    # ---- 字符串表示 ----

    def __str__(self) -> str:
        return f"{self.rank.short}{self.suit.symbol}"

    def __repr__(self) -> str:
        return f"Card({self.rank.name} of {self.suit.name})"

    @property
    def short_str(self) -> str:
        """简短表示，如 'Ah'。"""
        return f"{self.rank.short}{self.suit.short.lower()}"

    # ---- 比较（仅比较点数） ----

    def __lt__(self, other: Card) -> bool:
        return self.rank < other.rank

    def __le__(self, other: Card) -> bool:
        return self.rank <= other.rank

    def __gt__(self, other: Card) -> bool:
        return self.rank > other.rank

    def __ge__(self, other: Card) -> bool:
        return self.rank >= other.rank


# 类型别名
Cards = List[Card]
OptionalCard = Optional[Card]
