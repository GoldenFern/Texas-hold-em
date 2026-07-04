"""底池赔率与期望值测试。"""

import pytest

from src.analysis.odds import OddsCalculator
from src.engine.card import Card
from src.engine.game import GameState
from src.engine.player import Player


def cards(s: str) -> list[Card]:
    return Card.from_str_multi(s)


def make_players(names: list[str], chips: int = 1000) -> list[Player]:
    return [Player(name=n, chips=chips, seat=i) for i, n in enumerate(names)]


class TestPotOdds:
    """底池赔率计算。"""

    def test_standard_call(self) -> None:
        """跟注 10 进 50 底池 -> to_call=10, required_equity=10/60=0.1667。"""
        calc = OddsCalculator()
        players = make_players(["A", "B"])
        game = GameState(players)
        # 不用 start_new_hand，手动构建状态
        player = players[0]
        players[1].total_bet = 50  # 对手已下注 50
        game.pot.add_bet(players[1], 50)
        game.current_bet = 10
        player.current_bet = 0

        result = calc.pot_odds(game, player)
        assert result["to_call"] == 10
        assert abs(result["required_equity"] - 10 / 60) < 0.01

    def test_no_call_needed(self) -> None:
        """无需跟注时返回 0。"""
        calc = OddsCalculator()
        players = make_players(["A", "B"])
        game = GameState(players)
        player = players[0]
        player.current_bet = 10
        game.current_bet = 10

        result = calc.pot_odds(game, player)
        assert result["to_call"] == 0
        assert result["required_equity"] == 0.0

    def test_half_pot_call(self) -> None:
        """跟注 = 底池的一半 -> 所需胜率合理。"""
        calc = OddsCalculator()
        players = make_players(["A", "B"])
        game = GameState(players)
        players[1].total_bet = 100
        game.pot.add_bet(players[1], 100)
        game.current_bet = 50
        player = players[0]
        player.current_bet = 0

        result = calc.pot_odds(game, player)
        assert abs(result["required_equity"] - 1 / 3) < 0.02

    def test_all_in_call(self) -> None:
        """全下跟注的赔率计算。"""
        calc = OddsCalculator()
        players = make_players(["A", "B"])
        game = GameState(players)
        players[1].total_bet = 500
        game.pot.add_bet(players[1], 500)
        game.current_bet = 500
        player = players[0]
        player.current_bet = 0

        result = calc.pot_odds(game, player)
        assert result["to_call"] == 500
        assert abs(result["required_equity"] - 0.5) < 0.02


class TestImpliedOdds:
    """隐含赔率计算。"""

    def test_with_future_bets(self) -> None:
        calc = OddsCalculator()
        players = make_players(["A", "B"])
        game = GameState(players)
        players[1].total_bet = 50
        game.pot.add_bet(players[1], 50)
        game.current_bet = 10
        player = players[0]
        player.current_bet = 0

        result = calc.implied_odds(game, player, estimated_future_bets=30)
        assert result["to_call"] == 10
        assert result["pot_now"] == 50
        assert result["estimated_future"] == 30
        assert abs(result["implied_odds_ratio"] - 9.0) < 0.1
        assert abs(result["required_equity"] - 10 / 90) < 0.02

    def test_no_future_bets(self) -> None:
        calc = OddsCalculator()
        players = make_players(["A", "B"])
        game = GameState(players)
        players[1].total_bet = 50
        game.pot.add_bet(players[1], 50)
        game.current_bet = 10
        player = players[0]
        player.current_bet = 0

        result = calc.implied_odds(game, player)
        assert abs(result["implied_odds_ratio"] - 6.0) < 0.1

    def test_no_call_needed_zero(self) -> None:
        calc = OddsCalculator()
        players = make_players(["A", "B"])
        game = GameState(players)
        player = players[0]
        player.current_bet = 10
        game.current_bet = 10

        result = calc.implied_odds(game, player)
        assert result["implied_odds_ratio"] == 0
        assert result["required_equity"] == 0.0


class TestExpectedValue:
    """期望值计算。"""

    def test_check_is_free(self) -> None:
        calc = OddsCalculator()
        players = make_players(["A", "B"])
        game = GameState(players)
        player = players[0]
        player.current_bet = 10
        game.current_bet = 10

        result = calc.expected_value(game, player, opponent_count=1)
        assert result["action"] == "check/free"

    def test_call_ev_structure(self) -> None:
        calc = OddsCalculator()
        players = make_players(["A", "B"])
        game = GameState(players)
        players[1].total_bet = 50
        game.pot.add_bet(players[1], 50)
        game.current_bet = 20
        player = players[0]
        player.current_bet = 0
        player.hole_cards = cards("Ah As")

        result = calc.expected_value(game, player, opponent_count=1)
        assert result["action"] == "call"
        assert "estimated_equity" in result
        assert "ev_call" in result
        assert "pot_total" in result
        assert "to_call" in result
        assert result["to_call"] == 20
        assert result["pot_total"] == 50

    def test_postflop_ev_uses_hand_rank(self) -> None:
        calc = OddsCalculator()
        players = make_players(["A", "B"])
        game = GameState(players)
        game.community_cards = cards("Ah Kh Qh Jh Th")
        players[0].hole_cards = cards("As Kd")
        players[1].total_bet = 100
        game.pot.add_bet(players[1], 100)
        game.current_bet = 100
        player = players[0]
        player.current_bet = 0

        result = calc.expected_value(game, player, opponent_count=1)
        assert isinstance(result["estimated_equity"], float)

    def test_preflop_ev_uses_preflop_strength(self) -> None:
        calc = OddsCalculator()
        players = make_players(["A", "B"])
        game = GameState(players)
        players[1].total_bet = 20
        game.pot.add_bet(players[1], 20)
        game.current_bet = 20
        player = players[0]
        player.hole_cards = cards("Ah As")
        player.current_bet = 0

        result = calc.expected_value(game, player, opponent_count=2)
        assert result["action"] == "call"
        assert 0.0 <= result["estimated_equity"] <= 1.0
