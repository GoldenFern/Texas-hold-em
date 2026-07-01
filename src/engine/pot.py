"""底池管理 —— 主底池与边池（全下边池）的计算。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from src.engine.player import Player


@dataclass
class SidePot:
    """一个边池（或主池）。

    Attributes:
        amount: 该池的总筹码量。
        eligible_players: 有资格赢得该池的玩家名称集合。
        level: 该池对应的下注级别（用于追踪）。
    """

    amount: int = 0
    eligible_players: Set[str] = field(default_factory=set)
    level: int = 0


class Pot:
    """底池管理器。

    处理主池和边池的创建与分配。当有玩家全下且筹码量
    不足以匹配其他玩家的下注时，自动创建边池。
    """

    def __init__(self) -> None:
        self._main_pot: int = 0
        self._side_pots: List[SidePot] = []
        self._total: int = 0

    # ---- 属性 ----

    @property
    def total(self) -> int:
        """底池总额。"""
        return self._total

    @property
    def main_pot(self) -> int:
        return self._main_pot

    @property
    def side_pots(self) -> List[SidePot]:
        return self._side_pots

    @property
    def all_pots(self) -> List[SidePot]:
        """所有底池（主池 + 边池）。"""
        pots = [SidePot(amount=self._main_pot, eligible_players=set(), level=0)]
        pots.extend(self._side_pots)
        return pots

    # ---- 操作 ----

    def add_bet(self, player: Player, amount: int) -> None:
        """记录玩家的下注。

        实际的分池计算在 collect_bets 中完成，
        这里仅累积总下注用于显示。
        """
        self._total += amount

    def collect_bets(self, players: List[Player]) -> Dict[str, int]:
        """在摊牌时计算底池分配。

        按照全下玩家的下注额分层，创建边池。
        每个玩家贡献的筹码分配到相应的层级。

        弃牌玩家的筹码仍然保留在底池中，但他们没有资格赢得任何层级。

        Args:
            players: 所有参与本局的玩家列表。

        Returns:
            玩家名称 → 应得筹码的映射。
        """
        # 所有投注了筹码的玩家（包括已弃牌的）
        all_bettors = [p for p in players if p.total_bet > 0]
        # 未弃牌玩家（有资格赢得底池）
        active_players = [p for p in players if not p.is_folded]

        if not all_bettors:
            return {}

        # 按 total_bet 升序排列所有投注者
        sorted_by_bet = sorted(all_bettors, key=lambda p: p.total_bet)

        self._side_pots = []
        prev_level = 0
        processed: Set[str] = set()

        for player in sorted_by_bet:
            level = player.total_bet
            if level <= prev_level:
                continue

            contribution_per_player = level - prev_level
            eligible: Set[str] = set()

            pot_amount = 0
            for p in all_bettors:
                if p.total_bet > prev_level:
                    contrib = min(contribution_per_player, p.total_bet - prev_level)
                    pot_amount += contrib
                    # 只有未弃牌且尚未被"用完"的玩家才有资格
                    if not p.is_folded and p.name not in processed:
                        eligible.add(p.name)

            if prev_level == 0:
                self._main_pot = pot_amount
            else:
                self._side_pots.append(SidePot(
                    amount=pot_amount,
                    eligible_players=eligible,
                    level=level,
                ))

            prev_level = level
            for p in all_bettors:
                if p.total_bet <= level:
                    processed.add(p.name)

        self._total = sum(p.total_bet for p in players)

        return {}

    def get_pot_for_player(self, player_name: str) -> int:
        """计算指定玩家可争夺的底池总额。"""
        total = 0
        # 主池对所有未弃牌玩家开放
        total += self._main_pot
        for sp in self._side_pots:
            if player_name in sp.eligible_players:
                total += sp.amount
        return total

    def reset(self) -> None:
        """重置底池（新一局开始）。"""
        self._main_pot = 0
        self._side_pots = []
        self._total = 0
