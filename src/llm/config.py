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
    timeout_seconds: float = 15.0
    max_retries: int = 2
    temperature: float = 0.1
    max_tokens: int = 200


@dataclass
class LLMConfig:
    """全局 LLM 配置。

    Attributes:
        primary: 主力后端配置。
        fallbacks: 降级链（按顺序尝试）。
        call_frequency: "every" | "critical" | "mixed"
        min_llm_decisions_per_hand: 每手牌最少 LLM 调用次数。
        context_window_hands: 上下文窗口（最近 N 手牌）。
        enable_prompt_caching: 是否启用 Prompt Caching (Anthropic)。
        enable_commentary: 是否启用模式 C（解说）。
        enable_advisor: 是否启用模式 B（顾问）。
    """

    primary: ProviderConfig = field(default_factory=lambda: ProviderConfig(
        provider="anthropic",
        model="claude-sonnet-4-20250514",
    ))
    fallbacks: List[ProviderConfig] = field(default_factory=lambda: [
        ProviderConfig(provider="anthropic", model="claude-3-haiku-20240307",
                       timeout_seconds=10.0),
    ])
    call_frequency: str = "every"
    min_llm_decisions_per_hand: int = 1
    context_window_hands: int = 5
    enable_prompt_caching: bool = True
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
    # API Key：优先 THP_LLM_API_KEY / JSON，再按提供商环境变量解析
    api_key = resolve_provider_api_key(
        provider,
        _env("API_KEY") or json_config.get("api_key", ""),
    )
    base_url = _env("BASE_URL") or json_config.get("base_url", "")
    if not base_url and provider in PROVIDER_PRESETS:
        base_url = PROVIDER_PRESETS[provider]["base_url"]
    timeout = float(_env("TIMEOUT") or json_config.get("timeout_seconds", 15.0))

    config.primary = ProviderConfig(
        provider=provider,
        model=model,
        api_key=api_key,
        base_url=base_url,
        timeout_seconds=timeout,
        temperature=float(_env("TEMPERATURE") or json_config.get("temperature", 0.1)),
        max_tokens=int(_env("MAX_TOKENS") or json_config.get("max_tokens", 200)),
    )

    # 降级链
    config.fallbacks = []
    fb_list = json_config.get("fallbacks", [])
    for fb in fb_list:
        fb_provider = fb.get("provider", "anthropic")
        fb_api_key = resolve_provider_api_key(
            fb_provider,
            fb.get("api_key", "") or _env("API_KEY"),
        )
        fb_base_url = fb.get("base_url", "")
        if not fb_base_url and fb_provider in PROVIDER_PRESETS:
            fb_base_url = PROVIDER_PRESETS[fb_provider]["base_url"]
        config.fallbacks.append(ProviderConfig(
            provider=fb_provider,
            model=fb.get("model", ""),
            api_key=fb_api_key,
            base_url=fb_base_url,
            timeout_seconds=float(fb.get("timeout_seconds", 10.0)),
        ))

    # 如果没有配置降级链，添加默认
    if not config.fallbacks:
        haiku_key = resolve_provider_api_key("anthropic")
        config.fallbacks.append(ProviderConfig(
            provider="anthropic",
            model="claude-3-haiku-20240307",
            api_key=haiku_key,
            timeout_seconds=10.0,
        ))

    # 策略参数
    strategy = json_config.get("strategy", {})
    config.call_frequency = _env("CALL_FREQUENCY") or strategy.get("call_frequency", "every")
    config.min_llm_decisions_per_hand = int(strategy.get("min_llm_decisions_per_hand", 1))
    config.context_window_hands = int(strategy.get("context_window_hands", 5))
    config.enable_prompt_caching = json_config.get("caching", {}).get("enabled", True)
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

    def _provider_to_dict(pc: ProviderConfig) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "provider": pc.provider,
            "model": pc.model,
            "timeout_seconds": pc.timeout_seconds,
        }
        if pc.api_key:
            d["api_key"] = pc.api_key
        if pc.base_url:
            d["base_url"] = pc.base_url
        return d

    json_config: Dict[str, Any] = {
        "provider": config.primary.provider,
        "model": config.primary.model,
        "timeout_seconds": config.primary.timeout_seconds,
        "temperature": config.primary.temperature,
        "max_tokens": config.primary.max_tokens,
        "fallbacks": [_provider_to_dict(fb) for fb in config.fallbacks],
        "strategy": {
            "call_frequency": config.call_frequency,
            "min_llm_decisions_per_hand": config.min_llm_decisions_per_hand,
            "context_window_hands": config.context_window_hands,
        },
        "caching": {
            "enabled": config.enable_prompt_caching,
            "prompt_caching": config.enable_prompt_caching,
        },
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
