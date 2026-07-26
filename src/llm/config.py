"""LLM configuration — model selection, API keys, rate limits, costs.

加载顺序：环境变量 > config/llm_config.json > 代码默认值。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class ProviderConfig:
    """单个 LLM 后端的配置。"""

    provider: str  # "anthropic", "openai", "ollama"
    model: str     # 模型标识符
    api_key: str = ""
    base_url: str = ""  # 对 Ollama / 自定义端点有用
    timeout_seconds: float = 60.0
    max_retries: int = 2
    temperature: float = 0.5
    max_tokens: int = 100000
    reasoning_effort: str = ""  # "" = disabled, "high", "max"


@dataclass
class LLMConfig:
    """全局 LLM 配置（精简版）。

    Attributes:
        primary: 主力后端配置。
        enable_commentary: 是否启用解说模式。
        enable_advisor: 是否启用顾问模式。
    """

    primary: ProviderConfig = field(default_factory=lambda: ProviderConfig(
        provider="deepseek",
        model="deepseek-v4-pro",
    ))
    enable_commentary: bool = False
    enable_advisor: bool = False


PROVIDER_API_KEY_ENV: Dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "qwen": "DASHSCOPE_API_KEY",
    "glm": "GLM_API_KEY",
    "kimi": "MOONSHOT_API_KEY",
    "minimax": "MINIMAX_API_KEY",
    "volcengine": "ARK_API_KEY",
    "longcat": "LONGCAT_API_KEY",
}


def resolve_provider_api_key(provider: str, explicit_key: str = "") -> str:
    """按提供商解析 API Key（显式值 > 环境变量）。"""
    if explicit_key:
        return explicit_key
    env_var = PROVIDER_API_KEY_ENV.get(provider, "")
    if env_var:
        return os.environ.get(env_var, "")
    return ""


PROVIDER_PRESETS: Dict[str, Dict[str, Any]] = {
    "deepseek": {
        "display_name": "DeepSeek（深度求索）",
        "base_url": "https://api.deepseek.com",
        "models": ["deepseek-v4-pro", "deepseek-v4-flash", "deepseek-chat"],
        "api_key_env": "DEEPSEEK_API_KEY",
    },
    "qwen": {
        "display_name": "通义千问（阿里云）",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "models": ["qwen3-max", "qwen3-plus", "qwen3-turbo"],
        "api_key_env": "DASHSCOPE_API_KEY",
    },
    "glm": {
        "display_name": "智谱 GLM（智谱AI）",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "models": ["glm-5.2", "glm-5-turbo", "glm-5-flash"],
        "api_key_env": "GLM_API_KEY",
    },
    "kimi": {
        "display_name": "Kimi（月之暗面 Moonshot）",
        "base_url": "https://api.moonshot.cn",
        "models": ["kimi-k2.6", "kimi-k2-turbo"],
        "api_key_env": "MOONSHOT_API_KEY",
    },
    "minimax": {
        "display_name": "MiniMax（稀宇科技）",
        "base_url": "https://api.minimaxi.com/v1",
        "models": ["MiniMax-M3", "MiniMax-M2"],
        "api_key_env": "MINIMAX_API_KEY",
    },
    "volcengine": {
        "display_name": "火山引擎（字节跳动）",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "models": ["doubao-pro", "doubao-lite", "doubao-vision"],
        "api_key_env": "ARK_API_KEY",
    },
    "longcat": {
        "display_name": "LongCat（美团）",
        "base_url": "https://api.longcat.cn/v1",
        "models": ["longcat-pro", "longcat-flash"],
        "api_key_env": "LONGCAT_API_KEY",
    },
}


_EXTRA_ALLOWED_BASE_URLS = {
    "https://api.anthropic.com",
    "https://api.openai.com/v1",
    "https://api.openai.com",
}


def is_allowed_base_url(base_url: str) -> bool:
    """校验 base_url 是否允许（防 SSRF / 密钥外传到任意端点）。

    允许: 空串（使用 Provider 预设）、各 Provider 官方预设地址、
    Anthropic/OpenAI 官方地址、本机地址（Ollama 等本地部署）。
    """
    if not base_url:
        return True
    url = base_url.rstrip("/")
    presets = {p["base_url"].rstrip("/") for p in PROVIDER_PRESETS.values()}
    if url in presets or url in {u.rstrip("/") for u in _EXTRA_ALLOWED_BASE_URLS}:
        return True
    for prefix in ("http://127.0.0.1", "http://localhost",
                   "https://127.0.0.1", "https://localhost"):
        if url == prefix or url.startswith(prefix + ":") or url.startswith(prefix + "/"):
            return True
    return False


def _find_project_root() -> Path:
    """查找项目根目录（包含 src/ 的目录）。"""
    current = Path(__file__).resolve().parent
    for _ in range(5):
        if (current / "src").is_dir():
            return current
        current = current.parent
    return Path.cwd()


def load_config(config_path: Optional[str] = None) -> LLMConfig:
    """从 JSON 文件和环境变量加载 LLM 配置。

    Args:
        config_path: JSON 配置文件路径，默认查找 config/llm_config.json。

    Returns:
        LLMConfig 实例。
    """
    config = LLMConfig()

    # 1. 尝试加载 JSON 配置文件
    project_root = _find_project_root()
    if config_path is None:
        config_path = str(project_root / "config" / "llm_config.json")

    json_config: Dict[str, Any] = {}
    if os.path.isfile(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                json_config = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass

    # 2. 环境变量覆盖（优先级最高）
    env_prefix = "THP_LLM_"

    def _env(key: str, default: str = "") -> str:
        return os.environ.get(env_prefix + key, default)

    # 主力后端
    provider = _env("PROVIDER") or json_config.get("provider", "deepseek")
    model = _env("MODEL") or json_config.get("model", "deepseek-v4-pro")
    api_key = resolve_provider_api_key(
        provider,
        _env("API_KEY") or json_config.get("api_key", ""),
    )
    base_url = _env("BASE_URL") or json_config.get("base_url", "")
    if not base_url and provider in PROVIDER_PRESETS:
        base_url = PROVIDER_PRESETS[provider]["base_url"]
    timeout = float(_env("TIMEOUT") or json_config.get("timeout_seconds", 60.0))

    config.primary = ProviderConfig(
        provider=provider,
        model=model,
        api_key=api_key,
        base_url=base_url,
        timeout_seconds=timeout,
        temperature=float(_env("TEMPERATURE") or json_config.get("temperature", 0.5)),
        max_tokens=100000,  # 固定 100k
        reasoning_effort=_env("REASONING_EFFORT") or json_config.get("reasoning_effort", ""),
    )

    config.enable_commentary = json_config.get("commentary", {}).get("enabled", False)
    config.enable_advisor = json_config.get("advisor", {}).get("enabled", False)

    return config


def save_config(config: LLMConfig, config_path: Optional[str] = None) -> None:
    """将 LLM 配置保存为 JSON 文件。

    Args:
        config: 要保存的 LLMConfig 实例。
        config_path: 目标文件路径，默认保存到 config/llm_config.json。
    """
    project_root = _find_project_root()
    if config_path is None:
        config_path = str(project_root / "config" / "llm_config.json")

    json_config: Dict[str, Any] = {
        "provider": config.primary.provider,
        "model": config.primary.model,
        "timeout_seconds": config.primary.timeout_seconds,
        "temperature": config.primary.temperature,
        "reasoning_effort": config.primary.reasoning_effort,
        "commentary": {"enabled": config.enable_commentary},
        "advisor": {"enabled": config.enable_advisor},
    }
    if config.primary.api_key:
        json_config["api_key"] = config.primary.api_key
    if config.primary.base_url:
        json_config["base_url"] = config.primary.base_url

    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(json_config, f, indent=2, ensure_ascii=False)
