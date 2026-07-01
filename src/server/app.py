"""Flask 应用工厂。"""

from __future__ import annotations

from flask import Flask

from src.server.routes import register_routes
from src.server.events import register_events


def create_app() -> Flask:
    """创建并配置 Flask + SocketIO 应用。"""
    import os

    template_dir = os.path.join(os.path.dirname(__file__), "..", "..", "templates")
    static_dir = os.path.join(os.path.dirname(__file__), "..", "..", "static")
    template_dir = os.path.abspath(template_dir)
    static_dir = os.path.abspath(static_dir)

    app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
    app.config["SECRET_KEY"] = "texas-hold-em-secret-key-2024"

    # 注册路由和事件
    register_routes(app)
    register_events(app)

    return app
