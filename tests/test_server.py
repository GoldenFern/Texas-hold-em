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
