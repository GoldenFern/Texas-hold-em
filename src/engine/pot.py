"""底池管理 —— 主底池与边池（全下边池）计算的唯一权威。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Set

from src.engine.player import Player


@dataclass
class SidePot:
    """一个底池层（主池或边池）。

    Attributes:
        amount: 该池的总筹码量。
        eligible_players: 有资格赢得该池的玩家名称集合。
        level: 该池对应的下注级别（用于追踪）。
    """

    amount: int = 0
    eligible_players: Set[str] = field(default_factory=set)
    level: int = 0


class Pot:
    """底池管理器 —— 边池计算的唯一权威。

    下注阶段用 `add_bet` 累积显示总额；摊牌时调用 `collect_bets`
    完成退款与分层，之后 `pots` 即为可直接分配的底池列表。
    """

    def __init__(self) -> None:
        self._pots: List[SidePot] = []
        self._total: int = 0

    # ---- 属性 ----

    @property
    def total(self) -> int:
        """底池总额（下注中为累积值，collect_bets 后为分层总和）。"""
        return self._total

    @property
    def main_pot(self) -> int:
        """主池金额（第一层）。"""
        return self._pots[0].amount if self._pots else 0

    @property
    def side_pots(self) -> List[SidePot]:
        """边池列表（主池之外的各层）。"""
        return self._pots[1:]

    @property
    def pots(self) -> List[SidePot]:
        """全部底池层（索引 0 为主池），仅在 collect_bets 后有效。"""
        return list(self._pots)

    # ---- 操作 ----

    def add_bet(self, amount: int) -> None:
        """累积下注总额（用于牌局进行中的显示）。

        分池计算在摊牌时由 collect_bets 统一完成。

        Args:
            amount: 本次新增投入的筹码量。
        """
        self._total += amount

    def collect_bets(self, players: List[Player]) -> int:
        """摊牌时计算底池分层（唯一权威）。

        规则：
        1. 未被任何其他下注者（含弃牌者的死钱）匹配的最高下注溢出部分，
           退还给该玩家（不计入任何底池）。
        2. 按未弃牌玩家的下注档位分层；弃牌玩家的死钱按档位填入各层，
           但无资格赢取。仅一名 eligible 玩家的层在分配时自动归其所有
           （含该层死钱），这是赢取而非退款。

        Args:
            players: 所有参与本局的玩家列表。退款会直接修改玩家的
                chips 与 total_bet。

        Returns:
            退还的未匹配筹码量（0 表示无退款）。
        """
        all_bettors = [p for p in players if p.total_bet > 0]
        self._pots = []

        if not all_bettors:
            self._total = 0
            return 0

        # 1. 退还未被匹配的最高下注溢出
        refund = 0
        top = max(all_bettors, key=lambda p: p.total_bet)
        second_level = max(
            (p.total_bet for p in all_bettors if p is not top),
            default=0,
        )
        if top.total_bet > second_level:
            refund = top.total_bet - second_level
            top.chips += refund
            top.total_bet -= refund

        # 2. 按未弃牌玩家的下注档位分层
        levels = sorted({
            p.total_bet for p in players
            if not p.is_folded and p.total_bet > 0
        })

        prev_level = 0
        for level in levels:
            pot_amount = sum(
                min(level, p.total_bet) - prev_level
                for p in all_bettors
                if p.total_bet > prev_level
            )
            eligible = {
                p.name for p in players
                if not p.is_folded and p.total_bet >= level
            }
            if pot_amount > 0:
                if not eligible:
                    raise RuntimeError(
                        f"底池层 level={level} 无人有资格认领 "
                        f"(amount={pot_amount})，筹码账目已损坏"
                    )
                self._pots.append(SidePot(
                    amount=pot_amount,
                    eligible_players=eligible,
                    level=level,
                ))
            prev_level = level

        # 守恒校验：分层总额 + 退款 必须等于全部投入
        total_committed = sum(p.total_bet for p in players)
        layered = sum(p_.amount for p_ in self._pots)
        if layered != total_committed:
            raise RuntimeError(
                f"边池分层不守恒: 投入 {total_committed} != 分层 {layered}"
            )

        self._total = layered
        return refund

    def refund_uncalled(self, player: Player, amount: int) -> None:
        """退还未被跟注的溢出筹码并同步显示总额（fold-out 路径使用）。

        Args:
            player: 收到退款的玩家。
            amount: 退款金额。
        """
        player.chips += amount
        player.total_bet -= amount
        self._total -= amount

    def get_pot_for_player(self, player_name: str) -> int:
        """计算指定玩家可争夺的底池总额（collect_bets 后有效）。"""
        return sum(
            p_.amount for p_ in self._pots
            if player_name in p_.eligible_players
        )

    def reset(self) -> None:
        """重置底池（新一局开始）。"""
        self._pots = []
        self._total = 0
