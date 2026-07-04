"""玩家模型 —— 人类玩家与 AI 玩家的基类。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from src.engine.card import Card, Cards
from src.utils.constants import PlayerStatus


@dataclass
class Player:
    """德州扑克玩家。

    Attributes:
        name: 玩家名称。
        chips: 当前筹码量。
        seat: 座位号（0–8）。
        is_human: 是否为人类玩家。
        hole_cards: 底牌（2 张）。
        status: 当前状态。
        current_bet: 当前轮已下注总额。
        total_bet: 本局累计下注。
        is_dealer: 是否为庄家（按钮位）。
    """

    name: str
    chips: int
    seat: int
    is_human: bool = False

    # 手牌状态
    hole_cards: Cards = field(default_factory=list)
    status: PlayerStatus = PlayerStatus.ACTIVE
    current_bet: int = 0
    total_bet: int = 0

    # 位置标记
    is_dealer: bool = False
    is_small_blind: bool = False
    is_big_blind: bool = False

    # 统计
    hands_played: int = 0
    hands_won: int = 0
    total_won: int = 0

    # 重购
    rebuy_count: int = 0

    def reset_for_new_hand(self) -> None:
        """新一局开始，重置手牌相关状态。"""
        self.hole_cards = []
        self.status = PlayerStatus.ACTIVE
        self.current_bet = 0
        self.total_bet = 0
        self.is_dealer = False
        self.is_small_blind = False
        self.is_big_blind = False

    # ---- 属性查询 ----

    @property
    def is_active(self) -> bool:
        """是否仍在牌局中。"""
        return self.status == PlayerStatus.ACTIVE

    @property
    def is_folded(self) -> bool:
        return self.status == PlayerStatus.FOLDED

    @property
    def is_all_in(self) -> bool:
        return self.status == PlayerStatus.ALL_IN

    @property
    def is_out(self) -> bool:
        return self.status == PlayerStatus.OUT

    @property
    def can_act(self) -> bool:
        """是否可以行动（未弃牌且未全下且有筹码）。"""
        return self.status == PlayerStatus.ACTIVE and self.chips > 0

    # ---- 动作 ----

    def bet(self, amount: int) -> int:
        """下注/加注。

        Args:
            amount: 本轮新增的下注总额（含之前的 current_bet）。

        Returns:
            实际新增投入的筹码量。
        """
        added = amount - self.current_bet
        if added > self.chips:
            added = self.chips
            amount = self.current_bet + added
            self.status = PlayerStatus.ALL_IN
        self.chips -= added
        self.current_bet = amount
        self.total_bet += added
        return added

    def call(self, amount: int) -> int:
        """跟注。

        Args:
            amount: 需要跟到的总额。

        Returns:
            实际新增投入的筹码量。
        """
        added = amount - self.current_bet
        if added >= self.chips:
            # 全下
            added = self.chips
            self.current_bet += added
            self.total_bet += added
            self.chips = 0
            self.status = PlayerStatus.ALL_IN
        else:
            self.chips -= added
            self.current_bet = amount
            self.total_bet += added
        return added

    def fold(self) -> None:
        """弃牌。"""
        self.status = PlayerStatus.FOLDED

    def check(self) -> None:
        """过牌（仅在无需跟注时合法）。"""
        pass  # 不改变任何状态

    def post_blind(self, amount: int) -> int:
        """支付盲注。

        Returns:
            实际支付的筹码量（若筹码不足则为全下）。
        """
        if amount >= self.chips:
            actual = self.chips
            self.chips = 0
            self.current_bet = actual
            self.total_bet += actual
            self.status = PlayerStatus.ALL_IN
            return actual
        self.chips -= amount
        self.current_bet = amount
        self.total_bet += amount
        return amount

    def win_pot(self, amount: int) -> None:
        """赢得底池。"""
        self.chips += amount
        self.total_won += amount
        self.hands_won += 1

    def rebuy(self, amount: int = 1000) -> bool:
        """重购筹码（本金输光时借款重新入场）。

        Returns:
            True 如果执行了重购。
        """
        if self.chips > 0:
            return False
        self.chips = amount
        self.rebuy_count += 1
        return True

    # ---- 比较 ----

    def __hash__(self) -> int:
        return hash((self.name, self.seat))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Player):
            return NotImplemented
        return self.name == other.name and self.seat == other.seat
