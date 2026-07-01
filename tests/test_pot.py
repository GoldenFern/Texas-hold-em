"""Pot / SidePot 底池管理测试。"""

import pytest

from src.engine.player import Player
from src.engine.pot import Pot, SidePot


def make_player(name: str, chips: int, seat: int) -> Player:
    return Player(name=name, chips=chips, seat=seat)


class TestPotBasic:
    """底池基本操作。"""

    def test_new_pot_is_empty(self) -> None:
        pot = Pot()
        assert pot.total == 0
        assert pot.main_pot == 0
        assert pot.side_pots == []

    def test_add_bet_increases_total(self) -> None:
        pot = Pot()
        p1 = make_player("Alice", 1000, 0)
        pot.add_bet(p1, 50)
        assert pot.total == 50

    def test_reset_clears_pot(self) -> None:
        pot = Pot()
        p1 = make_player("Alice", 1000, 0)
        pot.add_bet(p1, 100)
        pot.reset()
        assert pot.total == 0


class TestSidePotCalculation:
    """边池计算测试。"""

    def test_no_all_in_no_side_pots(self) -> None:
        """无人全下，无边池。"""
        pot = Pot()
        p1 = make_player("A", 1000, 0)
        p2 = make_player("B", 1000, 1)
        p3 = make_player("C", 1000, 2)

        p1.total_bet = 100
        p2.total_bet = 100
        p3.total_bet = 100

        pot.collect_bets([p1, p2, p3])

        # 仅主池
        assert pot.main_pot == 300
        assert len(pot.side_pots) == 0

    def test_one_all_in_creates_side_pot(self) -> None:
        """一人全下，筹码不足匹配。"""
        pot = Pot()
        p1 = make_player("A", 50, 0)
        p2 = make_player("B", 1000, 1)
        p3 = make_player("C", 1000, 2)

        # A 全下 50, B 和 C 各下注 100
        p1.total_bet = 50
        p2.total_bet = 100
        p3.total_bet = 100

        pot.collect_bets([p1, p2, p3])

        # 主池: 3×50 = 150 (A, B, C 均有资格)
        # 边池: 2×50 = 100 (仅 B, C 有资格)
        assert pot.main_pot == 150
        assert len(pot.side_pots) == 1
        assert pot.side_pots[0].amount == 100
        assert "A" not in pot.side_pots[0].eligible_players
        assert "B" in pot.side_pots[0].eligible_players
        assert "C" in pot.side_pots[0].eligible_players

    def test_two_all_in_different_levels(self) -> None:
        """两人全下，不同层级。"""
        pot = Pot()
        p1 = make_player("A", 30, 0)
        p2 = make_player("B", 60, 1)
        p3 = make_player("C", 1000, 2)

        p1.total_bet = 30
        p2.total_bet = 60
        p3.total_bet = 100

        pot.collect_bets([p1, p2, p3])

        # 第一层: 3×30 = 90 (所有人)
        assert pot.main_pot == 90
        # 第二层: (60-30)×2 = 60 (B, C)
        assert len(pot.side_pots) >= 1
        side_60 = pot.side_pots[0]
        assert side_60.amount == 60
        assert "A" not in side_60.eligible_players
        # 第三层: (100-60)×1 = 40 (仅 C)
        assert len(pot.side_pots) == 2
        side_100 = pot.side_pots[1]
        assert side_100.amount == 40
        assert "A" not in side_100.eligible_players
        assert "B" not in side_100.eligible_players
        assert "C" in side_100.eligible_players

    def test_folded_player_excluded(self) -> None:
        """弃牌玩家不计入边池资格。"""
        pot = Pot()
        p1 = make_player("A", 100, 0)
        p2 = make_player("B", 1000, 1)
        p3 = make_player("C", 1000, 2)

        p1.total_bet = 100
        p2.total_bet = 200
        p3.total_bet = 200
        p1.fold()  # A 弃牌

        pot.collect_bets([p1, p2, p3])

        # 主池: 3×100 = 300 (但 A 弃牌，无资格)
        assert pot.main_pot == 300
        # 边池: 2×100 = 200 (仅 B, C)
        assert len(pot.side_pots) == 1
        assert pot.side_pots[0].amount == 200

    def test_all_players_all_in(self) -> None:
        """所有人全下且下注额不同的极端情况。"""
        pot = Pot()
        p1 = make_player("A", 10, 0)
        p2 = make_player("B", 25, 1)
        p3 = make_player("C", 50, 2)

        p1.total_bet = 10
        p2.total_bet = 25
        p3.total_bet = 50

        pot.collect_bets([p1, p2, p3])

        total_pot = pot.main_pot + sum(sp.amount for sp in pot.side_pots)
        assert total_pot == 85  # 10+25+50
