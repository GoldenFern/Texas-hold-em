"""牌局记录与统计报告器测试。"""

import pytest

from src.analysis.reporter import HandReporter, PlayerStats
from src.engine.game import Action, ActionType, HandHistory
from src.engine.card import Card
from src.engine.hand import HandEvaluator
from src.utils.constants import GamePhase, HandRank


def make_action(
    name: str,
    action_type: ActionType,
    amount: int = 0,
    phase: GamePhase = GamePhase.PRE_FLOP,
) -> Action:
    return Action(player_name=name, action_type=action_type, amount=amount, phase=phase)


def make_hand_history(
    hand_id: int = 1,
    players: list | None = None,
    winners: dict | None = None,
    actions: list | None = None,
    snapshots: list | None = None,
) -> HandHistory:
    player_list = players or ["A", "B"]
    win_map = winners or {}
    return HandHistory(
        hand_id=hand_id,
        players=player_list,
        hole_cards={},
        community_cards=[],
        actions=actions or [],
        winners=win_map,
        winning_hands={},
        pot_total=sum(win_map.values()),
        step_snapshots=snapshots or [],
    )


class TestPlayerStats:
    """PlayerStats 统计属性。"""

    def test_default_values(self) -> None:
        ps = PlayerStats(name="Hero")
        assert ps.name == "Hero"
        assert ps.hands_played == 0
        assert ps.hands_won == 0
        assert ps.vpip == 0.0
        assert ps.pfr == 0.0
        assert ps.aggression_factor == 0.0
        assert ps.win_rate == 0.0
        assert ps.profit == 0

    def test_vpip_calculation(self) -> None:
        ps = PlayerStats(name="Hero", hands_played=10, vpip_count=4)
        assert ps.vpip == 0.4

    def test_pfr_calculation(self) -> None:
        ps = PlayerStats(name="Hero", hands_played=10, pfr_count=2)
        assert ps.pfr == 0.2

    def test_aggression_factor(self) -> None:
        ps = PlayerStats(name="Hero", raise_count=8, call_count=4)
        assert ps.aggression_factor == 2.0

    def test_aggression_factor_no_calls(self) -> None:
        ps = PlayerStats(name="Hero", raise_count=5, call_count=0)
        assert ps.aggression_factor == 5.0

    def test_aggression_factor_zero(self) -> None:
        ps = PlayerStats(name="Hero", raise_count=0, call_count=0)
        assert ps.aggression_factor == 0.0

    def test_win_rate(self) -> None:
        ps = PlayerStats(name="Hero", hands_played=20, hands_won=5)
        assert ps.win_rate == 0.25

    def test_win_rate_zero_hands(self) -> None:
        ps = PlayerStats(name="Hero", hands_played=0, hands_won=0)
        assert ps.win_rate == 0.0

    def test_profit_positive(self) -> None:
        ps = PlayerStats(name="Hero", total_won=500, total_spent=300)
        assert ps.profit == 200

    def test_profit_negative(self) -> None:
        ps = PlayerStats(name="Hero", total_won=200, total_spent=300)
        assert ps.profit == -100


class TestHandReporterRecord:
    """record_hand 测试（无 snapshot）。"""

    def test_record_hand_adds_history(self) -> None:
        reporter = HandReporter()
        h = make_hand_history(hand_id=1)
        reporter.record_hand(h)
        assert len(reporter.history) == 1

    def test_record_hand_creates_player_stats(self) -> None:
        reporter = HandReporter()
        h = make_hand_history(hand_id=1, players=["A", "B", "C"])
        reporter.record_hand(h)
        assert "A" in reporter.player_stats
        assert "B" in reporter.player_stats
        assert "C" in reporter.player_stats

    def test_record_hand_increments_hands_played(self) -> None:
        reporter = HandReporter()
        h = make_hand_history(hand_id=1, players=["A", "B"])
        reporter.record_hand(h)
        assert reporter.player_stats["A"].hands_played == 1
        assert reporter.player_stats["B"].hands_played == 1

    def test_record_hand_tracks_winners(self) -> None:
        reporter = HandReporter()
        h = make_hand_history(hand_id=1, players=["A", "B"], winners={"A": 100})
        reporter.record_hand(h)
        assert reporter.player_stats["A"].hands_won == 1
        assert reporter.player_stats["A"].total_won == 100
        assert reporter.player_stats["B"].hands_won == 0

    def test_record_hand_tracks_actions(self) -> None:
        reporter = HandReporter()
        actions = [
            make_action("A", ActionType.FOLD),
            make_action("B", ActionType.CALL),
            make_action("B", ActionType.RAISE, amount=30),
        ]
        h = make_hand_history(hand_id=1, players=["A", "B"], actions=actions)
        reporter.record_hand(h)
        assert reporter.player_stats["A"].fold_count == 1
        assert reporter.player_stats["B"].call_count == 1
        assert reporter.player_stats["B"].raise_count == 1

    def test_vpip_pfr_once_per_hand(self) -> None:
        reporter = HandReporter()
        actions = [
            make_action("A", ActionType.CALL, phase=GamePhase.PRE_FLOP),
            make_action("A", ActionType.CALL, phase=GamePhase.PRE_FLOP),
            make_action("B", ActionType.RAISE, phase=GamePhase.PRE_FLOP),
            make_action("B", ActionType.RAISE, phase=GamePhase.PRE_FLOP),
        ]
        h = make_hand_history(hand_id=1, players=["A", "B"], actions=actions)
        reporter.record_hand(h)
        assert reporter.player_stats["A"].vpip_count == 1
        assert reporter.player_stats["B"].vpip_count == 1
        assert reporter.player_stats["B"].pfr_count == 1

    def test_vpip_postflop_not_counted(self) -> None:
        reporter = HandReporter()
        actions = [
            make_action("A", ActionType.CALL, phase=GamePhase.FLOP),
            make_action("B", ActionType.RAISE, phase=GamePhase.RIVER),
        ]
        h = make_hand_history(hand_id=1, players=["A", "B"], actions=actions)
        reporter.record_hand(h)
        assert reporter.player_stats["A"].vpip_count == 0
        assert reporter.player_stats["B"].pfr_count == 0


class TestHandReporterWithSnapshots:
    """record_hand 测试（含 step_snapshots）。"""

    def test_spent_calculated_from_snapshots(self) -> None:
        reporter = HandReporter()
        snapshots = [
            {"players": [{"name": "A", "chips": 1000}, {"name": "B", "chips": 1000}]},
            {"players": [{"name": "A", "chips": 950}, {"name": "B", "chips": 1020}]},
        ]
        h = make_hand_history(
            hand_id=1, players=["A", "B"], winners={"B": 50}, snapshots=snapshots
        )
        reporter.record_hand(h)
        assert reporter.player_stats["A"].total_spent == 50
        assert reporter.player_stats["B"].total_spent == 30

    def test_spent_zero_when_no_snapshot(self) -> None:
        reporter = HandReporter()
        h = make_hand_history(hand_id=1, players=["A", "B"])
        reporter.record_hand(h)
        assert reporter.player_stats["A"].total_spent == 0

    def test_spent_excludes_rebuy_chips(self) -> None:
        """重购筹码不应计为实际投入。"""
        reporter = HandReporter()
        # A 本局用了重购，B 正常
        snapshots = [
            {
                "players": [
                    {"name": "A", "chips": 1000, "rebuy_count": 1},
                    {"name": "B", "chips": 1000, "rebuy_count": 0},
                ]
            },
            {
                "players": [
                    {"name": "A", "chips": 0, "rebuy_count": 1},
                    {"name": "B", "chips": 1020, "rebuy_count": 0},
                ]
            },
        ]
        h = make_hand_history(
            hand_id=1, players=["A", "B"], winners={"B": 50}, snapshots=snapshots
        )
        reporter.record_hand(h)
        # A: chips 1000->0, won 0, rebuy=1000 => spent = 0
        assert reporter.player_stats["A"].total_spent == 0
        # B: chips 1000->1020, won 50 => spent = 1000-1020+50 = 30
        assert reporter.player_stats["B"].total_spent == 30

    def test_profit_sums_to_zero(self) -> None:
        """零和游戏：所有玩家 profit 之和必为 0。"""
        reporter = HandReporter()
        snapshots = [
            {
                "players": [
                    {"name": "A", "chips": 1000, "rebuy_count": 0},
                    {"name": "B", "chips": 1000, "rebuy_count": 0},
                    {"name": "C", "chips": 1000, "rebuy_count": 0},
                ]
            },
            {
                "players": [
                    {"name": "A", "chips": 980, "rebuy_count": 0},
                    {"name": "B", "chips": 950, "rebuy_count": 0},
                    {"name": "C", "chips": 1070, "rebuy_count": 0},
                ]
            },
        ]
        h = make_hand_history(
            hand_id=1, players=["A", "B", "C"], winners={"C": 100}, snapshots=snapshots
        )
        reporter.record_hand(h)
        profits = [reporter.player_stats[n].profit for n in ["A", "B", "C"]]
        assert sum(profits) == 0, f"profit sum = {sum(profits)}"

    def test_profit_sums_to_zero_with_rebuy(self) -> None:
        """有重购时，total_spent 不计入重购筹码，profit 正确反映实际盈亏。"""
        reporter = HandReporter()
        # A 重购了 1000 筹码，最终全输光；B 输了 50；C 赢了 1100
        snapshots = [
            {
                "players": [
                    {"name": "A", "chips": 1000, "rebuy_count": 1},
                    {"name": "B", "chips": 1000, "rebuy_count": 0},
                    {"name": "C", "chips": 1000, "rebuy_count": 0},
                ]
            },
            {
                "players": [
                    {"name": "A", "chips": 0, "rebuy_count": 1},
                    {"name": "B", "chips": 950, "rebuy_count": 0},
                    {"name": "C", "chips": 2050, "rebuy_count": 0},
                ]
            },
        ]
        h = make_hand_history(
            hand_id=1, players=["A", "B", "C"],
            winners={"C": 1100}, snapshots=snapshots
        )
        reporter.record_hand(h)
        a = reporter.player_stats["A"]
        b = reporter.player_stats["B"]
        c = reporter.player_stats["C"]
        # A 的 spent 不是 1000（那 1000 来自重购）
        assert a.total_spent == 0
        # B 输了 50
        assert b.total_spent == 50
        assert b.profit == -50
        # C 投了 50，赢了 1100
        assert c.total_spent == 50
        assert c.profit == 1050


class TestHandReporterQuery:
    """查询方法测试。"""

    def test_get_stats_existing(self) -> None:
        reporter = HandReporter()
        h = make_hand_history(hand_id=1, players=["A", "B"])
        reporter.record_hand(h)
        stats = reporter.get_stats("A")
        assert stats is not None
        assert stats.name == "A"

    def test_get_stats_nonexistent(self) -> None:
        reporter = HandReporter()
        assert reporter.get_stats("X") is None

    def test_get_all_stats(self) -> None:
        reporter = HandReporter()
        h = make_hand_history(hand_id=1, players=["A", "B", "C"])
        reporter.record_hand(h)
        assert len(reporter.get_all_stats()) == 3

    def test_get_summary(self) -> None:
        reporter = HandReporter()
        h = make_hand_history(hand_id=1, players=["A", "B"], winners={"A": 50, "B": 50})
        reporter.record_hand(h)
        summary = reporter.get_summary()
        assert summary["total_hands"] == 1
        assert len(summary["player_stats"]) == 2

    def test_last_hand_summary(self) -> None:
        reporter = HandReporter()
        h = make_hand_history(hand_id=42, players=["A", "B"])
        reporter.record_hand(h)
        last = reporter.last_hand_summary()
        assert last is not None
        assert last["hand_id"] == 42

    def test_last_hand_summary_empty(self) -> None:
        reporter = HandReporter()
        assert reporter.last_hand_summary() is None

    def test_clear_resets_all(self) -> None:
        reporter = HandReporter()
        h = make_hand_history(hand_id=1, players=["A", "B"])
        reporter.record_hand(h)
        reporter.clear()
        assert len(reporter.history) == 0
        assert len(reporter.player_stats) == 0
        assert reporter.last_hand_summary() is None


class TestMultiHandAccumulation:
    """多手牌累积统计。"""

    def test_multi_hand_cumulative_stats(self) -> None:
        reporter = HandReporter()
        actions1 = [
            make_action("A", ActionType.RAISE, phase=GamePhase.PRE_FLOP),
            make_action("B", ActionType.FOLD, phase=GamePhase.PRE_FLOP),
        ]
        h1 = make_hand_history(hand_id=1, players=["A", "B"], winners={"A": 30}, actions=actions1)
        reporter.record_hand(h1)
        actions2 = [
            make_action("B", ActionType.RAISE, phase=GamePhase.PRE_FLOP),
            make_action("A", ActionType.FOLD, phase=GamePhase.PRE_FLOP),
        ]
        h2 = make_hand_history(hand_id=2, players=["A", "B"], winners={"B": 30}, actions=actions2)
        reporter.record_hand(h2)
        assert reporter.player_stats["A"].hands_played == 2
        assert reporter.player_stats["B"].hands_played == 2
        assert reporter.player_stats["A"].hands_won == 1
        assert reporter.player_stats["B"].hands_won == 1
        assert reporter.player_stats["A"].pfr_count == 1
        assert reporter.player_stats["B"].pfr_count == 1
