"""蒙特卡洛胜率模拟器 —— 估算手牌在当前局面下的胜率。

通过随机补全剩余公共牌，模拟 N 次对决，统计获胜/平分概率。
"""

from __future__ import annotations

import itertools
import random
from typing import Dict, List, Optional, Set, Tuple

from src.engine.card import Card, Cards
from src.engine.deck import Deck
from src.engine.hand import HandEvaluator
from src.utils.constants import HandRank, Rank, Suit


class EquityCalculator:
    """蒙特卡洛胜率计算器。

    通过大量随机模拟，估算一手或多手牌的胜率。
    """

    def __init__(self, num_simulations: int = 1000, seed: int = 42) -> None:
        self.num_simulations = num_simulations
        self.rng = random.Random(seed)

    def calculate(
        self,
        hole_cards_list: List[Cards],
        community_cards: Optional[Cards] = None,
        dead_cards: Optional[Cards] = None,
    ) -> Dict[str, List[float]]:
        """计算每手牌的胜率。

        Args:
            hole_cards_list: 各玩家的底牌列表。
            community_cards: 已知的公共牌（0–5 张）。
            dead_cards: 已知的已死牌（已被弃/烧）。

        Returns:
            {描述: [胜率, 平率, 负率]} 的字典。
        """
        community = community_cards or []
        dead = dead_cards or []

        # 收集所有已知牌
        known_cards: Set[Card] = set()
        for hand in hole_cards_list:
            for c in hand:
                known_cards.add(c)
        for c in community:
            known_cards.add(c)
        for c in dead:
            known_cards.add(c)

        # 从牌堆中移除已知牌
        remaining = [
            Card(rank=r, suit=s)
            for r, s in itertools.product(Rank, Suit)
            if Card(rank=r, suit=s) not in known_cards
        ]

        needed = 5 - len(community)
        descriptions = [
            " ".join(c.short_str for c in hand)
            for hand in hole_cards_list
        ]

        wins = [0] * len(hole_cards_list)
        ties = [0] * len(hole_cards_list)
        losses = [0] * len(hole_cards_list)

        for _ in range(self.num_simulations):
            # 随机抽取剩余公共牌
            sim_community = community + self.rng.sample(remaining, needed)

            # 评估每手牌
            results = []
            for hand in hole_cards_list:
                all_cards = hand + sim_community
                results.append(HandEvaluator.evaluate(all_cards))

            # 找最佳手牌
            best_score = max(r.score for r in results)
            best_indices = [
                i for i, r in enumerate(results)
                if r.score == best_score
            ]

            if len(best_indices) == 1:
                wins[best_indices[0]] += 1
                for i in range(len(hole_cards_list)):
                    if i != best_indices[0]:
                        losses[i] += 1
            else:
                for i in best_indices:
                    ties[i] += 1
                for i in range(len(hole_cards_list)):
                    if i not in best_indices:
                        losses[i] += 1

        total = self.num_simulations
        return {
            desc: [
                round(w / total, 4),
                round(t / total, 4),
                round(l / total, 4),
            ]
            for desc, w, t, l in zip(descriptions, wins, ties, losses)
        }

    def heads_up_equity(
        self,
        hand_a: Cards,
        hand_b: Cards,
        community_cards: Optional[Cards] = None,
    ) -> Tuple[float, float, float]:
        """双人胜率计算。

        Returns:
            (A胜率, B胜率, 平率)。
        """
        result = self.calculate([hand_a, hand_b], community_cards)
        keys = list(result.keys())
        return (
            result[keys[0]][0],
            result[keys[1]][0],
            result[keys[0]][1],
        )

    def preflop_matchup(self, hand_a_str: str, hand_b_str: str) -> Dict[str, float]:
        """两个起手牌的翻牌前胜率对决。

        Args:
            hand_a_str: 如 "Ah Kh"
            hand_b_str: 如 "2s 2d"

        Returns:
            A胜率, B胜率, 平率。
        """
        hand_a = Card.from_str_multi(hand_a_str)
        hand_b = Card.from_str_multi(hand_b_str)
        win_a, win_b, tie = self.heads_up_equity(hand_a, hand_b)
        return {"win_a": win_a, "win_b": win_b, "tie": tie}


# ================================================================
# 牌型概率计算 —— 实时 Monte Carlo
# ================================================================

def calculate_hand_type_probs(
    hole_cards: Cards,
    community_cards: Optional[Cards] = None,
    num_simulations: int = 5000,
) -> Dict[str, float]:
    """计算凑到各种牌型的条件概率。

    基于已知的底牌和公共牌，通过蒙特卡洛模拟估计最终牌型的概率分布。
    在河牌圈（5 张公共牌全知）时直接评估，无需模拟。

    Args:
        hole_cards: 底牌（2 张）。
        community_cards: 已知的公共牌（0–5 张）。
        num_simulations: 蒙特卡洛模拟次数（默认 5000）。

    Returns:
        {牌型中文名: 概率百分比} 的字典，按牌型等级降序排列。
    """
    community = list(community_cards or [])
    all_known = list(hole_cards) + community

    # 河牌圈：所有牌已知，直接评估
    if len(community) == 5:
        result = HandEvaluator.evaluate(all_known)
        target_rank = result.hand_rank
        probs: Dict[str, float] = {}
        for rank in HandRank:
            probs[rank.display_name] = 100.0 if rank == target_rank else 0.0
        return probs

    # 排除已知牌
    known_set = set(all_known)
    remaining = [
        Card(rank=r, suit=s)
        for r, s in itertools.product(Rank, Suit)
        if Card(rank=r, suit=s) not in known_set
    ]

    needed = 5 - len(community)

    # 初始化各牌型计数器
    counts = {rank: 0 for rank in HandRank}

    rng = random.Random()
    for _ in range(num_simulations):
        sim_community = community + rng.sample(remaining, needed)
        result = HandEvaluator.evaluate(hole_cards + sim_community)
        counts[result.hand_rank] += 1

    # 返回结果（从强到弱排列）
    return {
        rank.display_name: round(counts[rank] / num_simulations * 100, 1)
        for rank in reversed(HandRank)
    }
