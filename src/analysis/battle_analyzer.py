"""统一战局分析引擎 —— 蒙特卡洛模拟 + 赔率/EV + 底池财务。

单次模拟循环同时收集：
1. Hero 最终牌型分布（牌型概率）
2. Hero 在对阵 N 个对手时的排名分布（排名分布律）

基于蒙特卡洛结果计算：胜率、底池赔率、隐含赔率、EV、底池财务。
"""

from __future__ import annotations

import itertools
import random
from typing import Dict, List, Optional, Tuple

from src.engine.card import Card, Cards
from src.engine.game import GameState
from src.engine.hand import HandEvaluator
from src.engine.player import Player
from src.utils.constants import HandRank, Rank, Suit

# Benchmark 确定的模拟次数（由 scripts/benchmark_sim.py 生成）
try:
    from src.analysis._benchmark_result import M_PREFLOP, M_POSTFLOP
except ImportError:
    M_PREFLOP = 227
    M_POSTFLOP = 45


# ---- 辅助函数 ----

def _all_cards() -> List[Card]:
    """全部 52 张牌。"""
    return [Card(rank=r, suit=s) for r, s in itertools.product(Rank, Suit)]


def _random_hand(rng: random.Random, exclude: Cards) -> Cards:
    """从排除 excluded 后的牌堆中随机抽取 2 张。"""
    excluded_str = {c.short_str for c in exclude}
    available = [c for c in _all_cards() if c.short_str not in excluded_str]
    return rng.sample(available, 2)


class BattleAnalyzer:
    """统一战局分析器。

    一次 analyze() 调用完成全部 4 块分析：
      - 牌型概率 (hand_type_probs)
      - 排名分布律 (ranking_distribution)
      - 赔率与期望值 (odds_ev)
      - 底池财务 (pot_financials)
    """

    def __init__(
        self,
        preflop_sims: int = M_PREFLOP,
        postflop_sims: int = M_POSTFLOP,
        seed: int | None = None,
    ) -> None:
        self.preflop_sims = preflop_sims
        self.postflop_sims = postflop_sims
        self._rng = random.Random(seed)

    def analyze(
        self,
        hole_cards: Cards,
        community_cards: Cards,
        active_opponent_count: int,
        game: GameState,
        player: Player,
    ) -> dict:
        """执行完整分析，返回前端可用的字典。

        每次调用根据输入状态生成确定性种子重置 RNG，
        保证相同局面下分析结果稳定不抖动。
        """
        # 确定性种子：基于手牌 + 公共牌 + 对手数 + 跟注额
        # 跟注额可能在同一轮下注中变化，但 check 不会改变它
        to_call = max(0, game.current_bet - player.current_bet)
        state_key = (
            tuple(c.short_str for c in sorted(hole_cards, key=lambda c: c.short_str)),
            tuple(c.short_str for c in sorted(community_cards, key=lambda c: c.short_str)),
            active_opponent_count,
            to_call,
        )
        self._rng = random.Random(hash(state_key) & 0x7FFFFFFF)

        n_community = len(community_cards)

        # 河牌：全部已知，直接评估
        if n_community == 5:
            return self._analyze_river(hole_cards, community_cards, active_opponent_count, game, player)

        # 翻牌前/翻牌/转牌：蒙特卡洛
        num_sims = self.preflop_sims if n_community == 0 else self.postflop_sims

        # 单次循环同时收集牌型 + 排名
        hand_type_probs, ranking_dist = self._run_monte_carlo(
            hole_cards, community_cards, active_opponent_count, num_sims
        )

        # 赔率/EV
        odds_ev = self._calc_odds_ev(game, player, active_opponent_count, ranking_dist)

        # 底池财务
        pot_financials = self._calc_pot_financials(game, player)

        return {
            "hand_type_probs": hand_type_probs,
            "ranking_distribution": ranking_dist,
            "odds_ev": odds_ev,
            "pot_financials": pot_financials,
            "sim_count": num_sims,
        }

    # ---- 蒙特卡洛模拟（单循环） ----

    def _run_monte_carlo(
        self,
        hole_cards: Cards,
        community: Cards,
        opponent_count: int,
        num_sims: int,
    ) -> Tuple[Dict[str, float], List[dict]]:
        """执行蒙特卡洛模拟，同时收集牌型概率和排名分布律。

        Returns:
            (hand_type_probs, ranking_distribution)
        """
        # 排除已知牌
        excluded: Cards = list(hole_cards) + list(community)

        # 初始化计数器
        hand_type_counts = {rank: 0 for rank in HandRank}
        rank_counts: Dict[int, int] = {}  # rank_position -> count

        needed = 5 - len(community)

        for _ in range(num_sims):
            # 随机发 N 个对手手牌
            current_excluded: Cards = list(excluded)
            opponent_hands: List[Cards] = []
            for _ in range(opponent_count):
                opp = _random_hand(self._rng, current_excluded)
                opponent_hands.append(opp)
                current_excluded.extend(opp)

            # 随机补全公共牌
            excluded_str = {c.short_str for c in current_excluded}
            available = [c for c in _all_cards() if c.short_str not in excluded_str]
            sim_board = list(community) + self._rng.sample(available, needed)

            # 评估 Hero 手牌
            hero_result = HandEvaluator.evaluate(hole_cards + sim_board)
            hand_type_counts[hero_result.hand_rank] += 1

            # 评估所有对手手牌，确定 Hero 排名
            hero_score = hero_result.score
            rank = 1
            for opp_hand in opponent_hands:
                opp_result = HandEvaluator.evaluate(opp_hand + sim_board)
                if opp_result.score > hero_score:
                    rank += 1
            rank_counts[rank] = rank_counts.get(rank, 0) + 1

        # 转换为概率
        hand_type_probs = {
            rank.display_name: round(hand_type_counts[rank] / num_sims * 100, 1)
            for rank in reversed(HandRank)
        }

        # 完整排名分布（1 到 opponent_count+1，缺口概率为 0）
        max_rank = opponent_count + 1
        ranking_distribution = []
        for r in range(1, max_rank + 1):
            count = rank_counts.get(r, 0)
            prob = round(count / num_sims * 100, 1)
            rank_label = f"第{r}名" if count > 0 else f"第{r}名"
            ranking_distribution.append({
                "rank": r,
                "desc": rank_label,
                "prob": prob,
            })

        # 汇总并列情况：P(rank=1)=胜率, 其余为排名后位
        # 重新计算以展示格式
        ranking_distribution = []
        for r in range(1, max_rank + 1):
            count = rank_counts.get(r, 0)
            prob = round(count / num_sims * 100, 1)
            if r == 1:
                desc = f"第1名 (胜)"
            elif r == 2:
                desc = f"第2名"
            elif r == max_rank:
                desc = f"第{r}名 (最差)"
            else:
                desc = f"第{r}名"
            ranking_distribution.append({
                "rank": r,
                "desc": desc,
                "prob": prob,
            })

        return hand_type_probs, ranking_distribution

    # ---- 河牌直接评估 ----

    def _analyze_river(
        self,
        hole_cards: Cards,
        community_cards: Cards,
        active_opponent_count: int,
        game: GameState,
        player: Player,
    ) -> dict:
        """河牌圈直接评估（牌型确定，排名分布用 MC 确定）。"""
        result = HandEvaluator.evaluate(hole_cards + community_cards)

        hand_type_probs = {}
        for rank in HandRank:
            hand_type_probs[rank.display_name] = 100.0 if rank == result.hand_rank else 0.0

        # 排名分布律：如果还有对手，用 MC 模拟确定 vs 对手随机手牌的排名
        if active_opponent_count > 0:
            _, ranking_dist = self._run_monte_carlo(
                hole_cards, community_cards, active_opponent_count, self.postflop_sims
            )
        else:
            ranking_dist = [{"rank": 1, "desc": "第1名 (胜)", "prob": 100.0}]

        odds_ev = self._calc_odds_ev(game, player, active_opponent_count, ranking_dist)
        pot_financials = self._calc_pot_financials(game, player)

        return {
            "hand_type_probs": hand_type_probs,
            "ranking_distribution": ranking_dist,
            "odds_ev": odds_ev,
            "pot_financials": pot_financials,
            "sim_count": 0,
        }

    # ---- 赔率与期望值 ----

    def _calc_odds_ev(
        self,
        game: GameState,
        player: Player,
        opponent_count: int,
        ranking_distribution: List[dict],
    ) -> dict:
        """计算底池赔率、隐含赔率、期望值。

        胜率直接取自排名分布律的 P(rank=1)。
        """
        # 胜率 = P(rank=1)
        win_rate = 0.0
        for entry in ranking_distribution:
            if entry["rank"] == 1:
                win_rate = entry["prob"] / 100.0
                break

        to_call = max(0, game.current_bet - player.current_bet)
        pot_total = game.pot.total

        # 底池赔率
        if to_call > 0:
            pot_after_call = pot_total + to_call
            pot_odds_ratio = round(pot_after_call / to_call, 2)
            required_equity = round(to_call / pot_after_call * 100, 1)
        else:
            pot_odds_ratio = 0.0
            required_equity = 0.0

        # EV / 底池权益
        if to_call > 0:
            ev = round(win_rate * pot_total - (1.0 - win_rate) * to_call, 2)
            ev_judgment = "正期望 [+EV]" if ev >= 0 else "负期望 [-EV]"
            has_call = True
        else:
            # 无需跟注，不存在 EV 决策——显示底池权益（期望份额）
            equity = round(win_rate * pot_total, 2)
            ev = equity
            ev_judgment = "免跟注 · 底池权益"
            has_call = False

        return {
            "win_rate": round(win_rate * 100, 1),
            "pot_odds_ratio": pot_odds_ratio,
            "required_equity": required_equity,
            "ev": ev,
            "ev_judgment": ev_judgment,
            "to_call": to_call,
            "has_call_decision": has_call,
        }

    # ---- 底池财务 ----

    def _calc_pot_financials(
        self,
        game: GameState,
        player: Player,
    ) -> dict:
        """计算底池财务指标。"""
        pot_total = game.pot.total
        to_call = max(0, game.current_bet - player.current_bet)

        # 死钱：已弃牌玩家的投入
        dead_money = sum(
            p.total_bet for p in game.players
            if p.is_folded
        )

        # 沉没成本：Hero 本手牌已投入的总筹码
        sunk_cost = player.total_bet

        return {
            "pot_total": pot_total,
            "dead_money": dead_money,
            "sunk_cost": sunk_cost,
            "to_call": to_call,
        }
