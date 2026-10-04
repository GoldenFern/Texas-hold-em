"""Flask 应用工厂。"""

from __future__ import annotations

import os
import secrets
from typing import List, Optional

from flask import Flask

from src.server.routes import register_routes
from src.server.events import register_events


def create_app(extra_origins: Optional[List[str]] = None) -> Flask:
    """创建并配置 Flask + SocketIO 应用。

    Args:
        extra_origins: 额外允许的浏览器 Origin(自定义端口/局域网访问时传入)。
    """
    static_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "static")
    )

    app = Flask(__name__, static_folder=static_dir)
    # 密钥: 环境变量优先,否则每次启动随机生成（本地单人无持久会话需求）
    app.config["SECRET_KEY"] = os.environ.get(
        "THP_SECRET_KEY", secrets.token_hex(32),
    )

    # 注册路由和事件
    register_routes(app)
    register_events(app, extra_origins=extra_origins)

    return app
