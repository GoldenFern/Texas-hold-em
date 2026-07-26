"""ContextManager 会话上下文测试 —— 窗口裁剪、对手分类、桌面形象、净利润展示。"""

from __future__ import annotations

import pytest

from src.analysis.reporter import HandReporter, PlayerStats
from src.llm.context_manager import ContextManager, classify_opponent
from src.utils.constants import ActionType


class TestClassifyOpponent:
    def test_rock(self) -> None:
        label, _ = classify_opponent(vpip=0.10, pfr=0.08)
        assert "Rock" in label

    def test_tag(self) -> None:
        label, _ = classify_opponent(vpip=0.22, pfr=0.18)
        assert "TAG" in label

    def test_calling_station(self) -> None:
        label, _ = classify_opponent(vpip=0.55, pfr=0.10)
        assert "Calling Station" in label

    def test_lag_fallthrough(self) -> None:
        label, _ = classify_opponent(vpip=0.45, pfr=0.35)
        assert "LAG" in label


class TestHandWindow:
    def test_window_trims_to_n(self) -> None:
        ctx = ContextManager(bot_name="B", context_window_hands=3)
        for i in range(10):
            ctx.record_action("B", ActionType.CALL, hole_cards="Ah Kh", hand_id=i)
            ctx.end_hand(won=False, profit=-10)
        assert len(ctx._hand_summaries) == 3
        assert ctx._hand_summaries[-1].hand_id == 9

    def test_negative_profit_visible_in_summary(self) -> None:
        """L2 回归: 输家的负净利润必须出现在上下文里。"""
        ctx = ContextManager(bot_name="B", context_window_hands=5)
        ctx.record_action("B", ActionType.CALL, hole_cards="Ah Kh", hand_id=1)
        ctx.end_hand(won=False, profit=-120)
        text = ctx.get_context_for_prompt()
        assert "-$-120" not in text  # 不应出现双符号
        assert "$-120" in text or "-120" in text

    def test_context_empty_initially(self) -> None:
        ctx = ContextManager(bot_name="B")
        assert ctx.get_context_for_prompt() == ""


class TestTableImage:
    def test_aggressive_image(self) -> None:
        ctx = ContextManager(bot_name="B")
        for _ in range(6):
            ctx.record_action("B", ActionType.RAISE, hand_id=1)
        for _ in range(4):
            ctx.record_action("B", ActionType.CALL, hand_id=1)
        image = ctx.get_table_image()
        assert image["image_label"] == "激进"
        assert image["aggression_frequency"] == 0.6


class TestOpponentSync:
    def test_sync_from_reporter(self) -> None:
        reporter = HandReporter()
        reporter.player_stats["V"] = PlayerStats(
            name="V", hands_played=40, vpip_count=8, pfr_count=6,
            raise_count=12, call_count=6,
        )
        ctx = ContextManager(bot_name="B")
        ctx._sync_opponent_stats(reporter)
        profile = ctx.get_opponent_stats("V")
        assert profile.hands_played == 40
        assert profile.vpip == pytest.approx(0.2)
        assert profile.classification

    def test_self_excluded(self) -> None:
        reporter = HandReporter()
        reporter.player_stats["B"] = PlayerStats(name="B", hands_played=10)
        ctx = ContextManager(bot_name="B")
        ctx._sync_opponent_stats(reporter)
        assert ctx.get_opponent_stats("B").hands_played == 0

    def test_showdown_records_kept_recent(self) -> None:
        ctx = ContextManager(bot_name="B")
        for i in range(8):
            ctx.record_showdown("V", f"A{i} K{i}")
        profile = ctx.get_opponent_stats("V")
        assert len(profile.showdown_hands) == 5
