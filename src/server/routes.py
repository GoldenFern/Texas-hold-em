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
            {"style": "COOL", "name": "偏冷"},
            {"style": "WARM", "name": "偏热"},
            {"style": "COLD", "name": "极冷"},
            {"style": "HOT", "name": "炎热"},
            {"style": "CHAOS", "name": "混沌"},
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

    @app.route("/api/game/bots")
    def game_bots():
        """获取当前游戏中所有 Bot 的类型信息（调试用）。"""
        mgr = get_game_manager()
        if mgr is None or not mgr.bots:
            return jsonify({"bots": [], "message": "没有活跃的游戏"})
        from src.llm.llm_bot import LLMBot
        bots_info = []
        for name, bot in mgr.bots.items():
            is_llm = isinstance(bot, LLMBot)
            info = {
                "name": name,
                "type": "LLM" if is_llm else "Rule",
                "repr": repr(bot),
            }
            if is_llm:
                info["stats"] = bot.decision_stats
            bots_info.append(info)
        return jsonify({"bots": bots_info})

    @app.route("/api/game/llm_context")
    def llm_context():
        """获取最近一次 LLM 调用的完整上下文（调试面板用）。"""
        mgr = get_game_manager()
        if mgr is None:
            return jsonify({"status": "no_server", "system_prompt": "", "user_prompt": "", "raw_response": ""})
        ctx = mgr.get_llm_context()
        if ctx is None:
            # 没有 LLM 调用记录（尚未调用或没有 LLM Bot）
            return jsonify({"status": "no_context", "system_prompt": "", "user_prompt": "", "raw_response": ""})
        ctx["status"] = "ok"
        return jsonify(ctx)

    @app.route("/api/config/llm", methods=["GET"])
    def get_llm_config():
        """获取当前 LLM 配置。"""
        from src.llm.config import load_config, ProviderConfig
        cfg = load_config()

        return jsonify({
            "primary": {
                "provider": cfg.primary.provider,
                "model": cfg.primary.model,
                "api_key": "***" if cfg.primary.api_key else "",
                "base_url": cfg.primary.base_url,
                "timeout_seconds": cfg.primary.timeout_seconds,
                "temperature": cfg.primary.temperature,
                "reasoning_effort": cfg.primary.reasoning_effort or "disabled",
            },
            "enable_commentary": cfg.enable_commentary,
            "enable_advisor": cfg.enable_advisor,
        })

    @app.route("/api/config/llm", methods=["POST"])
    def set_llm_config():
        """保存 LLM 配置。"""
        from src.llm.config import LLMConfig, ProviderConfig, save_config, load_config
        data = request.get_json() or {}

        primary_data = data.get("primary", {})
        raw_key = primary_data.get("api_key", "")
        # 保护：掩码值 "***" 表示前端未修改密钥，保留已有值
        if raw_key == "***" or raw_key == "":
            existing = load_config()
            actual_key = existing.primary.api_key  # 保留现有密钥
        else:
            actual_key = raw_key
        primary = ProviderConfig(
            provider=primary_data.get("provider", "deepseek"),
            model=primary_data.get("model", "deepseek-v4-pro"),
            api_key=actual_key,
            base_url=primary_data.get("base_url", ""),
            timeout_seconds=float(primary_data.get("timeout_seconds", 60.0)),
            temperature=float(primary_data.get("temperature", 0.5)),
            max_tokens=100000,
            reasoning_effort=primary_data.get("reasoning_effort", ""),
        )

        cfg = LLMConfig(
            primary=primary,
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
