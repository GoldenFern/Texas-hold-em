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
    provider = _env("PROVIDER") or json_config.get("provider", "anthropic")
    model = _env("MODEL") or json_config.get("model", "claude-sonnet-4-20250514")
    api_key = _env("API_KEY") or json_config.get("api_key", "") or os.environ.get("ANTHROPIC_API_KEY", "")
    base_url = _env("BASE_URL") or json_config.get("base_url", "")
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
        fb_api_key = ""
        if fb_provider == "anthropic":
            fb_api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        elif fb_provider == "openai":
            fb_api_key = os.environ.get("OPENAI_API_KEY", "")
        config.fallbacks.append(ProviderConfig(
            provider=fb_provider,
            model=fb.get("model", ""),
            api_key=fb_api_key,
            base_url=fb.get("base_url", ""),
            timeout_seconds=float(fb.get("timeout_seconds", 10.0)),
        ))

    # 如果没有配置降级链，添加默认
    if not config.fallbacks:
        haiku_key = os.environ.get("ANTHROPIC_API_KEY", "")
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
