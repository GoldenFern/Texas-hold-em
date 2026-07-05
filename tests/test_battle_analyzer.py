"""BattleAnalyzer 战局分析引擎测试。"""

from __future__ import annotations

import time

import pytest

from src.analysis.battle_analyzer import BattleAnalyzer
from src.engine.card import Card
from src.engine.game import GameState
from src.engine.player import Player


def cards(s: str) -> list[Card]:
    return Card.from_str_multi(s)


def make_players(names: list[str], chips: int = 1000) -> list[Player]:
    return [Player(name=n, chips=chips, seat=i) for i, n in enumerate(names)]


def make_game(players: list[Player]) -> GameState:
    game = GameState(players)
    game.community_cards = []
    return game


class TestBattleAnalyzerHandTypeProbs:
    """牌型概率测试。"""

    def test_preflop_returns_all_10_hand_types(self) -> None:
        analyzer = BattleAnalyzer(preflop_sims=227, postflop_sims=45, seed=42)
        hole = cards("Ah Kh")
        players = make_players(["Hero", "Bot1", "Bot2"])
        players[0].is_human = True
        game = make_game(players)

        result = analyzer.analyze(
            hole_cards=hole, community_cards=[],
            active_opponent_count=2, game=game, player=players[0],
        )

        probs = result["hand_type_probs"]
        assert len(probs) == 10

    def test_preflop_prob_sum_around_100(self) -> None:
        analyzer = BattleAnalyzer(preflop_sims=227, postflop_sims=45, seed=42)
        hole = cards("Ah Kh")
        players = make_players(["Hero", "Bot1", "Bot2"])
        players[0].is_human = True
        game = make_game(players)

        result = analyzer.analyze(
            hole_cards=hole, community_cards=[],
            active_opponent_count=2, game=game, player=players[0],
        )

        total = sum(result["hand_type_probs"].values())
        assert abs(total - 100.0) < 2.0, f"sum={total}"

    def test_river_exact_result(self) -> None:
        """"Ah Kh" + "Qh Jh Th" = 皇家同花顺（A-K-Q-J-T all hearts）。"""
        analyzer = BattleAnalyzer(preflop_sims=227, postflop_sims=45, seed=42)
        hole = cards("Ah Kh")
        community = cards("Qh Jh Th 2d 3c")
        players = make_players(["Hero", "Bot1", "Bot2"])
        players[0].is_human = True
        game = make_game(players)
        game.community_cards = community

        result = analyzer.analyze(
            hole_cards=hole, community_cards=community,
            active_opponent_count=2, game=game, player=players[0],
        )

        probs = result["hand_type_probs"]
        # A-K-Q-J-T all hearts = Royal Flush
        assert probs["\u7687\u5bb6\u540c\u82b1\u987a"] == 100.0
        assert result["sim_count"] == 0

    def test_aa_preflop_has_one_pair_or_better(self) -> None:
        analyzer = BattleAnalyzer(preflop_sims=227, postflop_sims=45, seed=42)
        hole = cards("Ah As")
        players = make_players(["Hero", "Bot1", "Bot2"])
        players[0].is_human = True
        game = make_game(players)

        result = analyzer.analyze(
            hole_cards=hole, community_cards=[],
            active_opponent_count=2, game=game, player=players[0],
        )

        probs = result["hand_type_probs"]
        assert probs["\u4e00\u5bf9"] > 0

    def test_flop_made_hand(self) -> None:
        """翻牌 Ac Ks + 公共牌 Kh 8d 2c = 顶对顶踢脚。"""
        analyzer = BattleAnalyzer(preflop_sims=227, postflop_sims=45, seed=42)
        hole = cards("Ac Ks")
        community = cards("Kh 8d 2c")
        players = make_players(["Hero", "Bot1", "Bot2"])
        players[0].is_human = True
        game = make_game(players)
        game.community_cards = community

        result = analyzer.analyze(
            hole_cards=hole, community_cards=community,
            active_opponent_count=2, game=game, player=players[0],
        )

        probs = result["hand_type_probs"]
        # 翻牌有一对 Kings，但 MC 模拟可能升级为两对/三条等
        assert probs["\u4e00\u5bf9"] > 0

    def test_turn_with_draws(self) -> None:
        analyzer = BattleAnalyzer(preflop_sims=227, postflop_sims=45, seed=42)
        hole = cards("Ah Kh")
        community = cards("Qh Jh 2d 7c")
        players = make_players(["Hero", "Bot1", "Bot2"])
        players[0].is_human = True
        game = make_game(players)
        game.community_cards = community

        result = analyzer.analyze(
            hole_cards=hole, community_cards=community,
            active_opponent_count=2, game=game, player=players[0],
        )

        probs = result["hand_type_probs"]
        assert probs["\u9ad8\u724c"] < 90.0


class TestBattleAnalyzerRankingDistribution:
    """排名分布律测试。"""

    def test_ranking_has_correct_entries(self) -> None:
        analyzer = BattleAnalyzer(preflop_sims=227, postflop_sims=45, seed=42)
        hole = cards("Ah Kh")
        players = make_players(["Hero", "Bot1", "Bot2", "Bot3"])
        players[0].is_human = True
        game = make_game(players)

        result = analyzer.analyze(
            hole_cards=hole, community_cards=[],
            active_opponent_count=3, game=game, player=players[0],
        )

        dist = result["ranking_distribution"]
        assert len(dist) == 4
        assert dist[0]["rank"] == 1
        assert dist[3]["rank"] == 4

    def test_ranking_prob_sum_around_100(self) -> None:
        analyzer = BattleAnalyzer(preflop_sims=227, postflop_sims=45, seed=42)
        hole = cards("Ah Kh")
        players = make_players(["Hero", "Bot1", "Bot2"])
        players[0].is_human = True
        game = make_game(players)

        result = analyzer.analyze(
            hole_cards=hole, community_cards=[],
            active_opponent_count=2, game=game, player=players[0],
        )

        dist = result["ranking_distribution"]
        total = sum(d["prob"] for d in dist)
        assert abs(total - 100.0) < 2.0, f"sum={total}"

    def test_aa_has_higher_win_rate(self) -> None:
        analyzer = BattleAnalyzer(preflop_sims=227, postflop_sims=45, seed=42)
        hole_aa = cards("Ah As")
        hole_27 = cards("2h 7d")
        players = make_players(["Hero", "Bot1", "Bot2"])
        players[0].is_human = True
        game = make_game(players)

        result_aa = analyzer.analyze(
            hole_cards=hole_aa, community_cards=[],
            active_opponent_count=2, game=game, player=players[0],
        )
        result_27 = analyzer.analyze(
            hole_cards=hole_27, community_cards=[],
            active_opponent_count=2, game=game, player=players[0],
        )

        win_aa = result_aa["ranking_distribution"][0]["prob"]
        win_27 = result_27["ranking_distribution"][0]["prob"]
        assert win_aa > win_27

    def test_single_opponent_two_ranks(self) -> None:
        analyzer = BattleAnalyzer(preflop_sims=227, postflop_sims=45, seed=42)
        hole = cards("Ah Kh")
        players = make_players(["Hero", "Bot1"])
        players[0].is_human = True
        game = make_game(players)

        result = analyzer.analyze(
            hole_cards=hole, community_cards=[],
            active_opponent_count=1, game=game, player=players[0],
        )

        dist = result["ranking_distribution"]
        assert len(dist) == 2


class TestBattleAnalyzerOddsEv:
    """赔率与 EV 测试。"""

    def test_odds_ev_structure(self) -> None:
        analyzer = BattleAnalyzer(preflop_sims=227, postflop_sims=45, seed=42)
        hole = cards("Ah Kh")
        players = make_players(["Hero", "Bot1", "Bot2"])
        players[0].is_human = True
        players[0].hole_cards = hole
        players[1].total_bet = 20
        game = make_game(players)
        game.pot.add_bet(players[1], 20)
        game.current_bet = 20

        result = analyzer.analyze(
            hole_cards=hole, community_cards=[],
            active_opponent_count=2, game=game, player=players[0],
        )

        odds_ev = result["odds_ev"]
        for key in ("win_rate", "pot_odds_ratio", "required_equity",
                     "implied_odds_ratio", "ev", "ev_judgment", "to_call",
                     "has_call_decision"):
            assert key in odds_ev, f"missing {key}"

    def test_no_call_shows_equity(self) -> None:
        """to_call=0 时应显示底池权益而非 EV。"""
        analyzer = BattleAnalyzer(preflop_sims=227, postflop_sims=45, seed=42)
        hole = cards("Ah Kh")
        players = make_players(["Hero", "Bot1", "Bot2"])
        players[0].is_human = True
        players[0].hole_cards = hole
        game = make_game(players)

        result = analyzer.analyze(
            hole_cards=hole, community_cards=[],
            active_opponent_count=2, game=game, player=players[0],
        )

        assert result["odds_ev"]["to_call"] == 0
        assert result["odds_ev"]["has_call_decision"] is False
        assert "底池权益" in result["odds_ev"]["ev_judgment"]

    def test_aa_has_positive_ev(self) -> None:
        analyzer = BattleAnalyzer(preflop_sims=227, postflop_sims=45, seed=42)
        hole = cards("Ah As")
        players = make_players(["Hero", "Bot1"])
        players[0].is_human = True
        players[0].hole_cards = hole
        players[0].current_bet = 10
        players[1].total_bet = 50
        game = make_game(players)
        game.pot.add_bet(players[1], 50)
        game.pot.add_bet(players[0], 10)
        game.current_bet = 50

        result = analyzer.analyze(
            hole_cards=hole, community_cards=[],
            active_opponent_count=1, game=game, player=players[0],
        )

        assert result["odds_ev"]["to_call"] == 40
        assert result["odds_ev"]["has_call_decision"] is True
        assert result["odds_ev"]["ev"] > 0


class TestBattleAnalyzerPotFinancials:
    """底池财务测试。"""

    def test_pot_financials_structure(self) -> None:
        analyzer = BattleAnalyzer(preflop_sims=227, postflop_sims=45, seed=42)
        hole = cards("Ah Kh")
        players = make_players(["Hero", "Bot1", "Bot2"])
        players[0].is_human = True
        players[0].hole_cards = hole
        players[0].current_bet = 10
        players[0].total_bet = 10  # 同步 total_bet
        players[1].total_bet = 30
        game = make_game(players)
        game.pot.add_bet(players[0], 10)
        game.pot.add_bet(players[1], 30)
        game.current_bet = 30

        result = analyzer.analyze(
            hole_cards=hole, community_cards=[],
            active_opponent_count=2, game=game, player=players[0],
        )

        fin = result["pot_financials"]
        assert fin["pot_total"] == 40
        assert fin["sunk_cost"] == 10
        assert fin["to_call"] == 20

    def test_dead_money_from_folded_player(self) -> None:
        analyzer = BattleAnalyzer(preflop_sims=227, postflop_sims=45, seed=42)
        hole = cards("Ah Kh")
        players = make_players(["Hero", "Bot1", "Bot2"])
        players[0].is_human = True
        players[0].hole_cards = hole
        players[2].fold()
        players[2].total_bet = 15
        game = make_game(players)
        game.pot.add_bet(players[2], 15)

        result = analyzer.analyze(
            hole_cards=hole, community_cards=[],
            active_opponent_count=1, game=game, player=players[0],
        )

        assert result["pot_financials"]["dead_money"] == 15


class TestBattleAnalyzerPerformance:
    """性能测试。"""

    def test_preflop_performance(self) -> None:
        analyzer = BattleAnalyzer(preflop_sims=227, postflop_sims=45, seed=42)
        hole = cards("Ah Kh")
        players = make_players(["Hero", "Bot1", "Bot2", "Bot3", "Bot4", "Bot5"])
        players[0].is_human = True
        game = make_game(players)

        t0 = time.perf_counter()
        result = analyzer.analyze(
            hole_cards=hole, community_cards=[],
            active_opponent_count=5, game=game, player=players[0],
        )
        elapsed = (time.perf_counter() - t0) * 1000

        assert elapsed < 300
        assert result["sim_count"] == 227

    def test_flop_performance(self) -> None:
        analyzer = BattleAnalyzer(preflop_sims=227, postflop_sims=45, seed=42)
        hole = cards("Ac Ks")
        community = cards("Kh 8d 2c")
        players = make_players(["Hero", "Bot1", "Bot2", "Bot3", "Bot4", "Bot5"])
        players[0].is_human = True
        game = make_game(players)
        game.community_cards = community

        t0 = time.perf_counter()
        result = analyzer.analyze(
            hole_cards=hole, community_cards=community,
            active_opponent_count=5, game=game, player=players[0],
        )
        elapsed = (time.perf_counter() - t0) * 1000

        assert elapsed < 100
        assert result["sim_count"] == 45

    def test_river_performance(self) -> None:
        """河牌评估（含少量 MC 确定排名）耗时应在合理范围。"""
        analyzer = BattleAnalyzer(preflop_sims=227, postflop_sims=45, seed=42)
        hole = cards("Ah Kh")
        community = cards("Qh Jh Th 2d 3c")
        players = make_players(["Hero", "Bot1", "Bot2"])
        players[0].is_human = True
        game = make_game(players)
        game.community_cards = community

        t0 = time.perf_counter()
        result = analyzer.analyze(
            hole_cards=hole, community_cards=community,
            active_opponent_count=2, game=game, player=players[0],
        )
        elapsed = (time.perf_counter() - t0) * 1000

        assert elapsed < 60  # 45 次 MC 模拟确定排名分布
        assert result["sim_count"] == 0


class TestBattleAnalyzerSimCount:
    """模拟次数测试。"""

    def test_preflop_uses_preflop_sim_count(self) -> None:
        analyzer = BattleAnalyzer(preflop_sims=100, postflop_sims=20, seed=42)
        hole = cards("Ah Kh")
        players = make_players(["Hero", "Bot1"])
        players[0].is_human = True
        game = make_game(players)

        result = analyzer.analyze(
            hole_cards=hole, community_cards=[],
            active_opponent_count=1, game=game, player=players[0],
        )

        assert result["sim_count"] == 100

    def test_postflop_uses_postflop_sim_count(self) -> None:
        """翻牌后使用 postflop_sims 次模拟。"""
        analyzer = BattleAnalyzer(preflop_sims=100, postflop_sims=20, seed=42)
        hole = cards("Ac Ks")
        community = cards("Kh 8d 2c")
        players = make_players(["Hero", "Bot1"])
        players[0].is_human = True
        game = make_game(players)
        game.community_cards = community

        result = analyzer.analyze(
            hole_cards=hole, community_cards=community,
            active_opponent_count=1, game=game, player=players[0],
        )

        assert result["sim_count"] == 20

    def test_zero_opponents_rank_distribution(self) -> None:
        """0 个活跃对手时，河牌排名分布律只有第 1 名（100%）。"""
        analyzer = BattleAnalyzer(preflop_sims=227, postflop_sims=45, seed=42)
        hole = cards("Ah Kh")
        community = cards("Qh Jh Th 2d 3c")
        # GameState 需要至少 2 个玩家
        players = make_players(["Hero", "Bot1"])
        players[0].is_human = True
        game = make_game(players)
        game.community_cards = community

        result = analyzer.analyze(
            hole_cards=hole, community_cards=community,
            active_opponent_count=0, game=game, player=players[0],
        )

        dist = result["ranking_distribution"]
        assert len(dist) == 1
        assert dist[0]["prob"] == 100.0

    def test_deterministic_results(self) -> None:
        """相同输入多次调用返回完全一致的结果（同一轮 check 不会抖动）。"""
        analyzer = BattleAnalyzer(preflop_sims=227, postflop_sims=45, seed=42)
        hole = cards("Ah Kh")
        players = make_players(["Hero", "Bot1", "Bot2", "Bot3"])
        players[0].is_human = True
        game = make_game(players)
        # 模拟有人加注后轮到 Hero，跟注状态
        players[1].total_bet = 20
        game.pot.add_bet(players[1], 20)
        game.current_bet = 20

        r1 = analyzer.analyze(
            hole_cards=hole, community_cards=[],
            active_opponent_count=3, game=game, player=players[0],
        )
        r2 = analyzer.analyze(
            hole_cards=hole, community_cards=[],
            active_opponent_count=3, game=game, player=players[0],
        )

        # 所有分析字段应完全一致
        assert r1["hand_type_probs"] == r2["hand_type_probs"]
        assert r1["ranking_distribution"] == r2["ranking_distribution"]
        assert r1["odds_ev"] == r2["odds_ev"]
        assert r1["sim_count"] == r2["sim_count"]

    def test_results_change_on_new_community_card(self) -> None:
        """公共牌翻出后，结果应该变化。"""
        analyzer = BattleAnalyzer(preflop_sims=100, postflop_sims=20, seed=42)
        hole = cards("Ah Kh")
        players = make_players(["Hero", "Bot1", "Bot2"])
        players[0].is_human = True
        game = make_game(players)

        r_pre = analyzer.analyze(
            hole_cards=hole, community_cards=[],
            active_opponent_count=2, game=game, player=players[0],
        )
        community = cards("2d 7h Kc")
        game.community_cards = community
        r_post = analyzer.analyze(
            hole_cards=hole, community_cards=community,
            active_opponent_count=2, game=game, player=players[0],
        )

        # 牌型概率应该变化（翻牌前 vs 翻牌后）
        assert r_pre["hand_type_probs"] != r_post["hand_type_probs"]
