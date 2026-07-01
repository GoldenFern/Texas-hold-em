"""REST API 路由。"""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict

from flask import Flask, jsonify, render_template, request

# 全局游戏管理器引用（在 events.py 中初始化）
_game_manager: Any = None


def get_game_manager() -> Any:
    global _game_manager
    return _game_manager


def set_game_manager(mgr: Any) -> None:
    global _game_manager
    _game_manager = mgr


def register_routes(app: Flask) -> None:
    """注册所有 API 路由。"""

    @app.route("/")
    def index():
        """主页 —— 扑克牌桌。"""
        return render_template("index.html")

    @app.route("/api/game/state")
    def game_state():
        """获取当前游戏状态。"""
        mgr = get_game_manager()
        if mgr is None or mgr.game is None:
            return jsonify({"error": "没有活跃的游戏"}), 404
        return jsonify(mgr.game.to_dict())

    @app.route("/api/game/new", methods=["POST"])
    def new_game():
        """创建新游戏。"""
        mgr = get_game_manager()
        if mgr is None:
            return jsonify({"error": "服务器未就绪"}), 500

        data = request.get_json() or {}
        player_name = data.get("player_name", "Player")
        bot_configs = data.get("bots", [
            {"style": "TAG", "name": "Alice"},
            {"style": "LAG", "name": "Bob"},
            {"style": "NIT", "name": "Charlie"},
            {"style": "CALLING_STATION", "name": "Diana"},
            {"style": "MANIAC", "name": "Eve"},
        ])
        starting_chips = data.get("starting_chips", 1000)
        small_blind = data.get("small_blind", 5)
        big_blind = data.get("big_blind", 10)
        ante = data.get("ante", 0)
        betting_structure = data.get("betting_structure", "no_limit")

        mgr.create_game(
            player_name=player_name,
            bot_configs=bot_configs,
            starting_chips=starting_chips,
            small_blind=small_blind,
            big_blind=big_blind,
            ante=ante,
            betting_structure=betting_structure,
        )

        return jsonify({"status": "ok", "message": "游戏已创建"})

    @app.route("/api/game/action", methods=["POST"])
    def player_action():
        """处理玩家动作。"""
        mgr = get_game_manager()
        if mgr is None or mgr.game is None:
            return jsonify({"error": "没有活跃的游戏"}), 404

        data = request.get_json() or {}
        action_type = data.get("action")
        amount = data.get("amount", 0)

        from src.utils.constants import ActionType
        action_map = {
            "fold": ActionType.FOLD,
            "check": ActionType.CHECK,
            "call": ActionType.CALL,
            "bet": ActionType.BET,
            "raise": ActionType.RAISE,
        }

        if action_type not in action_map:
            return jsonify({"error": f"无效动作: {action_type}"}), 400

        mgr.handle_human_action(action_map[action_type], amount)
        return jsonify({"status": "ok"})

    @app.route("/api/game/history")
    def game_history():
        """获取牌局历史。"""
        mgr = get_game_manager()
        if mgr is None:
            return jsonify({"error": "没有活跃的游戏"}), 404
        return jsonify(mgr.get_history())

    @app.route("/api/game/analysis")
    def game_analysis():
        """获取分析数据。"""
        mgr = get_game_manager()
        if mgr is None or mgr.reporter is None:
            return jsonify({"error": "没有分析数据"}), 404
        return jsonify(mgr.reporter.get_summary())

    @app.route("/api/bots/styles")
    def bot_styles():
        """列出所有可用的机器人风格。"""
        from src.ai.bots import BotFactory
        profiles = BotFactory.list_styles()
        return jsonify([
            {
                "style": p.style.value,
                "display_name": p.display_name,
                "description": p.description,
                "aggression": p.aggression,
                "bluff_frequency": p.bluff_frequency,
            }
            for p in profiles
        ])
