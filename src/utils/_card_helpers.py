"""共享扑克牌辅助 —— 缓存牌表、Treys 快速通道、听牌/outs 检测。"""

from __future__ import annotations

import itertools
import random
from collections import Counter
from dataclasses import dataclass
from typing import Dict, List, Tuple

from treys import Card as TreysCard

from src.engine.card import Card, Cards
from src.utils.constants import Rank, Suit

# 预建 52 张牌常量表（避免热循环反复构造 Card 对象）
ALL_CARDS: Tuple[Card, ...] = tuple(
    Card(rank=r, suit=s) for r, s in itertools.product(Rank, Suit)
)

# short_str -> Treys 整数表示（MC 热循环全程用 int，零对象开销）
TREYS_BY_STR: Dict[str, int] = {c.short_str: TreysCard.new(c.short_str) for c in ALL_CARDS}

# 全牌堆的 Treys 整数表
ALL_TREYS: Tuple[int, ...] = tuple(TREYS_BY_STR[c.short_str] for c in ALL_CARDS)


def all_cards() -> List[Card]:
    """全部 52 张牌（返回缓存表的拷贝列表）。"""
    return list(ALL_CARDS)


def treys_ids(cards: Cards) -> List[int]:
    """将项目 Card 列表转为 Treys 整数列表。"""
    return [TREYS_BY_STR[c.short_str] for c in cards]


def treys_pool(exclude: Cards) -> List[int]:
    """排除指定牌后的 Treys 整数牌池。"""
    excluded = {TREYS_BY_STR[c.short_str] for c in exclude}
    return [t for t in ALL_TREYS if t not in excluded]


def random_hand(rng: random.Random, exclude: Cards) -> Cards:
    """从排除 exclude 后的牌堆中随机抽取 2 张。"""
    excluded_str = {c.short_str for c in exclude}
    available = [c for c in ALL_CARDS if c.short_str not in excluded_str]
    return rng.sample(available, 2)


# ================================================================
# 听牌与 outs 检测
# ================================================================

@dataclass
class DrawInfo:
    """听牌信息。

    Attributes:
        made_flush: 已成同花（≥5 张同色且含至少 1 张底牌）。
        flush_draw: 同花听牌（恰 4 张同色且含至少 1 张底牌，未成花）。
        made_straight: 已成顺子（5 连且含至少 1 张底牌的牌面参与）。
        straight_draw: "oesd"（两头/双卡, ≥2 个补牌点数）、
            "gutshot"（单卡）或 "none"。
        outs: 完成同花/顺子的补牌张数（去重后的并集）。
    """

    made_flush: bool = False
    flush_draw: bool = False
    made_straight: bool = False
    straight_draw: str = "none"
    outs: int = 0


def _has_five_run(rank_values: set) -> bool:
    """点数集合中是否存在 5 连（含 A-low 轮子）。"""
    vals = set(rank_values)
    if 14 in vals:
        vals.add(1)  # A 可作 1
    return any(
        all(v + i in vals for i in range(5))
        for v in range(1, 11)
    )


def count_outs(hole_cards: Cards, community_cards: Cards) -> DrawInfo:
    """检测同花/顺子听牌并统计 outs。

    仅统计与底牌相关的听牌：纯公共牌构成的听牌属于所有人，不计。

    Args:
        hole_cards: 底牌（2 张）。
        community_cards: 公共牌（3–5 张）。

    Returns:
        DrawInfo 数据对象。
    """
    info = DrawInfo()
    if len(community_cards) < 3:
        return info

    all_c = list(hole_cards) + list(community_cards)
    seen = {c.short_str for c in all_c}
    hole_suits = {c.suit for c in hole_cards}
    hole_ranks = {c.rank.value for c in hole_cards}

    # ---- 同花 ----
    suit_counts = Counter(c.suit for c in all_c)
    out_cards: set = set()
    for suit, count in suit_counts.items():
        if suit not in hole_suits:
            continue  # 纯公共牌同花不算 Hero 的成花/听牌
        if count >= 5:
            info.made_flush = True
        elif count == 4:
            info.flush_draw = True
            for r in Rank:
                c = Card(rank=r, suit=suit)
                if c.short_str not in seen:
                    out_cards.add(c.short_str)

    # ---- 顺子 ----
    rank_values = {c.rank.value for c in all_c}
    community_values = {c.rank.value for c in community_cards}
    if _has_five_run(rank_values) and not _has_five_run(community_values):
        info.made_straight = True
    elif not _has_five_run(rank_values):
        completing_ranks: set = set()
        for v in range(2, 15):
            if v in rank_values:
                continue
            if _has_five_run(rank_values | {v}):
                # 要求完成的 5 连用到至少一张底牌
                vals = rank_values | {v}
                if 14 in vals:
                    vals = vals | {1}
                uses_hole = False
                for start in range(1, 11):
                    window = {start + i for i in range(5)}
                    if window <= vals and v in window:
                        hole_in = hole_ranks | ({1} if 14 in hole_ranks else set())
                        if window & hole_in:
                            uses_hole = True
                            break
                if not uses_hole:
                    continue
                completing_ranks.add(v)
        if completing_ranks:
            info.straight_draw = "oesd" if len(completing_ranks) >= 2 else "gutshot"
            for v in completing_ranks:
                rank = next(r for r in Rank if r.value == v)
                for s in Suit:
                    c = Card(rank=rank, suit=s)
                    if c.short_str not in seen:
                        out_cards.add(c.short_str)

    info.outs = len(out_cards)
    return info


def detect_draws(hole_cards: Cards, community_cards: Cards) -> tuple:
    """检测听牌（兼容旧接口）。

    Returns:
        (has_flush_draw, has_straight_draw)
    """
    info = count_outs(hole_cards, community_cards)
    return info.flush_draw, info.straight_draw != "none"
