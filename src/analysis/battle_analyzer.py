"""统一战局分析引擎 —— 蒙特卡洛模拟 + 赔率/EV + 底池财务。

单次模拟循环同时收集：
1. Hero 最终牌型分布（牌型概率）
2. Hero 在对阵 N 个对手时的排名分布（排名分布律）

基于蒙特卡洛结果计算：胜率、底池赔率、隐含赔率、EV、底池财务。
"""

from __future__ import annotations

import random
import zlib
from collections import OrderedDict
from typing import Dict, List, Tuple

from treys import Evaluator as _TreysEvaluator

from src.engine.card import Cards
from src.engine.game import GameState
from src.engine.hand import HandEvaluator
from src.engine.player import Player
from src.utils._card_helpers import treys_ids, treys_pool
from src.utils.constants import HandRank
from src.utils.poker_math import mc_ci95, pot_odds

_treys = _TreysEvaluator()

# Treys rank class (1–9) -> 项目 HandRank
_TREYS_CLASS_TO_HANDRANK: Dict[int, HandRank] = {
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

# Benchmark 确定的模拟次数（由 scripts/benchmark_sim.py 生成）
try:
    from src.analysis._benchmark_result import M_PREFLOP, M_POSTFLOP
except ImportError:
    M_PREFLOP = 227
    M_POSTFLOP = 45


class BattleAnalyzer:
    """统一战局分析器。

    一次 analyze() 调用完成全部 4 块分析：
      - 牌型概率 (hand_type_probs)
      - 排名分布律 (ranking_distribution)
      - 赔率与期望值 (odds_ev)
      - 底池财务 (pot_financials)
    """

    _CACHE_SIZE = 256

    def __init__(
        self,
        preflop_sims: int = M_PREFLOP,
        postflop_sims: int = M_POSTFLOP,
        seed: int | None = None,
    ) -> None:
        self.preflop_sims = preflop_sims
        self.postflop_sims = postflop_sims
        self._rng = random.Random(seed)
        # MC 结果按 (手牌, 公共牌, 对手数, 次数) 缓存——赔率/财务每次现算
        self._mc_cache: "OrderedDict[tuple, Tuple[Dict[str, float], List[dict]]]" = (
            OrderedDict()
        )

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
        n_community = len(community_cards)

        # 河牌：全部已知，直接评估
        if n_community == 5:
            return self._analyze_river(hole_cards, community_cards, active_opponent_count, game, player)

        # 翻牌前/翻牌/转牌：蒙特卡洛
        num_sims = self.preflop_sims if n_community == 0 else self.postflop_sims

        if num_sims <= 0:
            # 跳过 MC（Bot 翻牌前用 preflop_hand_strength 查表）
            odds_ev = self._calc_odds_ev_raw(game, player, active_opponent_count)
            pot_financials = self._calc_pot_financials(game, player)
            return {
                "hand_type_probs": {},
                "ranking_distribution": [],
                "odds_ev": odds_ev,
                "pot_financials": pot_financials,
                "sim_count": 0,
            }

        # 单次循环同时收集牌型 + 排名（结果按状态缓存）
        hand_type_probs, ranking_dist = self._mc_cached(
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

    # ---- 蒙特卡洛模拟（单循环，Treys 整数热路径） ----

    def _mc_cached(
        self,
        hole_cards: Cards,
        community: Cards,
        opponent_count: int,
        num_sims: int,
    ) -> Tuple[Dict[str, float], List[dict]]:
        """带 LRU 缓存与确定性种子的 MC 入口。

        种子由状态派生（zlib.crc32，跨进程可复现），同一局面
        重复调用直接命中缓存。
        """
        key = (
            tuple(sorted(c.short_str for c in hole_cards)),
            tuple(sorted(c.short_str for c in community)),
            opponent_count,
            num_sims,
        )
        cached = self._mc_cache.get(key)
        if cached is not None:
            self._mc_cache.move_to_end(key)
            return cached

        seed = zlib.crc32(repr(key).encode("utf-8"))
        rng = random.Random(seed)
        result = self._run_monte_carlo(
            hole_cards, community, opponent_count, num_sims, rng
        )

        self._mc_cache[key] = result
        if len(self._mc_cache) > self._CACHE_SIZE:
            self._mc_cache.popitem(last=False)
        return result

    def _run_monte_carlo(
        self,
        hole_cards: Cards,
        community: Cards,
        opponent_count: int,
        num_sims: int,
        rng: random.Random,
    ) -> Tuple[Dict[str, float], List[dict]]:
        """执行蒙特卡洛模拟，同时收集牌型概率和排名分布律。

        热循环全程使用 Treys 整数与单次查表调用；转牌圈只剩一张
        未知公共牌时，对全部剩余河牌做精确枚举以降低方差。

        平局按 equity share 处理：与 k 个对手平分时 Hero 的
        equity 为 1/(k+1)。
        """
        hero = treys_ids(hole_cards)
        board_known = treys_ids(community)
        pool = treys_pool(list(hole_cards) + list(community))
        needed = 5 - len(board_known)

        hand_type_counts: Dict[HandRank, int] = {rank: 0 for rank in HandRank}
        rank_counts: Dict[int, int] = {}
        equity_sum = 0.0
        total_outcomes = 0

        evaluate = _treys.evaluate
        get_class = _treys.get_rank_class

        # 转牌圈精确枚举河牌：外层抽对手，内层遍历全部剩余牌
        enumerate_river = needed == 1 and opponent_count > 0
        outer = max(1, num_sims // max(1, len(pool) - 2 * opponent_count))             if enumerate_river else num_sims

        for _ in range(outer):
            drawn = rng.sample(pool, 2 * opponent_count + (0 if enumerate_river else needed))
            opp_hands = [
                drawn[2 * i:2 * i + 2] for i in range(opponent_count)
            ]

            if enumerate_river:
                drawn_set = set(drawn)
                rivers = [t for t in pool if t not in drawn_set]
                boards = [board_known + [rv] for rv in rivers]
            else:
                boards = [board_known + drawn[2 * opponent_count:]]

            for board in boards:
                hero_score = evaluate(hero, board)
                hand_type_counts[
                    _TREYS_CLASS_TO_HANDRANK[get_class(hero_score)]
                    if hero_score != 1 else HandRank.ROYAL_FLUSH
                ] += 1

                better = 0
                tied = 0
                for opp in opp_hands:
                    opp_score = evaluate(opp, board)
                    if opp_score < hero_score:  # Treys 分数越小越强
                        better += 1
                    elif opp_score == hero_score:
                        tied += 1

                rank_counts[better + 1] = rank_counts.get(better + 1, 0) + 1
                if better == 0:
                    equity_sum += 1.0 / (1.0 + tied)
                total_outcomes += 1

        n = max(1, total_outcomes)
        hand_type_probs = {
            rank.display_name: round(hand_type_counts[rank] / n * 100, 1)
            for rank in reversed(HandRank)
        }

        max_rank = opponent_count + 1
        ranking_distribution = []
        for r in range(1, max_rank + 1):
            ranking_distribution.append({
                "rank": r,
                "desc": f"第{r}名",
                "prob": round(rank_counts.get(r, 0) / n * 100, 1),
            })

        # equity share 附加条目（rank=-1 标记），并附带样本量供 CI 计算
        avg_equity = equity_sum / n
        ranking_distribution.append({
            "rank": -1,
            "desc": "equity",
            "prob": round(avg_equity * 100, 1),
            "samples": total_outcomes,
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
            _, ranking_dist = self._mc_cached(
                hole_cards, community_cards, active_opponent_count, self.postflop_sims
            )
        else:
            ranking_dist = [{"rank": 1, "desc": "第1名", "prob": 100.0}]

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
        """计算底池赔率、期望值。

        使用 equity share（已处理平局）替代简单的 P(rank=1)。
        to_call 裁剪到玩家筹码，底池按玩家可争夺的边池过滤。
        """
        # 提取 equity share（由 _run_monte_carlo 存入 ranking_distribution 尾部）
        equity_share = 0.0
        win_rate_display = 0.0
        mc_samples = 0
        for entry in ranking_distribution:
            if entry.get("rank") == -1:  # equity 标记
                equity_share = entry["prob"] / 100.0
                mc_samples = entry.get("samples", 0)
            elif entry.get("rank") == 1:
                win_rate_display = entry["prob"] / 100.0  # 纯显示用

        # to_call 裁剪到玩家可承担的筹码
        to_call = max(0, min(
            game.current_bet - player.current_bet,
            player.chips,
        ))

        # 底池按玩家可争夺的部分过滤（摊牌分层后排除无法赢取的边池）
        pot_total = game.pot.total
        if game.pot.side_pots:
            pot_total = game.pot.get_pot_for_player(player.name)

        # 底池赔率
        if to_call > 0:
            pot_odds_ratio = round(pot_total / to_call, 2)
            required_equity = round(pot_odds(to_call, pot_total) * 100, 1)
        else:
            pot_odds_ratio = 0.0
            required_equity = 0.0

        # EV / 底池权益（使用 equity share 替代 win_rate）
        if to_call > 0:
            ev = round(equity_share * (pot_total + to_call) - to_call, 2)
            ev_judgment = "正期望 [+EV]" if ev >= 0 else "负期望 [-EV]"
            has_call = True
        else:
            # 无需跟注，不存在 EV 决策——显示底池权益（期望份额）
            equity_chips = round(equity_share * pot_total, 2)
            ev = equity_chips
            ev_judgment = "免跟注 · 底池权益"
            has_call = False

        return {
            "win_rate": round(win_rate_display * 100, 1),
            "equity": round(equity_share * 100, 1),
            "ci_95": mc_ci95(equity_share, mc_samples),
            "pot_odds_ratio": pot_odds_ratio,
            "required_equity": required_equity,
            "ev": ev,
            "ev_judgment": ev_judgment,
            "to_call": to_call,
            "has_call_decision": has_call,
        }

    def _calc_odds_ev_raw(self, game: GameState, player: Player, opponent_count: int) -> dict:
        """无需 MC 的赔率/财务裸数据（翻牌前跳过 MC 时使用）。"""
        to_call = max(0, game.current_bet - player.current_bet)
        pot_total = game.pot.total
        return {
            "win_rate": 0.0,
            "pot_odds_ratio": round((pot_total + to_call) / to_call, 2) if to_call > 0 else 0.0,
            "required_equity": round(to_call / (pot_total + to_call) * 100, 1) if to_call > 0 else 0.0,
            "ev": 0.0,
            "ev_judgment": "",
            "to_call": to_call,
            "has_call_decision": to_call > 0,
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
