"""Web 层测试 —— Flask 应用工厂、API 路由、GameManager 生命周期。"""

import pytest

# 测试 Flask 是否可用
_flask_available = True
try:
    from flask import Flask
    from flask.testing import FlaskClient
except ImportError:
    _flask_available = False


def _requires_flask():
    if not _flask_available:
        pytest.skip("Flask 未安装")


class TestAppFactory:
    """Flask 应用工厂测试。"""

    def test_create_app_returns_flask_app(self) -> None:
        _requires_flask()
        from src.server.app import create_app
        app = create_app()
        assert isinstance(app, Flask)
        assert app.config["SECRET_KEY"] is not None

    def test_routes_registered(self) -> None:
        _requires_flask()
        from src.server.app import create_app
        app = create_app()
        rules = sorted(r.rule for r in app.url_map.iter_rules())
        assert "/" in rules
        assert "/api/game/state" in rules
        assert "/api/game/new" in rules
        assert "/api/game/action" in rules
        assert "/api/game/history" in rules
        assert "/api/game/analysis" in rules
        assert "/api/bots/styles" in rules


class TestRoutesBasics:
    """REST API 路由基本功能测试。"""

    def test_index_route(self) -> None:
        _requires_flask()
        from src.server.app import create_app
        app = create_app()
        app.config["TESTING"] = True
        client = app.test_client()
        response = client.get("/")
        assert response.status_code == 200

    def test_bot_styles_route(self) -> None:
        _requires_flask()
        from src.server.app import create_app
        app = create_app()
        app.config["TESTING"] = True
        client = app.test_client()
        response = client.get("/api/bots/styles")
        assert response.status_code == 200
        data = response.get_json()
        assert isinstance(data, list)
        assert len(data) >= 6
        # 验证字段
        for bot in data:
            assert "style" in bot
            assert "display_name" in bot
            assert "description" in bot

    def test_game_state_no_game_returns_404(self) -> None:
        _requires_flask()
        from src.server.app import create_app
        from src.server import events
        app = create_app()
        app.config["TESTING"] = True
        client = app.test_client()
        events._game_manager.game = None
        response = client.get("/api/game/state")
        assert response.status_code == 404

    def test_game_history_no_game_returns_empty(self) -> None:
        _requires_flask()
        from src.server.app import create_app
        from src.server import events
        app = create_app()
        app.config["TESTING"] = True
        client = app.test_client()
        events._game_manager.game = None
        response = client.get("/api/game/history")
        # game_history route only checks mgr is None, not game is None
        assert response.status_code == 200


class TestGameManager:
    """GameManager 生命周期测试。"""

    def test_import_game_manager(self) -> None:
        from src.server.events import GameManager, _game_manager
        assert _game_manager is not None
        assert isinstance(_game_manager, GameManager)
        assert _game_manager.game is None

    def test_create_game(self) -> None:
        from src.server.events import GameManager
        mgr = GameManager()
        mgr.create_game(
            player_name="Hero",
            bot_configs=[
                {"style": "TAG", "name": "Bot1"},
                {"style": "NIT", "name": "Bot2"},
            ],
            starting_chips=1000,
            small_blind=5,
            big_blind=10,
        )
        assert mgr.game is not None
        assert mgr.human_player_name == "Hero"
        assert len(mgr.bots) == 2
        assert "Bot1" in mgr.bots
        assert "Bot2" in mgr.bots
        assert mgr.game.phase.value < 6  # 未结束

    def test_create_game_with_llm_bot(self) -> None:
        from src.server.events import GameManager
        mgr = GameManager()
        mgr.create_game(
            player_name="Hero",
            bot_configs=[
                {"style": "LLM", "name": "AI", "llm_config": {"provider": "mock", "model": "mock"}},
            ],
        )
        assert mgr.game is not None
        assert "AI" in mgr.bots

    def test_create_game_replaces_previous(self) -> None:
        from src.server.events import GameManager
        mgr = GameManager()
        mgr.create_game(
            player_name="Hero1",
            bot_configs=[{"style": "TAG", "name": "Bot1"}],
        )
        game1_id = id(mgr.game)
        mgr.create_game(
            player_name="Hero2",
            bot_configs=[{"style": "LAG", "name": "Bot2"}],
        )
        assert mgr.human_player_name == "Hero2"
        assert id(mgr.game) != game1_id

    def test_human_player_name(self) -> None:
        from src.server.events import GameManager
        mgr = GameManager()
        assert mgr.get_human_player_name() == ""
        mgr.create_game(player_name="Alice", bot_configs=[{"style": "TAG", "name": "Bot1"}])
        assert mgr.get_human_player_name() == "Alice"

    def test_replay_empty_returns_none(self) -> None:
        from src.server.events import GameManager
        mgr = GameManager()
        assert mgr.get_replay() is None
        assert mgr.get_replay_list() == []

    def test_end_game_stops_bot_loop(self) -> None:
        from src.server.events import GameManager
        mgr = GameManager()
        assert mgr._bot_running is False
        # 创建游戏后 bot loop 应该启动了
        # 但这里测试不用 socketio，所以 _start_bot_loop 会跳过
        mgr.end_game()
        assert mgr._bot_running is False

    def test_continue_game_resumes(self) -> None:
        from src.server.events import GameManager
        mgr = GameManager()
        mgr.continue_game()
        # 应该不抛异常
        assert mgr._hand_paused is False


class TestRoutesRoutesSetGameManager:
    """routes.py 的 set/get 工具函数。"""

    def test_set_and_get_game_manager(self) -> None:
        from src.server.routes import set_game_manager, get_game_manager

        mgr = get_game_manager()
        assert mgr is not None

        # set 和 get 应在导入 events 后被自动调用
        from src.server.events import _game_manager
        assert get_game_manager() is _game_manager
