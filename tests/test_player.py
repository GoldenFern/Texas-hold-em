"""Player 单元测试 —— 下注/跟注/全下/重购等基础操作。"""

import pytest

from src.engine.player import Player
from src.utils.constants import PlayerStatus


class TestPlayerBasics:
    """玩家基本属性和状态。"""

    def test_default_properties(self) -> None:
        p = Player(name="Hero", chips=1000, seat=0)
        assert p.name == "Hero"
        assert p.chips == 1000
        assert p.seat == 0
        assert p.is_human is False
        assert p.is_active is True
        assert p.is_folded is False
        assert p.is_all_in is False
        assert p.is_out is False
        assert p.can_act is True  # 有筹码且未弃牌
        assert p.current_bet == 0
        assert p.total_bet == 0

    def test_human_player(self) -> None:
        p = Player(name="Human", chips=500, seat=1, is_human=True)
        assert p.is_human is True
        assert p.can_act is True

    def test_cannot_act_when_no_chips(self) -> None:
        p = Player(name="Broke", chips=0, seat=0)
        assert p.can_act is False

    def test_cannot_act_when_folded(self) -> None:
        p = Player(name="Folded", chips=500, seat=0)
        p.fold()
        assert p.can_act is False
        assert p.is_folded is True

    def test_cannot_act_when_all_in(self) -> None:
        p = Player(name="AllIn", chips=0, seat=0)
        p.status = PlayerStatus.ALL_IN
        assert p.can_act is False
        assert p.is_all_in is True

    def test_is_out(self) -> None:
        p = Player(name="Out", chips=0, seat=0)
        p.status = PlayerStatus.OUT
        assert p.is_out is True
        assert p.can_act is False


class TestBet:
    """下注/加注测试。"""

    def test_normal_bet(self) -> None:
        p = Player(name="Hero", chips=1000, seat=0)
        p.current_bet = 10  # 本轮已下 10
        added = p.bet(30)  # 加到 30
        assert added == 20
        assert p.current_bet == 30
        assert p.chips == 980
        assert p.total_bet == 20
        assert p.status == PlayerStatus.ACTIVE

    def test_bet_all_in(self) -> None:
        """下注超过筹码量应全下。"""
        p = Player(name="Hero", chips=100, seat=0)
        added = p.bet(200)
        assert added == 100
        assert p.chips == 0
        assert p.current_bet == 100
        assert p.total_bet == 100
        assert p.is_all_in is True

    def test_bet_zero(self) -> None:
        p = Player(name="Hero", chips=1000, seat=0)
        p.current_bet = 20
        added = p.bet(20)
        assert added == 0
        assert p.chips == 1000
        assert p.current_bet == 20


class TestCall:
    """跟注测试。"""

    def test_normal_call(self) -> None:
        p = Player(name="Hero", chips=1000, seat=0)
        p.current_bet = 10
        added = p.call(30)  # 跟注到 30
        assert added == 20
        assert p.chips == 980
        assert p.current_bet == 30
        assert p.total_bet == 20

    def test_call_no_additional(self) -> None:
        """无需额外跟注。"""
        p = Player(name="Hero", chips=1000, seat=0)
        p.current_bet = 30
        added = p.call(30)
        assert added == 0
        assert p.chips == 1000

    def test_call_all_in_insufficient_chips(self) -> None:
        """部分筹码跟注触发全下。"""
        p = Player(name="Hero", chips=15, seat=0)
        p.current_bet = 10
        added = p.call(50)  # 需要跟 40，但只有 15
        assert added == 15
        assert p.chips == 0
        assert p.current_bet == 25
        assert p.total_bet == 15
        assert p.is_all_in is True

    def test_call_all_in_exact_chips(self) -> None:
        """恰好用光筹码。"""
        p = Player(name="Hero", chips=40, seat=0)
        added = p.call(40)
        assert added == 40
        assert p.chips == 0
        assert p.is_all_in is True


class TestPostBlind:
    """盲注支付测试。"""

    def test_normal_blind(self) -> None:
        p = Player(name="Hero", chips=1000, seat=0)
        actual = p.post_blind(10)
        assert actual == 10
        assert p.chips == 990
        assert p.current_bet == 10
        assert p.total_bet == 10

    def test_blind_all_in(self) -> None:
        p = Player(name="Hero", chips=5, seat=0)
        actual = p.post_blind(10)
        assert actual == 5
        assert p.chips == 0
        assert p.current_bet == 5
        assert p.total_bet == 5
        assert p.is_all_in is True

    def test_blind_exact_chips(self) -> None:
        p = Player(name="Hero", chips=5, seat=0)
        actual = p.post_blind(5)
        assert actual == 5
        assert p.chips == 0
        assert p.is_all_in is True


class TestWinPot:
    """赢得底池测试。"""

    def test_win_pot_increases_chips(self) -> None:
        p = Player(name="Hero", chips=500, seat=0)
        p.win_pot(200)
        assert p.chips == 700
        assert p.total_won == 200
        assert p.hands_won == 1

    def test_win_pot_accumulates(self) -> None:
        p = Player(name="Hero", chips=500, seat=0)
        p.win_pot(100)
        p.win_pot(150)
        assert p.chips == 750
        assert p.total_won == 250
        assert p.hands_won == 2


class TestRebuy:
    """重购测试。"""

    def test_rebuy_when_broke(self) -> None:
        p = Player(name="Hero", chips=0, seat=0)
        result = p.rebuy(500)
        assert result is True
        assert p.chips == 500
        assert p.rebuy_count == 1

    def test_rebuy_when_have_chips_fails(self) -> None:
        p = Player(name="Hero", chips=50, seat=0)
        result = p.rebuy(500)
        assert result is False
        assert p.chips == 50
        assert p.rebuy_count == 0

    def test_rebuy_default_amount(self) -> None:
        p = Player(name="Hero", chips=0, seat=0)
        p.rebuy()
        assert p.chips == 1000

    def test_rebuy_count_accumulates(self) -> None:
        p = Player(name="Hero", chips=0, seat=0)
        p.rebuy(100)
        p.chips = 0  # 再次输光
        p.rebuy(200)
        assert p.rebuy_count == 2
        assert p.chips == 200


class TestResetForNewHand:
    """重置手牌状态。"""

    def test_reset_clears_hand_state(self) -> None:
        p = Player(name="Hero", chips=500, seat=0)
        p.hole_cards = [None, None]  # type: ignore
        p.current_bet = 50
        p.total_bet = 50
        p.is_dealer = True
        p.is_small_blind = True
        p.is_big_blind = True
        p.status = PlayerStatus.ALL_IN

        p.reset_for_new_hand()

        assert p.hole_cards == []
        assert p.status == PlayerStatus.ACTIVE
        assert p.current_bet == 0
        assert p.total_bet == 0
        assert p.is_dealer is False
        assert p.is_small_blind is False
        assert p.is_big_blind is False

    def test_reset_preserves_chips_and_stats(self) -> None:
        p = Player(name="Hero", chips=750, seat=0)
        p.hands_played = 10
        p.hands_won = 3
        p.total_won = 500
        p.rebuy_count = 1

        p.reset_for_new_hand()

        assert p.chips == 750
        assert p.hands_played == 10
        assert p.hands_won == 3
        assert p.total_won == 500
        assert p.rebuy_count == 1
