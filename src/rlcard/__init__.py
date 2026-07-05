"""RLCard 可选集成 —— 镜像适配器 + RLCardBot。

rlcard 是可选依赖；未安装时，核心游戏正常运行，但
BotFactory.create(BotStyle.RLCARD) 会抛出清晰的 ImportError。
"""

from __future__ import annotations

import importlib.util as _importlib_util

_RL_CARD_AVAILABLE = _importlib_util.find_spec("rlcard") is not None


def is_available() -> bool:
    """rlcard 包是否已安装。"""
    return _RL_CARD_AVAILABLE


if _RL_CARD_AVAILABLE:
    from src.rlcard.mirror_adapter import MirrorAdapter  # noqa: F401
    from src.rlcard.rlcard_bot import RLCardBot  # noqa: F401

__all__ = ["MirrorAdapter", "RLCardBot", "is_available"]
