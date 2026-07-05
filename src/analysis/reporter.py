"""牌局记录与统计报告器。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from src.engine.game import HandHistory
from src.engine.player import Player


@dataclass
class PlayerStats:
    """玩家统计数据。"""

    name: str
    hands_played: int = 0
    hands_won: int = 0
    vpip_count: int = 0  # 自愿入池次数
    pfr_count: int = 0   # 翻牌前加注次数
    fold_count: int = 0
    call_count: int = 0
    raise_count: int = 0
    total_won: int = 0
    total_spent: int = 0  # 实际投入底池的总筹码（含盲注、跟注等）
    showdown_count: int = 0

    @property
    def vpip(self) -> float:
        """自愿入池率。"""
        if self.hands_played == 0:
            return 0.0
        return round(self.vpip_count / self.hands_played, 4)

    @property
    def pfr(self) -> float:
        """翻牌前加注率。"""
        if self.hands_played == 0:
            return 0.0
        return round(self.pfr_count / self.hands_played, 4)

    @property
    def aggression_factor(self) -> float:
        """侵略因子 = (加注次数 + 下注次数) / 跟注次数。"""
        if self.call_count == 0:
            return float(self.raise_count) if self.raise_count > 0 else 0.0
        return round(self.raise_count / max(1, self.call_count), 2)

    @property
    def win_rate(self) -> float:
        """胜率。"""
        if self.hands_played == 0:
            return 0.0
        return round(self.hands_won / self.hands_played, 4)

    @property
    def profit(self) -> int:
        """净利润 = 赢得总额 - 实际投入总额。"""
        return self.total_won - self.total_spent


class HandReporter:
    """牌局报告器。

    追踪牌局历史并生成统计数据。
    """

    def __init__(self) -> None:
        self.history: List[HandHistory] = []
        self.player_stats: Dict[str, PlayerStats] = {}
        self._prev_rebuy: Dict[str, int] = {}  # 上局末各玩家的 rebuy_count

    def record_hand(self, history: HandHistory) -> None:
        """记录一手牌。"""
        self.history.append(history)

        for name in history.players:
            if name not in self.player_stats:
                self.player_stats[name] = PlayerStats(name=name)
            self.player_stats[name].hands_played += 1

        # 统计优胜者
        for name, amount in history.winners.items():
            if name in self.player_stats:
                self.player_stats[name].hands_won += 1
                self.player_stats[name].total_won += amount

        # 统计动作（所有阶段）
        from src.utils.constants import ActionType, GamePhase
        vpip_players: set = set()
        pfr_players: set = set()
        for action in history.actions:
            stats = self.player_stats.get(action.player_name)
            if stats is None:
                continue
            if action.action_type == ActionType.FOLD:
                stats.fold_count += 1
            elif action.action_type == ActionType.CALL:
                stats.call_count += 1
            elif action.action_type in (ActionType.BET, ActionType.RAISE):
                stats.raise_count += 1

            # VPIP & PFR：翻牌前阶段，每人每局只计一次
            if action.phase == GamePhase.PRE_FLOP:
                if action.action_type in (ActionType.CALL, ActionType.BET, ActionType.RAISE):
                    vpip_players.add(action.player_name)
                if action.action_type in (ActionType.BET, ActionType.RAISE):
                    pfr_players.add(action.player_name)

        for name in vpip_players:
            if name in self.player_stats:
                self.player_stats[name].vpip_count += 1
        for name in pfr_players:
            if name in self.player_stats:
                self.player_stats[name].pfr_count += 1

        # 计算每位玩家本手实际投入的筹码（含盲注、跟注、退款等）
        # 公式:
        #   spent = 初始筹码 - 终局筹码 + 赢得筹码 - 重购筹码
        #
        # 重购发生在 start_new_hand() 中，快照 0 之前。
        # 快照 0 中 rebuy_count 已包含本局重购。
        # 与上局末的 rebuy_count 之差即为本局重购次数。
        snapshots = getattr(history, 'step_snapshots', None)
        if snapshots and len(snapshots) >= 2:
            first = snapshots[0]
            last = snapshots[-1]
            first_players = {p['name']: p for p in first.get('players', [])}
            last_chips = {p['name']: p['chips'] for p in last.get('players', [])}
            for name in history.players:
                stats = self.player_stats.get(name)
                if stats is None:
                    continue
                fp = first_players.get(name, {})
                chips_before = fp.get('chips', 0)
                chips_after = last_chips.get(name, 0)
                won = history.winners.get(name, 0)
                spent = chips_before - chips_after + won

                # 扣除本局重购筹码（凭空注入的筹码不算实际投入）
                curr_rebuy = fp.get('rebuy_count', 0)
                prev_rebuy = self._prev_rebuy.get(name, 0)
                rebuy_extra = (curr_rebuy - prev_rebuy) * 1000
                spent -= rebuy_extra

                if spent > 0:
                    stats.total_spent += spent
                # 记录本局末 rebuy 状态，供下一局对比
                last_player = {p['name']: p for p in last.get('players', [])}
                self._prev_rebuy[name] = last_player.get(name, {}).get('rebuy_count', curr_rebuy)

    def get_stats(self, player_name: str) -> Optional[PlayerStats]:
        """获取指定玩家的统计数据。"""
        return self.player_stats.get(player_name)

    def get_all_stats(self) -> List[PlayerStats]:
        """获取所有玩家的统计数据。"""
        return list(self.player_stats.values())

    def get_summary(self) -> Dict:
        """生成牌局摘要。"""
        total_hands = len(self.history)
        total_pot = sum(h.pot_total for h in self.history)

        return {
            "total_hands": total_hands,
            "total_pot_distributed": total_pot,
            "player_stats": [
                {
                    "name": s.name,
                    "hands_played": s.hands_played,
                    "hands_won": s.hands_won,
                    "vpip": s.vpip,
                    "pfr": s.pfr,
                    "aggression_factor": s.aggression_factor,
                    "win_rate": s.win_rate,
                    "profit": s.profit,
                }
                for s in self.player_stats.values()
            ],
        }

    def last_hand_summary(self) -> Optional[Dict]:
        """最近一手牌的摘要。"""
        if not self.history:
            return None
        h = self.history[-1]
        return {
            "hand_id": h.hand_id,
            "community_cards": [str(c) for c in h.community_cards],
            "pot_total": h.pot_total,
            "winners": dict(h.winners),
            "actions": [repr(a) for a in h.actions[-10:]],  # 最近 10 个动作
            "num_actions": len(h.actions),
        }

    def clear(self) -> None:
        """清除所有历史记录。"""
        self.history.clear()
        self.player_stats.clear()
        self._prev_rebuy.clear()
