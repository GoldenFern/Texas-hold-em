"""Web 层测试 —— 应用工厂、路由、GameManager 生命周期与拒绝路径。"""

from __future__ import annotations

from typing import List, Tuple

import pytest

from flask import Flask

from src.server.events import GameManager, GameSessionRegistry
from src.utils.constants import ActionType


class FakeSocketIO:
    """记录 emit 调用的假 SocketIO(不联网、不起后台线程)。"""

    def __init__(self) -> None:
        self.emitted: List[Tuple[str, dict]] = []
        self.background_tasks: list = []

    def emit(self, event: str, payload: dict = None) -> None:  # noqa: D102
        self.emitted.append((event, payload or {}))

    def start_background_task(self, fn, *args, **kwargs):  # noqa: D102
        # 同步执行,便于断言(分析广播/循环不在这些测试中启动)
        self.background_tasks.append(fn)

    def sleep(self, seconds: float) -> None:  # noqa: D102
        pass

    def events(self, name: str) -> List[dict]:
        """按事件名过滤已发出的载荷。"""
        return [p for e, p in self.emitted if e == name]


def make_manager() -> tuple[GameManager, FakeSocketIO]:
    sio = FakeSocketIO()
    mgr = GameManager(sio)  # type: ignore[arg-type]
    return mgr, sio


BOTS = [{"style": "BALANCED", "name": "B1"}, {"style": "COOL", "name": "B2"}]


class TestAppFactory:
    def test_create_app_returns_flask_app(self) -> None:
        from src.server.app import create_app
        app = create_app()
        assert isinstance(app, Flask)
        assert app.config["SECRET_KEY"]

    def test_routes_registered(self) -> None:
        from src.server.app import create_app
        app = create_app()
        rules = sorted(r.rule for r in app.url_map.iter_rules())
        assert "/" in rules
        assert "/api/game/state" in rules
        assert "/api/game/history" in rules
        assert "/api/game/analysis" in rules
        assert "/api/bots/styles" in rules
        # 与 SocketIO 重复的写路由已删除
        assert "/api/game/new" not in rules
        assert "/api/game/action" not in rules


class TestRoutesBasics:
    def test_bot_styles_route(self) -> None:
        from src.server.app import create_app
        app = create_app()
        app.config["TESTING"] = True
        with app.test_client() as client:
            resp = client.get("/api/bots/styles")
            assert resp.status_code == 200
            styles = resp.get_json()
            assert any(s["style"] == "BALANCED" for s in styles)

    def test_state_404_without_game(self) -> None:
        from src.server.app import create_app
        from src.server import events as evt
        app = create_app()
        app.config["TESTING"] = True
        evt._game_manager.game = None
        with app.test_client() as client:
            assert client.get("/api/game/state").status_code == 404

    def test_llm_config_post_rejects_bad_base_url(self) -> None:
        from src.server.app import create_app
        app = create_app()
        app.config["TESTING"] = True
        with app.test_client() as client:
            resp = client.post("/api/config/llm", json={
                "primary": {"provider": "deepseek", "model": "m",
                            "base_url": "https://evil.example.com"},
            })
            assert resp.status_code == 400


class TestGameManager:
    def test_create_game(self) -> None:
        mgr, sio = make_manager()
        ok, reason = mgr.create_game("Hero", BOTS)
        assert ok, reason
        assert mgr.game is not None
        assert len(mgr.game.players) == 3
        assert mgr.game.players[0].is_human
        assert sio.events("game_update")

    def test_invalid_bot_style_rejected(self) -> None:
        mgr, _ = make_manager()
        ok, reason = mgr.create_game("Hero", [{"style": "NOPE"}])
        assert not ok
        assert "NOPE" in reason
        assert mgr.game is None

    def test_bot_names_sanitized(self) -> None:
        mgr, _ = make_manager()
        ok, _ = mgr.create_game(
            "Hero", [{"style": "BALANCED", "name": "<script>x</script>Bob"},
                     {"style": "COOL", "name": "B2"}],
        )
        assert ok
        names = [p.name for p in mgr.game.players]
        assert all("<" not in n for n in names)
        assert "xBob" in names

    def test_human_action_wrong_turn_reports_reason(self) -> None:
        mgr, _ = make_manager()
        mgr.create_game("Hero", BOTS)
        game = mgr.game
        # 强制指到非人类玩家
        for i, p in enumerate(game.players):
            if not p.is_human and p.status.name == "ACTIVE":
                game.current_player_index = i
                break
        ok, reason = mgr.handle_human_action(ActionType.CALL, 0)
        assert not ok
        assert "回合" in reason

    def test_human_illegal_action_reports_reason(self) -> None:
        mgr, _ = make_manager()
        mgr.create_game("Hero", BOTS)
        game = mgr.game
        human_idx = next(
            i for i, p in enumerate(game.players) if p.is_human
        )
        game.current_player_index = human_idx
        # 面对大盲不能 CHECK（除非自己就是 BB 已平齐）
        human = game.players[human_idx]
        if game.current_bet == human.current_bet:
            ok, reason = mgr.handle_human_action(ActionType.CALL, 0)
        else:
            ok, reason = mgr.handle_human_action(ActionType.CHECK, 0)
        assert not ok
        assert "非法动作" in reason

    def test_end_game_clears_state(self) -> None:
        mgr, sio = make_manager()
        mgr.create_game("Hero", BOTS)
        assert mgr.game is not None
        mgr.end_game()
        assert mgr.game is None
        assert mgr._bot_running is False
        assert sio.events("game_over")

    def test_create_game_replaces_previous(self) -> None:
        mgr, _ = make_manager()
        mgr.create_game("Hero", BOTS)
        gen1 = mgr._game_generation
        mgr.create_game("Hero2", BOTS)
        assert mgr._game_generation == gen1 + 1
        assert mgr.human_player_name == "Hero2"

    def test_action_applied_event_has_sequence_and_pot(self) -> None:
        """每个成功动作只发一次带手牌序号的实时事件。"""
        mgr, sio = make_manager()
        mgr.create_game("Hero", BOTS)
        game = mgr.game
        human_idx = next(i for i, p in enumerate(game.players) if p.is_human)
        game.current_player_index = human_idx
        legal = game.get_legal_actions(game.players[human_idx])
        action = ActionType.CALL if ActionType.CALL in legal else ActionType.CHECK

        ok, reason = mgr.handle_human_action(action, 0)
        assert ok, reason
        events = sio.events("action_applied")
        assert len(events) == 1
        assert events[0]["hand_id"] == game.hand_id
        assert events[0]["action_index"] == 0
        assert events[0]["action"] == action.name.lower()
        assert isinstance(events[0]["occurred_at"], int)
        assert events[0]["pot_total"] >= 0

    def test_action_required_includes_server_deadline(self) -> None:
        mgr, sio = make_manager()
        mgr.create_game("Hero", BOTS)
        mgr._emit_action_required("Hero")
        payload = sio.events("action_required")[-1]
        assert payload["hand_id"] == mgr.game.hand_id
        assert payload["deadline_at"] > 0
        assert payload["deadline_at"] >= payload["timeout_seconds"] * 1000

    def test_decision_review_uses_visible_snapshot_without_result_bias(self) -> None:
        mgr, _ = make_manager()
        mgr._decision_snapshots = [{
            "action_index": 2,
            "action": "call",
            "phase": "FLOP",
            "equity": 31.5,
            "required_equity": 40.0,
            "ev": -1.7,
        }]
        review = mgr._build_decision_review()
        assert review is not None
        assert review["action_index"] == 2
        assert review["verdict"] == "review"
        assert review["equity"] == 31.5
        assert "输" not in review["detail"]

    def test_auto_act_for_human_on_timeout(self) -> None:
        """超时自动动作:能过则过牌,否则弃牌,并广播 action_rejected。"""
        mgr, sio = make_manager()
        mgr.create_game("Hero", BOTS)
        game = mgr.game
        human_idx = next(i for i, p in enumerate(game.players) if p.is_human)
        game.current_player_index = human_idx
        hand_before = game.hand_id
        actions_before = len(game.all_actions)
        mgr._auto_act_for_human()
        assert len(game.all_actions) > actions_before or game.hand_id != hand_before
        assert sio.events("action_rejected")


class TestBotLoopErrorSurfacing:
    def test_loop_step_error_emits_game_error(self) -> None:
        """循环内异常必须上报 game_error 且循环存活(不再静默冻结)。"""
        mgr, sio = make_manager()
        mgr.create_game("Hero", BOTS)
        # 制造损坏状态触发异常
        mgr.bots.clear()
        game = mgr.game
        bot_idx = next(
            i for i, p in enumerate(game.players) if not p.is_human
        )
        game.current_player_index = bot_idx
        mgr._bot_running = True
        with pytest.raises(RuntimeError):
            mgr._bot_loop_step()  # step 本身抛出

        # 外层 _bot_loop 捕获并上报
        calls = {"n": 0}

        def failing_step():
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("boom")
            mgr._bot_running = False
            return True

        mgr._bot_loop_step = failing_step  # type: ignore[method-assign]
        mgr._bot_running = True
        mgr._bot_loop()
        assert any("服务器内部错误" in p.get("message", "")
                   for p in sio.events("game_error"))
        assert calls["n"] == 2  # 异常后循环继续跑了下一轮


class TestInputValidation:
    """入口级输入校验:畸形参数必须被拒绝而非静默崩溃。"""

    def test_player_action_rejects_non_numeric_amount(self) -> None:
        mgr, _ = make_manager()
        mgr.create_game("Hero", BOTS)
        game = mgr.game
        human_idx = next(i for i, p in enumerate(game.players) if p.is_human)
        game.current_player_index = human_idx
        legal = game.get_legal_actions(game.players[human_idx])
        target = (
            ActionType.BET if ActionType.BET in legal else ActionType.RAISE
        )
        assert target in legal  # 本测试需要一条带金额的合法动作
        for bad_amount in ("", None, float("nan"), float("inf"), True, 10.5):
            ok, reason = mgr.handle_human_action(target, bad_amount)
            assert not ok
            assert "金额" in reason or "数字" in reason
            # 非法输入不得推进游戏状态
            assert game.current_player_index == human_idx
        # 合法整数金额通过类型校验并被服务端钳位接受
        ok, reason = mgr.handle_human_action(target, 999999)
        assert ok, reason

    def test_new_game_rejects_bad_numeric_params(self) -> None:
        mgr, _ = make_manager()
        ok, reason = mgr.create_game("Hero", BOTS, starting_chips=-5)
        assert not ok
        assert mgr.game is None

    def test_new_game_rejects_unknown_betting_structure(self) -> None:
        mgr, _ = make_manager()
        ok, reason = mgr.create_game(
            "Hero", BOTS, betting_structure="super_turbo",
        )
        assert not ok
        assert "下注结构" in reason
        assert mgr.game is None  # 显式报错,不再静默回落无限注

    def test_new_game_rejects_duplicate_names(self) -> None:
        mgr, _ = make_manager()
        ok, reason = mgr.create_game("Hero", [
            {"style": "BALANCED", "name": "Hero"},   # 与人类重名
            {"style": "COOL", "name": "B"},
        ])
        assert not ok
        assert "重复" in reason
        ok, reason = mgr.create_game("Hero", [
            {"style": "BALANCED", "name": "B"},      # Bot 之间重名
            {"style": "COOL", "name": "B"},
        ])
        assert not ok
        assert "重复" in reason
        assert mgr.game is None


class TestCreateGameRollback:
    def test_failure_rolls_back_to_consistent_state(self, monkeypatch) -> None:
        """构建中途异常必须回滚到无游戏状态并上报 game_error。"""
        from src.server import events as evt_mod
        mgr, sio = make_manager()
        mgr.create_game("Hero", BOTS)
        gen_before = mgr._game_generation

        def boom(*args, **kwargs):
            raise RuntimeError("engine exploded")

        monkeypatch.setattr(evt_mod, "GameState", boom)
        ok, reason = mgr.create_game("Hero2", BOTS)
        assert not ok
        assert "创建游戏失败" in reason
        # 一致性:回到无游戏状态,而非旧游戏残留 + 循环已死的撕裂态
        assert mgr.game is None
        assert mgr.bots == {}
        assert mgr.human_player_name == ""
        assert mgr._game_generation == gen_before + 1
        assert any(
            "创建游戏失败" in p.get("message", "")
            for p in sio.events("game_error")
        )


class TestWaitSideGenerationGuard:
    def test_auto_act_skipped_on_stale_generation(self) -> None:
        """开新局后,旧循环的人类超时自动行动必须作废(防跨局误伤)。"""
        mgr, sio = make_manager()
        mgr.create_game("Hero", BOTS)
        game = mgr.game
        human_idx = next(i for i, p in enumerate(game.players) if p.is_human)
        game.current_player_index = human_idx
        actions_before = len(game.all_actions)

        stale_gen = mgr._game_generation - 1
        mgr._auto_act_for_human(stale_gen)
        assert len(game.all_actions) == actions_before
        assert not sio.events("action_rejected")


class TestSessionRegistry:
    def test_default_session(self) -> None:
        reg = GameSessionRegistry()
        a = reg.get_or_create("default")
        assert reg.get_or_create("default") is a
        assert reg.get("missing") is None

    def test_future_multi_session_seam(self) -> None:
        reg = GameSessionRegistry()
        a = reg.get_or_create("t1")
        b = reg.get_or_create("t2")
        assert a is not b
