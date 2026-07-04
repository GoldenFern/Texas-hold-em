"""AI 策略引擎 —— 手牌强度、底池赔率、位置评估。

提供 AI 机器人决策所需的所有基础计算。

翻牌前手牌评分基于预计算的 Monte Carlo 胜率表（模块加载时一次性计算），
翻牌后手牌强度基于 Treys 加速的 Monte Carlo 实时胜率估算。
"""

from __future__ import annotations

import itertools
import logging
import random
from typing import Dict, List, Optional, Tuple

from src.engine.card import Card, Cards
from src.engine.hand import HandEvaluator, HandResult
from src.utils.constants import ActionType, GamePhase, Rank, Suit

logger = logging.getLogger(__name__)


# ================================================================
# 翻牌前手牌胜率表 —— 模块加载时一次性预计算
# ================================================================

def _build_preflop_equity_table() -> Dict[Tuple[int, int, bool], float]:
    """构建 169 种起手牌的翻牌前胜率表（vs 1 个随机对手）。

    使用 Treys 加速的 Monte Carlo 模拟，每种手牌 500 次模拟。
    模块加载时执行一次，O(169 × 500) ≈ 84,500 次评估。
    """
    ranks = list(Rank)
    rng = random.Random(42)
    num_sim = 500
    table: Dict[Tuple[int, int, bool], float] = {}

    logger.info("构建翻牌前胜率表（169 种起手牌 × %d 次模拟）...", num_sim)

    for i, r1 in enumerate(ranks):
        for j, r2 in enumerate(ranks):
            if i < j:
                continue  # 只处理 canonical 形式 (high, low)，high 索引 >= low

            high = r1.value
            low = r2.value
            is_pair = (high == low)

            # 非同花
            card_a = Card(rank=r1, suit=Suit.CLUBS)
            card_b = Card(rank=r2, suit=Suit.DIAMONDS)
            hand = [card_a, card_b]
            key_offsuit = (high, low, False)
            table[key_offsuit] = _simulate_equity(hand, rng, num_sim)

            # 同花（只有非对子时才需要独立计算）
            if not is_pair:
                card_b2 = Card(rank=r2, suit=Suit.CLUBS)
                hand_suited = [card_a, card_b2]
                key_suited = (high, low, True)
                table[key_suited] = _simulate_equity(hand_suited, rng, num_sim)

    logger.info("翻牌前胜率表构建完成：%d 种手牌", len(table))
    return table


def _simulate_equity(
    hand: List[Card],
    rng: random.Random,
    num_sim: int,
) -> float:
    """模拟一手牌 vs 随机对手 + 随机公共牌的胜率。"""
    wins = 0.0
    for _ in range(num_sim):
        opponent = _random_hand(hand, rng)
        sim_community = _random_community(hand + opponent, rng)
        result_a = HandEvaluator.evaluate(hand + sim_community)
        result_b = HandEvaluator.evaluate(opponent + sim_community)
        if result_a > result_b:
            wins += 1.0
        elif result_a == result_b:
            wins += 0.5
    return round(wins / num_sim * 100.0, 1)


def _random_hand(exclude: List[Card], rng: random.Random) -> List[Card]:
    """从排除指定牌后的牌堆中随机抽取 2 张作为对手手牌。"""
    excluded = {c.short_str for c in exclude}
    available = [
        Card(rank=r, suit=s)
        for r, s in itertools.product(Rank, Suit)
        if Card(rank=r, suit=s).short_str not in excluded
    ]
    return rng.sample(available, 2)


def _random_community(exclude: List[Card], rng: random.Random) -> List[Card]:
    """从排除指定牌后的牌堆中随机抽取 5 张公共牌。"""
    excluded = {c.short_str for c in exclude}
    available = [
        Card(rank=r, suit=s)
        for r, s in itertools.product(Rank, Suit)
        if Card(rank=r, suit=s).short_str not in excluded
    ]
    return rng.sample(available, 5)


# 模块级预计算表（导入时执行）
_PREFLOP_EQUITY: Dict[Tuple[int, int, bool], float] = _build_preflop_equity_table()


# ================================================================
# 翻牌前手牌强度（0–100）—— 基于真实胜率
# ================================================================

def preflop_hand_strength(cards: Cards) -> int:
    """评估翻牌前手牌强度（0–100），基于真实胜率。

    对 2 张底牌，返回 vs 1 个随机对手的 Monte Carlo 胜率 × 100。
    未覆盖的组合默认返回 32（最差手牌的胜率）。
    """
    if len(cards) != 2:
        return 0

    r1, r2 = cards[0].rank.value, cards[1].rank.value
    suited = cards[0].suit == cards[1].suit

    high = max(r1, r2)
    low = min(r1, r2)
    key = (high, low, suited)

    if key in _PREFLOP_EQUITY:
        return int(_PREFLOP_EQUITY[key])

    # fallback（不应到达）
    return 32


# ================================================================
# 翻牌后手牌强度（0.0–1.0）—— 实时 Monte Carlo 胜率
# ================================================================

def postflop_hand_strength(
    hole_cards: Cards,
    community_cards: Cards,
    num_simulations: int = 300,
) -> float:
    """评估翻牌后手牌强度（0.0–1.0），基于实时 Monte Carlo 胜率。

    对已知公共牌进行随机补全模拟，计算 vs 1 个随机对手的胜率。

    Args:
        hole_cards: 底牌（2 张）。
        community_cards: 已知公共牌（0–5 张）。
        num_simulations: 模拟次数（默认 300，已够用）。

    Returns:
        0.0–1.0 的实际胜率。
    """
    if len(community_cards) == 0:
        return preflop_hand_strength(hole_cards) / 100.0

    all_cards = hole_cards + community_cards
    if len(all_cards) < 5:
        return preflop_hand_strength(hole_cards) / 100.0

    rng = random.Random()
    excluded = {c.short_str for c in all_cards}

    # 对手随机手牌
    available_hole = [
        Card(rank=r, suit=s)
        for r, s in itertools.product(Rank, Suit)
        if Card(rank=r, suit=s).short_str not in excluded
    ]
    if len(available_hole) < 2:
        return preflop_hand_strength(hole_cards) / 100.0

    # 剩余公共牌
    needed = 5 - len(community_cards)
    available_community = [
        Card(rank=r, suit=s)
        for r, s in itertools.product(Rank, Suit)
        if Card(rank=r, suit=s).short_str not in excluded
    ]

    wins = 0.0
    for _ in range(num_simulations):
        opponent = rng.sample(available_hole, 2)
        # 对手手牌也需要从社区牌池中排除
        opponent_excluded = excluded.copy()
        opponent_excluded.update(c.short_str for c in opponent)
        available_community_filtered = [
            c for c in available_community
            if c.short_str not in opponent_excluded
        ]
        sim_board = (
            list(community_cards)
            + rng.sample(available_community_filtered, needed)
        )
        result_hero = HandEvaluator.evaluate(hole_cards + sim_board)
        result_villain = HandEvaluator.evaluate(opponent + sim_board)
        if result_hero > result_villain:
            wins += 1.0
        elif result_hero == result_villain:
            wins += 0.5

    return round(wins / num_simulations, 4)


# ================================================================
# 听牌检测
# ================================================================

def has_draw(hole_cards: Cards, community_cards: Cards) -> Tuple[bool, bool]:
    """检测听牌。

    Returns:
        (has_flush_draw, has_straight_draw)
    """
    if len(community_cards) < 3:
        return False, False

    all_cards = hole_cards + community_cards

    # 同花听牌：同花色 >= 4 张
    suit_counts: Dict[Suit, int] = {}
    for c in all_cards:
        suit_counts[c.suit] = suit_counts.get(c.suit, 0) + 1
    flush_draw = any(count == 4 for count in suit_counts.values())

    # 顺子听牌：检查是否有 4 张连续的 rank
    ranks = sorted(set(c.rank.value for c in all_cards))
    straight_draw = False
    for i in range(len(ranks) - 3):
        if ranks[i + 3] - ranks[i] <= 4:
            straight_draw = True
            break
    # 检查 Ace-low wrap
    if 14 in ranks and {2, 3, 4}.issubset(set(ranks)):
        straight_draw = True

    return flush_draw, straight_draw


# ================================================================
# 底池赔率 & 位置价值
# ================================================================

def calculate_pot_odds(call_amount: int, pot_total: int) -> float:
    """计算底池赔率。

    Returns:
        跟注所需的最低胜率（0.0–1.0）。
    """
    if pot_total + call_amount == 0:
        return 0.0
    return call_amount / (pot_total + call_amount)


def position_value(seat: int, dealer_seat: int, num_players: int) -> float:
    """计算位置价值（0.0–1.0，越高越好）。

    庄位 = 1.0, 枪口位 ≈ 0.3。
    """
    relative_pos = (seat - dealer_seat) % num_players
    if relative_pos == 0:
        return 0.0
    pos_val = relative_pos / num_players
    return round(1.0 - pos_val, 2)


# ================================================================
# 手牌品质判定
# ================================================================

def is_premium_hand(cards: Cards) -> bool:
    """是否为顶级手牌（胜率 >= 70% vs 随机手牌）。

    典型覆盖：AA(85), KK(82), QQ(80), JJ(77), AKs(67)...
    阈值 70 覆盖 AA/KK/QQ/JJ。
    """
    strength = preflop_hand_strength(cards)
    return strength >= 70


def is_playable_hand(cards: Cards) -> bool:
    """是否为可玩手牌（胜率 >= 45% vs 随机手牌）。"""
    strength = preflop_hand_strength(cards)
    return strength >= 45


# ================================================================
# 动作随机化
# ================================================================

def randomize_action(
    actions: List[Tuple[ActionType, float]],
    rng: Optional[random.Random] = None,
) -> ActionType:
    """按权重随机选择一个动作。

    Args:
        actions: (动作类型, 权重) 列表。
        rng: 可选的随机数生成器。

    Returns:
        按权重随机选中的动作类型。
    """
    if rng is None:
        rng = random.Random()

    total = sum(w for _, w in actions)
    if total <= 0:
        return actions[0][0] if actions else ActionType.FOLD

    r = rng.random() * total
    cumulative = 0.0
    for action, weight in actions:
        cumulative += weight
        if r <= cumulative:
            return action
    return actions[-1][0]
