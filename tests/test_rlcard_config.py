"""RLCard 配置加载测试 — config loader + env override + bot override。

所有测试不依赖真实模型文件或 rlcard 包。
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from src.rlcard.config import (
    RLCardConfig,
    TrainingHyperparams,
    _load_json,
    load_rlcard_config,
)


# ================================================================
# TrainingHyperparams 测试
# ================================================================

class TestTrainingHyperparams:
    """TrainingHyperparams 默认值测试。"""

    def test_defaults(self) -> None:
        hp = TrainingHyperparams()
        assert hp.learning_rate == 1e-4
        assert hp.batch_size == 128
        assert hp.buffer_size == 100_000
        assert hp.train_every == 64
        assert hp.update_target_every == 1000

    def test_custom_values(self) -> None:
        hp = TrainingHyperparams(
            learning_rate=5e-4,
            batch_size=256,
            buffer_size=200_000,
            train_every=32,
            update_target_every=500,
        )
        assert hp.learning_rate == 5e-4
        assert hp.batch_size == 256
        assert hp.buffer_size == 200_000
        assert hp.train_every == 32
        assert hp.update_target_every == 500


# ================================================================
# RLCardConfig 默认值测试
# ================================================================

class TestRLCardConfigDefaults:
    """RLCardConfig 默认值测试。"""

    def test_default_config(self) -> None:
        cfg = RLCardConfig()
        assert cfg.agent_type == "random"
        assert cfg.model_path is None
        assert cfg.effective_stack_depth == 100
        assert isinstance(cfg.hyperparameters, TrainingHyperparams)
        assert cfg.hyperparameters.learning_rate == 1e-4

    def test_custom_config(self) -> None:
        hp = TrainingHyperparams(learning_rate=3e-4)
        cfg = RLCardConfig(
            agent_type="dqn",
            model_path="models/rlcard/test.pth",
            effective_stack_depth=200,
            hyperparameters=hp,
        )
        assert cfg.agent_type == "dqn"
        assert cfg.model_path == "models/rlcard/test.pth"
        assert cfg.effective_stack_depth == 200
        assert cfg.hyperparameters.learning_rate == 3e-4


# ================================================================
# _load_json 辅助函数测试
# ================================================================

class TestLoadJson:
    """_load_json 边界条件测试。"""

    def test_nonexistent_file_returns_empty(self) -> None:
        result = _load_json("/nonexistent/path/rlcard_config.json")
        assert result == {}

    def test_valid_json(self) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8",
        ) as f:
            json.dump({"agent_type": "dqn", "model_path": "test.pth"}, f)
            tmp_path = f.name

        try:
            result = _load_json(tmp_path)
            assert result["agent_type"] == "dqn"
            assert result["model_path"] == "test.pth"
        finally:
            os.unlink(tmp_path)

    def test_invalid_json_returns_empty(self) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8",
        ) as f:
            f.write("not valid json {{{")
            tmp_path = f.name

        try:
            result = _load_json(tmp_path)
            assert result == {}
        finally:
            os.unlink(tmp_path)


# ================================================================
# load_rlcard_config 核心测试
# ================================================================

class TestLoadRlcardConfig:
    """load_rlcard_config 集成测试。"""

    def _write_config(self, data: dict) -> str:
        """写入临时配置文件，返回路径。"""
        f = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8",
        )
        json.dump(data, f)
        f.close()
        return f.name

    def test_loads_defaults_when_no_config_file(self) -> None:
        """无配置文件时返回默认值。"""
        cfg = load_rlcard_config(config_path="/nonexistent/path.json")
        assert cfg.agent_type == "random"
        assert cfg.model_path is None
        assert cfg.effective_stack_depth == 100

    def test_loads_from_json_file(self) -> None:
        """从 JSON 文件加载配置。"""
        path = self._write_config({
            "agent_type": "dqn",
            "model_path": "models/rlcard/my_model.pth",
            "training": {
                "effective_stack_depth": 200,
                "hyperparameters": {
                    "learning_rate": 5e-4,
                    "batch_size": 256,
                },
            },
        })
        try:
            cfg = load_rlcard_config(config_path=path)
            assert cfg.agent_type == "dqn"
            assert cfg.model_path == "models/rlcard/my_model.pth"
            assert cfg.effective_stack_depth == 200
            assert cfg.hyperparameters.learning_rate == 5e-4
            assert cfg.hyperparameters.batch_size == 256
            # 未指定的 HP 应使用默认值
            assert cfg.hyperparameters.buffer_size == 100_000
            assert cfg.hyperparameters.train_every == 64
        finally:
            os.unlink(path)

    def test_env_var_overrides_model_path(self, monkeypatch) -> None:
        """THP_RLCARD_MODEL_PATH 环境变量覆盖 JSON 中的 model_path。"""
        monkeypatch.setenv("THP_RLCARD_MODEL_PATH", "/env/model.pth")

        path = self._write_config({
            "agent_type": "random",
            "model_path": "models/rlcard/json_model.pth",
        })
        try:
            cfg = load_rlcard_config(config_path=path)
            assert cfg.model_path == "/env/model.pth"
        finally:
            os.unlink(path)

    def test_env_var_sets_model_path_when_json_null(self, monkeypatch) -> None:
        """JSON 中 model_path 为 null 时，env var 可以设置。"""
        monkeypatch.setenv("THP_RLCARD_MODEL_PATH", "models/rlcard/env_only.pth")

        path = self._write_config({
            "agent_type": "random",
            "model_path": None,
        })
        try:
            cfg = load_rlcard_config(config_path=path)
            assert cfg.model_path == "models/rlcard/env_only.pth"
        finally:
            os.unlink(path)

    def test_env_var_not_set_uses_json(self) -> None:
        """无 env var 时使用 JSON 中的值。"""
        # 确保环境变量未设置
        if "THP_RLCARD_MODEL_PATH" in os.environ:
            del os.environ["THP_RLCARD_MODEL_PATH"]

        path = self._write_config({
            "agent_type": "random",
            "model_path": "models/rlcard/json_model.pth",
        })
        try:
            cfg = load_rlcard_config(config_path=path)
            assert cfg.model_path == "models/rlcard/json_model.pth"
        finally:
            os.unlink(path)

    def test_bot_override_agent_type(self) -> None:
        """bot_override 覆盖 agent_type。"""
        cfg = load_rlcard_config(
            config_path="/nonexistent/path.json",
            bot_override={"agent_type": "nfsp"},
        )
        assert cfg.agent_type == "nfsp"

    def test_bot_override_model_path(self) -> None:
        """bot_override 覆盖 model_path。"""
        cfg = load_rlcard_config(
            config_path="/nonexistent/path.json",
            bot_override={"model_path": "models/rlcard/bot_specific.pth"},
        )
        assert cfg.model_path == "models/rlcard/bot_specific.pth"

    def test_bot_override_effective_stack_depth(self) -> None:
        """bot_override 覆盖 effective_stack_depth。"""
        cfg = load_rlcard_config(
            config_path="/nonexistent/path.json",
            bot_override={"effective_stack_depth": 400},
        )
        assert cfg.effective_stack_depth == 400

    def test_bot_override_hyperparameters(self) -> None:
        """bot_override 覆盖超参数。"""
        cfg = load_rlcard_config(
            config_path="/nonexistent/path.json",
            bot_override={
                "hyperparameters": {
                    "learning_rate": 1e-3,
                    "batch_size": 512,
                },
            },
        )
        assert cfg.hyperparameters.learning_rate == 1e-3
        assert cfg.hyperparameters.batch_size == 512
        # 未覆盖的 HP 保持默认
        assert cfg.hyperparameters.buffer_size == 100_000
        assert cfg.hyperparameters.train_every == 64

    def test_bot_override_overrides_json(self) -> None:
        """bot_override 优先级高于 JSON 文件。"""
        path = self._write_config({
            "agent_type": "random",
            "model_path": "models/rlcard/from_json.pth",
            "training": {
                "effective_stack_depth": 100,
                "hyperparameters": {"learning_rate": 1e-4},
            },
        })
        try:
            cfg = load_rlcard_config(
                config_path=path,
                bot_override={
                    "agent_type": "dqn",
                    "model_path": "models/rlcard/from_bot.pth",
                    "effective_stack_depth": 300,
                    "hyperparameters": {"learning_rate": 1e-3},
                },
            )
            assert cfg.agent_type == "dqn"
            assert cfg.model_path == "models/rlcard/from_bot.pth"
            assert cfg.effective_stack_depth == 300
            assert cfg.hyperparameters.learning_rate == 1e-3
        finally:
            os.unlink(path)

    def test_bot_override_partial_hyperparameters(self) -> None:
        """bot_override 可以只覆盖部分超参数。"""
        path = self._write_config({
            "training": {
                "hyperparameters": {
                    "learning_rate": 5e-4,
                    "batch_size": 256,
                    "buffer_size": 200_000,
                },
            },
        })
        try:
            cfg = load_rlcard_config(
                config_path=path,
                bot_override={
                    "hyperparameters": {
                        "learning_rate": 1e-3,
                    },
                },
            )
            # 覆盖的生效
            assert cfg.hyperparameters.learning_rate == 1e-3
            # 未覆盖的来自 JSON
            assert cfg.hyperparameters.batch_size == 256
            assert cfg.hyperparameters.buffer_size == 200_000
            # JSON 中未指定的来自默认值
            assert cfg.hyperparameters.train_every == 64
        finally:
            os.unlink(path)

    def test_empty_bot_override_noop(self) -> None:
        """空 bot_override 不改变任何配置。"""
        cfg1 = load_rlcard_config(config_path="/nonexistent/path.json")
        cfg2 = load_rlcard_config(
            config_path="/nonexistent/path.json",
            bot_override={},
        )
        assert cfg1.agent_type == cfg2.agent_type
        assert cfg1.model_path == cfg2.model_path
        assert cfg1.effective_stack_depth == cfg2.effective_stack_depth

    def test_bot_override_handles_non_dict_hyperparams(self) -> None:
        """bot_override.hyperparameters 非 dict 时不应崩溃。"""
        cfg = load_rlcard_config(
            config_path="/nonexistent/path.json",
            bot_override={"hyperparameters": "not_a_dict"},
        )
        # 应保持默认值
        assert cfg.hyperparameters.learning_rate == 1e-4

    def test_partial_json_with_missing_sections(self) -> None:
        """JSON 文件只有部分字段时，其余使用默认值。"""
        path = self._write_config({"agent_type": "nfsp"})
        try:
            cfg = load_rlcard_config(config_path=path)
            assert cfg.agent_type == "nfsp"
            assert cfg.model_path is None
            assert cfg.effective_stack_depth == 100
            assert cfg.hyperparameters.learning_rate == 1e-4
        finally:
            os.unlink(path)


# ================================================================
# 实际配置文件存在性测试
# ================================================================

class TestActualConfigFile:
    """验证项目中实际的 config/rlcard_config.json 可正确加载。"""

    def test_project_config_file_loads(self) -> None:
        """config/rlcard_config.json 存在且可解析。"""
        cfg = load_rlcard_config()
        assert cfg.agent_type in ("random", "dqn", "dmc", "nfsp")
        assert cfg.effective_stack_depth > 0
        assert cfg.hyperparameters.learning_rate > 0
        assert cfg.hyperparameters.batch_size > 0
        assert cfg.hyperparameters.buffer_size > 0
