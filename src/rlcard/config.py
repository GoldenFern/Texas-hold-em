"""RLCard configuration — agent type, model path, training hyperparameters.

加载顺序：环境变量 THP_RLCARD_MODEL_PATH > config/rlcard_config.json > 代码默认值。
bot_configs[].rlcard_config 字典可覆盖任意字段。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass
class TrainingHyperparams:
    """RL 训练超参数桩（Phase B 接入训练脚本时使用）。"""

    learning_rate: float = 1e-4
    batch_size: int = 128
    buffer_size: int = 100_000
    train_every: int = 64
    update_target_every: int = 1000


@dataclass
class RLCardConfig:
    """RLCard Bot 配置。

    Attributes:
        agent_type: "random"（Phase A）| "dqn" | "nfsp"（Phase B+）。
        model_path: 训练好的策略工件路径（None 则使用 RandomAgent）。
        effective_stack_depth: 训练参考有效深度（起始筹码 / BB）。
        hyperparameters: 训练超参数桩。
    """

    agent_type: str = "random"
    model_path: Optional[str] = None
    effective_stack_depth: int = 100
    hyperparameters: TrainingHyperparams = field(default_factory=TrainingHyperparams)


def _find_project_root() -> Path:
    """查找项目根目录（包含 src/ 的目录）。"""
    current = Path(__file__).resolve().parent
    for _ in range(5):
        if (current / "src").is_dir():
            return current
        current = current.parent
    return Path.cwd()


def _load_json(path: str) -> Dict[str, Any]:
    """加载 JSON 文件，文件不存在或解析失败返回 {}。"""
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


_cached_config: Optional[RLCardConfig] = None


def _parse_json_config(json_cfg: Dict[str, Any]) -> RLCardConfig:
    """从已解析的 JSON 字典构建 RLCardConfig。"""
    agent_type = json_cfg.get("agent_type", "random")
    model_path: Optional[str] = (
        os.environ.get("THP_RLCARD_MODEL_PATH") or json_cfg.get("model_path") or None
    )

    training = json_cfg.get("training", {})
    effective_stack_depth = int(training.get("effective_stack_depth", 100))
    hp_dict = training.get("hyperparameters", {})

    hyperparams = TrainingHyperparams(
        learning_rate=float(hp_dict.get("learning_rate", 1e-4)),
        batch_size=int(hp_dict.get("batch_size", 128)),
        buffer_size=int(hp_dict.get("buffer_size", 100_000)),
        train_every=int(hp_dict.get("train_every", 64)),
        update_target_every=int(hp_dict.get("update_target_every", 1000)),
    )

    return RLCardConfig(
        agent_type=agent_type,
        model_path=model_path,
        effective_stack_depth=effective_stack_depth,
        hyperparameters=hyperparams,
    )


_HP_KEYS = ("learning_rate", "batch_size", "buffer_size", "train_every", "update_target_every")


def _apply_bot_override(config: RLCardConfig, override: Dict[str, Any]) -> None:
    """将 bot_override 字典应用到 RLCardConfig（原地修改）。"""
    if "agent_type" in override:
        config.agent_type = override["agent_type"]
    if "model_path" in override:
        config.model_path = override["model_path"]
    if "effective_stack_depth" in override:
        config.effective_stack_depth = int(override["effective_stack_depth"])

    hp_override = override.get("hyperparameters")
    if not isinstance(hp_override, dict):
        return
    hp = config.hyperparameters
    for key in _HP_KEYS:
        if key in hp_override:
            setattr(hp, key, type(getattr(hp, key))(hp_override[key]))


def load_rlcard_config(
    config_path: Optional[str] = None,
    bot_override: Optional[Dict[str, Any]] = None,
) -> RLCardConfig:
    """加载 RLCard 配置。

    优先级（从低到高）：
        1. config/rlcard_config.json
        2. 环境变量 THP_RLCARD_MODEL_PATH
        3. bot_override 字典（来自 bot_configs[].rlcard_config）

    使用默认路径且无 bot_override 时缓存基础配置以避免重复文件 I/O。
    """
    global _cached_config

    if bot_override is None and config_path is None and _cached_config is not None:
        return _cached_config

    project_root = _find_project_root()
    if config_path is None:
        config_path = str(project_root / "config" / "rlcard_config.json")

    config = _parse_json_config(_load_json(config_path))

    if bot_override:
        _apply_bot_override(config, bot_override)
    elif config_path is None or config_path == str(project_root / "config" / "rlcard_config.json"):
        _cached_config = config

    return config
