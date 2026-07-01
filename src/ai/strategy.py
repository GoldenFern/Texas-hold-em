"""AI 策略引擎 —— 手牌强度、底池赔率、位置评估。

提供 AI 机器人决策所需的所有基础计算。
"""

from __future__ import annotations

import random
from typing import Dict, List, Optional, Tuple

from src.engine.card import Card, Cards
from src.engine.hand import HandEvaluator, HandResult
from src.utils.constants import ActionType, GamePhase, Rank, Suit


# ================================================================
# 翻牌前手牌强度表（0–100 分制）
# ================================================================

# 口袋对子强度
_PAIR_STRENGTH: Dict[int, int] = {
    14: 100,  # AA
    13: 90,   # KK
    12: 80,   # QQ
    11: 70,   # JJ
    10: 60,   # TT
    9: 50,    # 99
    8: 40,    # 88
    7: 35,    # 77
    6: 30,    # 66
    5: 25,    # 55
    4: 20,    # 44
    3: 18,    # 33
    2: 15,    # 22
}

# 同花高牌组合强度
_SUITED_STRENGTH: Dict[Tuple[int, int], int] = {
    (14, 13): 85, (14, 12): 75, (14, 11): 70, (14, 10): 68,
    (14, 9): 62, (14, 8): 58, (14, 7): 52, (14, 6): 48,
    (14, 5): 45, (14, 4): 42, (14, 3): 38, (14, 2): 35,
    (13, 12): 72, (13, 11): 65, (13, 10): 62, (13, 9): 58,
    (13, 8): 54, (13, 7): 50, (13, 6): 46, (13, 5): 42,
    (13, 4): 38, (13, 3): 34, (13, 2): 30,
    (12, 11): 60, (12, 10): 57, (12, 9): 54, (12, 8): 50,
    (12, 7): 46, (12, 6): 42, (12, 5): 38, (12, 4): 34,
    (12, 3): 30, (12, 2): 26,
}

# 非同花高牌组合强度
_OFFSUIT_STRENGTH: Dict[Tuple[int, int], int] = {
    (14, 13): 72, (14, 12): 62, (14, 11): 58, (14, 10): 55,
    (14, 9): 50, (14, 8): 46, (14, 7): 42, (14, 6): 38,
    (14, 5): 35, (14, 4): 32, (14, 3): 28, (14, 2): 25,
    (13, 12): 58, (13, 11): 52, (13, 10): 48, (13, 9): 44,
    (13, 8): 40, (13, 7): 36, (13, 6): 32, (13, 5): 28,
    (13, 4): 24, (13, 3): 20, (13, 2): 16,
    (12, 11): 46, (12, 10): 42, (12, 9): 38, (12, 8): 34,
    (12, 7): 30, (12, 6): 26, (12, 5): 22, (12, 4): 18,
    (12, 3): 14, (12, 2): 10,
}


def preflop_hand_strength(cards: Cards) -> int:
    """评估翻牌前手牌强度（0–100）。

    支持 2 张底牌。未识别的组合默认返回 15。
    """
    if len(cards) != 2:
        return 0

    r1, r2 = cards[0].rank.value, cards[1].rank.value
    suited = cards[0].suit == cards[1].suit

    high = max(r1, r2)
    low = min(r1, r2)

    # 口袋对子
    if r1 == r2:
        return _PAIR_STRENGTH.get(high, 10)

    # 同花
    if suited:
        return _SUITED_STRENGTH.get((high, low), 10)

    # 非同花
    return _OFFSUIT_STRENGTH.get((high, low), 5)


def postflop_hand_strength(hole_cards: Cards, community_cards: Cards) -> float:
    """评估翻牌后手牌强度（0.0–1.0）。

    基于当前牌型在可能牌型中的相对位置。
    """
    if len(community_cards) == 0:
        return preflop_hand_strength(hole_cards) / 100.0

    all_cards = hole_cards + community_cards
    if len(all_cards) < 5:
        return preflop_hand_strength(hole_cards) / 100.0

    result = HandEvaluator.evaluate(all_cards)
    hand_rank = result.hand_rank.value
    # 归一化到 0.0–1.0
    return hand_rank / 9.0


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
        return 0.0  # 庄位本身不在这计算
    # 越靠近庄位越好
    pos_val = relative_pos / num_players
    return round(1.0 - pos_val, 2)


def is_premium_hand(cards: Cards) -> bool:
    """是否为顶级手牌（AA, KK, QQ, AKs, AKo）。"""
    strength = preflop_hand_strength(cards)
    return strength >= 72


def is_playable_hand(cards: Cards) -> bool:
    """是否为可玩手牌（强度 >= 35）。"""
    strength = preflop_hand_strength(cards)
    return strength >= 35


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
