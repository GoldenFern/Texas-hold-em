"""Pot 边池权威的单元测试 —— 分层、资格、死钱、退款。"""

from __future__ import annotations

import pytest

from src.engine.player import Player
from src.engine.pot import Pot
from src.utils.constants import PlayerStatus


def _player(name: str, total_bet: int, folded: bool = False, chips: int = 0) -> Player:
    """构造一个带指定投入的测试玩家。"""
    p = Player(name=name, chips=chips, seat=0)
    p.total_bet = total_bet
    if folded:
        p.status = PlayerStatus.FOLDED
    return p


class TestPotBasic:
    def test_empty_pot(self) -> None:
        pot = Pot()
        assert pot.total == 0
        assert pot.main_pot == 0
        assert pot.side_pots == []

    def test_add_bet_increases_total(self) -> None:
        pot = Pot()
        pot.add_bet(50)
        pot.add_bet(30)
        assert pot.total == 80

    def test_reset_clears_pot(self) -> None:
        pot = Pot()
        pot.add_bet(100)
        pot.reset()
        assert pot.total == 0
        assert pot.pots == []


class TestCollectBets:
    def test_no_all_in_single_main_pot(self) -> None:
        """无全下：全部进入主池，所有未弃牌者有资格。"""
        players = [_player("A", 100), _player("B", 100), _player("C", 100)]
        pot = Pot()
        refund = pot.collect_bets(players)

        assert refund == 0
        assert pot.main_pot == 300
        assert pot.side_pots == []
        assert pot.pots[0].eligible_players == {"A", "B", "C"}
        assert pot.total == 300

    def test_two_levels_side_pot(self) -> None:
        """B/C 下注 100，A 全下 50：主池 150（A/B/C），边池 100（B/C）。"""
        players = [_player("A", 50), _player("B", 100), _player("C", 100)]
        pot = Pot()
        pot.collect_bets(players)

        assert pot.main_pot == 150
        assert len(pot.side_pots) == 1
        assert pot.side_pots[0].amount == 100
        assert pot.pots[0].eligible_players == {"A", "B", "C"}
        assert pot.side_pots[0].eligible_players == {"B", "C"}
        assert pot.total == 250

    def test_three_levels(self) -> None:
        """30/60/100 三层全下。"""
        players = [_player("A", 30), _player("B", 60), _player("C", 100),
                   _player("D", 100)]
        pot = Pot()
        pot.collect_bets(players)

        assert pot.main_pot == 120  # 30 × 4
        assert pot.side_pots[0].amount == 90  # 30 × 3
        assert pot.side_pots[0].eligible_players == {"B", "C", "D"}
        assert pot.side_pots[1].amount == 80  # 40 × 2
        assert pot.side_pots[1].eligible_players == {"C", "D"}
        assert pot.total == 290  # 30+60+100+100

    def test_folded_dead_money_stays(self) -> None:
        """弃牌者的死钱留在对应层内，但无资格。"""
        players = [
            _player("A", 100, folded=True),
            _player("B", 100),
            _player("C", 100),
        ]
        pot = Pot()
        refund = pot.collect_bets(players)

        assert refund == 0
        assert pot.main_pot == 300
        assert pot.pots[0].eligible_players == {"B", "C"}

    def test_uncalled_excess_refunded(self) -> None:
        """最高下注未被匹配的部分退还，不计入底池。"""
        players = [_player("A", 50), _player("B", 200, chips=10)]
        pot = Pot()
        refund = pot.collect_bets(players)

        assert refund == 150
        assert players[1].chips == 160  # 10 + 150
        assert players[1].total_bet == 50
        assert pot.main_pot == 100
        assert pot.side_pots == []
        assert pot.total == 100

    def test_refund_matched_by_folded_dead_money(self) -> None:
        """弃牌者的投入也算匹配额：退款只退超出全场第二高投入的部分。

        C 弃牌前投入 400，B 全下 688：B 只退 688-400=288，
        400-level 层含 C 的死钱、仅 B 有资格（由 B 在摊牌时赢走）。
        """
        players = [
            _player("A", 28),
            _player("B", 688, chips=0),
            _player("C", 400, folded=True),
        ]
        pot = Pot()
        refund = pot.collect_bets(players)

        assert refund == 288
        assert players[1].total_bet == 400
        # 层1: 28×3=84 (A,B)；层2: (400-28)×2=744 (仅 B)
        assert pot.main_pot == 84
        assert pot.pots[0].eligible_players == {"A", "B"}
        assert pot.side_pots[0].amount == 744
        assert pot.side_pots[0].eligible_players == {"B"}
        # 守恒: 84 + 744 + 288(退款) == 28 + 688 + 400
        assert pot.total + refund == 28 + 688 + 400

    def test_out_player_ignored(self) -> None:
        """OUT 玩家（total_bet=0）不产生层也无资格。"""
        out = _player("Z", 0)
        out.status = PlayerStatus.OUT
        players = [out, _player("A", 100), _player("B", 100)]
        pot = Pot()
        pot.collect_bets(players)

        assert pot.main_pot == 200
        assert pot.pots[0].eligible_players == {"A", "B"}

    def test_conservation_invariant_violation_raises(self) -> None:
        """无人认领的死钱层必须触发 RuntimeError（防静默丢钱）。"""
        # 人为构造：弃牌者投入高于所有未弃牌者（引擎已禁止免费弃牌，
        # 此处直接构造损坏状态验证防御断言）
        players = [
            _player("A", 50),
            _player("B", 500, folded=True),
            _player("C", 500, folded=True),
        ]
        pot = Pot()
        with pytest.raises(RuntimeError):
            pot.collect_bets(players)

    def test_get_pot_for_player(self) -> None:
        players = [_player("A", 50), _player("B", 100), _player("C", 100)]
        pot = Pot()
        pot.collect_bets(players)

        assert pot.get_pot_for_player("A") == 150
        assert pot.get_pot_for_player("B") == 250
        assert pot.get_pot_for_player("Z") == 0

    def test_refund_uncalled_updates_total(self) -> None:
        pot = Pot()
        pot.add_bet(300)
        p = _player("A", 200, chips=0)
        pot.refund_uncalled(p, 80)
        assert p.chips == 80
        assert p.total_bet == 120
        assert pot.total == 220
