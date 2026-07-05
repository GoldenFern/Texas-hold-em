"""共享扑克牌辅助函数 —— 避免各模块重复定义。"""

from __future__ import annotations

import itertools
import random
from typing import Dict, List, Optional

from src.engine.card import Card, Cards
from src.utils.constants import Rank, Suit


def all_cards() -> List[Card]:
    """全部 52 张牌。"""
    return [Card(rank=r, suit=s) for r, s in itertools.product(Rank, Suit)]


def random_hand(rng: random.Random, exclude: Cards) -> Cards:
    """从排除 excluded 后的牌堆中随机抽取 2 张。"""
    excluded_str = {c.short_str for c in exclude}
    available = [c for c in all_cards() if c.short_str not in excluded_str]
    return rng.sample(available, 2)


def detect_draws(hole_cards: Cards, community_cards: Cards) -> tuple:
    """检测听牌。

    Returns:
        (has_flush_draw, has_straight_draw)
    """
    from collections import Counter
    all_c = hole_cards + community_cards

    # 同花听牌
    suit_counts = Counter(c.suit for c in all_c)
    flush_draw = any(count == 4 for count in suit_counts.values())

    # 顺子听牌
    ranks = sorted(set(c.rank.value for c in all_c))
    straight_draw = False
    for i in range(len(ranks) - 3):
        if ranks[i + 3] - ranks[i] <= 4:
            straight_draw = True
            break
    # Ace-low wrap: A-2-3-4
    if 14 in ranks and {2, 3, 4}.issubset(set(ranks)):
        straight_draw = True

    return flush_draw, straight_draw
