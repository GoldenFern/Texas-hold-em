"""REST API 路由。"""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict

from flask import Flask, jsonify, request, send_file

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
        """主页 —— Vue 构建产物(static/dist)。"""
        import os
        dist_index = os.path.join(app.static_folder or "", "dist", "index.html")
        if not os.path.isfile(dist_index):
            return (
                "<h3>前端未构建</h3>"
                "<p>请先运行: <code>cd frontend && npm install && npm run build</code></p>",
                503,
            )
        return send_file(dist_index)

    @app.route("/api/game/state")
    def game_state():
        """获取当前游戏状态。"""
        mgr = get_game_manager()
        if mgr is None or mgr.game is None:
            return jsonify({"error": "没有活跃的游戏"}), 404
        state = mgr.game.to_dict()
        state["action_index"] = getattr(mgr, "_action_sequence", 0)
        return jsonify(state)

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
        bots_info = [
            {
                "name": name,
                "type": "LLM" if isinstance(bot, LLMBot) else "Rule",
                "repr": repr(bot),
            }
            for name, bot in mgr.bots.items()
        ]
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
        """保存 LLM 配置。

        api_key 语义: "***" = 保留现有值; "" = 清除; 其他 = 更新。
        base_url 仅接受各 Provider 官方预设或本地地址（防 SSRF /
        密钥外传到任意端点）。
        """
        from src.llm.config import (
            LLMConfig, ProviderConfig, save_config, load_config,
            is_allowed_base_url,
        )
        data = request.get_json() or {}

        primary_data = data.get("primary", {})
        raw_key = primary_data.get("api_key", "")
        if raw_key == "***":
            actual_key = load_config().primary.api_key  # 未修改,保留
        else:
            actual_key = raw_key  # 含空串 = 显式清除

        base_url = primary_data.get("base_url", "")
        if not is_allowed_base_url(base_url):
            return jsonify({
                "status": "error",
                "message": f"base_url 不在允许列表中: {base_url}",
            }), 400

        primary = ProviderConfig(
            provider=primary_data.get("provider", "deepseek"),
            model=primary_data.get("model", "deepseek-v4-pro"),
            api_key=actual_key,
            base_url=base_url,
            timeout_seconds=float(primary_data.get("timeout_seconds", 60.0)),
            temperature=float(primary_data.get("temperature", 0.5)),
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

    @app.route("/api/capabilities")
    def capabilities():
        """上报可选能力是否可用。"""
        from src.rlcard import is_available as rlcard_available
        import importlib.util as _util
        llm_available = _util.find_spec("anthropic") is not None or _util.find_spec("openai") is not None
        return jsonify({
            "rlcard": rlcard_available(),
            "llm": llm_available,
        })
