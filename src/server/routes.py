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
            {"style": "TAG", "name": "曹操"},
            {"style": "LAG", "name": "刘备"},
            {"style": "NIT", "name": "孙权"},
            {"style": "CALLING_STATION", "name": "诸葛"},
            {"style": "MANIAC", "name": "吕布"},
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

    @app.route("/api/game/replay")
    def game_replay():
        """获取指定手牌的完整回放数据。

        Query params:
            hand_id: 手牌 ID（可选，默认返回最近一手）
        """
        mgr = get_game_manager()
        if mgr is None:
            return jsonify({"error": "服务器未就绪"}), 500
        hand_id = request.args.get("hand_id", type=int)
        replay = mgr.get_replay(hand_id)
        if replay is None:
            return jsonify({"error": "没有可回放的牌局"}), 404
        return jsonify(replay)

    @app.route("/api/game/replays")
    def game_replays():
        """获取所有可回放手牌的摘要列表。"""
        mgr = get_game_manager()
        if mgr is None:
            return jsonify({"error": "服务器未就绪"}), 500
        return jsonify(mgr.get_replay_list())

    @app.route("/api/config/llm", methods=["GET"])
    def get_llm_config():
        """获取当前 LLM 配置。"""
        from src.llm.config import load_config, ProviderConfig
        cfg = load_config()

        def _pc(pc: ProviderConfig) -> dict:
            return {
                "provider": pc.provider,
                "model": pc.model,
                "api_key": "***" if pc.api_key else "",
                "base_url": pc.base_url,
                "timeout_seconds": pc.timeout_seconds,
                "temperature": pc.temperature,
                "max_tokens": pc.max_tokens,
            }

        return jsonify({
            "primary": _pc(cfg.primary),
            "fallbacks": [_pc(fb) for fb in cfg.fallbacks],
            "call_frequency": cfg.call_frequency,
            "min_llm_decisions_per_hand": cfg.min_llm_decisions_per_hand,
            "context_window_hands": cfg.context_window_hands,
            "enable_prompt_caching": cfg.enable_prompt_caching,
            "enable_commentary": cfg.enable_commentary,
            "enable_advisor": cfg.enable_advisor,
        })

    @app.route("/api/config/llm", methods=["POST"])
    def set_llm_config():
        """保存 LLM 配置。"""
        from src.llm.config import LLMConfig, ProviderConfig, save_config
        data = request.get_json() or {}

        primary_data = data.get("primary", {})
        raw_key = primary_data.get("api_key", "")
        # "***" 表示未修改，不覆盖已有 Key
        actual_key = "" if raw_key == "***" else raw_key
        primary = ProviderConfig(
            provider=primary_data.get("provider", "anthropic"),
            model=primary_data.get("model", "claude-sonnet-4-20250514"),
            api_key=actual_key,
            base_url=primary_data.get("base_url", ""),
            timeout_seconds=float(primary_data.get("timeout_seconds", 15.0)),
            temperature=float(primary_data.get("temperature", 0.1)),
            max_tokens=int(primary_data.get("max_tokens", 200)),
        )

        fallbacks = []
        for fb_data in data.get("fallbacks", []):
            fallbacks.append(ProviderConfig(
                provider=fb_data.get("provider", "anthropic"),
                model=fb_data.get("model", ""),
                timeout_seconds=float(fb_data.get("timeout_seconds", 10.0)),
                base_url=fb_data.get("base_url", ""),
            ))

        cfg = LLMConfig(
            primary=primary,
            fallbacks=fallbacks,
            call_frequency=data.get("call_frequency", "every"),
            min_llm_decisions_per_hand=int(data.get("min_llm_decisions_per_hand", 1)),
            context_window_hands=int(data.get("context_window_hands", 5)),
            enable_prompt_caching=bool(data.get("enable_prompt_caching", True)),
            enable_commentary=bool(data.get("enable_commentary", False)),
            enable_advisor=bool(data.get("enable_advisor", False)),
        )

        save_config(cfg)
        return jsonify({"status": "ok", "message": "LLM 配置已保存"})

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
                "temperature": p.temperature,
            }
            for p in profiles
        ])
