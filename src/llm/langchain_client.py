"""基于 LangChain 的 LLM 客户端封装。

替代自建的 client.py，使用 LangChain 原生模型和 LCEL (LangChain Expression Language)
构建决策 Pipeline。

核心组件：
    - LCDecisionOutput: Pydantic Model 定义 LLM 输出结构
    - LCDecisionParser: 基于 PydanticOutputParser 的 JSON 解析器
    - create_chat_model(): 工厂函数，将 ProviderConfig 转为 LangChain ChatModel
    - build_decision_chain(): 构建 LCEL Chain（prompt | model | parser）
    - LCTrafficCallback: 流量日志回调处理器
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from typing import Any, Callable, Dict, List, Optional

from pydantic import BaseModel, Field

from src.llm.config import ProviderConfig

logger = logging.getLogger(__name__)
_TRAFFIC_LOGGER = logging.getLogger("src.llm.traffic")


class LLMError(Exception):
    """带类型的 LLM 调用错误。

    Attributes:
        kind: auth | rate_limit | timeout | parse | network | unknown。
        detail: 原始错误信息。
    """

    def __init__(self, kind: str, detail: str) -> None:
        super().__init__(f"[{kind}] {detail}")
        self.kind = kind
        self.detail = detail


def classify_llm_exception(e: Exception) -> str:
    """按异常内容归类错误类型（供 llm_status.error_type 使用）。"""
    name = type(e).__name__.lower()
    text = f"{name}: {e}".lower()
    if any(k in text for k in ("401", "unauthorized", "authentication",
                               "invalid api key", "api key", "forbidden", "403")):
        return "auth"
    if any(k in text for k in ("429", "rate limit", "ratelimit", "quota")):
        return "rate_limit"
    if any(k in text for k in ("timeout", "timed out")):
        return "timeout"
    if any(k in text for k in ("json", "parse", "validation", "pydantic")):
        return "parse"
    if any(k in text for k in ("connection", "network", "dns", "unreachable",
                               "ssl", "proxy")):
        return "network"
    return "unknown"


# ================================================================
# Pydantic 输出模型
# ================================================================


class LCDecisionAnalysis(BaseModel):
    """LLM 决策分析（CoT 思维链）。"""

    hand_assessment: str = Field(default="", description="手牌强度与牌面连接评估")
    pot_odds_analysis: str = Field(default="", description="底池赔率与胜率对比分析")
    opponent_read: str = Field(default="", description="对手范围与行为解读")
    plan: str = Field(default="", description="后续几条街的策略计划")


class LCDecisionOutput(BaseModel):
    """LLM 扑克决策输出结构。

    对应 Prompt 中要求的 JSON 输出格式。
    """

    analysis: LCDecisionAnalysis = Field(default_factory=LCDecisionAnalysis, description="思维链分析")
    action: str = Field(description="动作: FOLD / CHECK / CALL / BET / RAISE")
    amount: int = Field(default=0, description="下注/加注金额（仅 BET/RAISE 需要）")
    reasoning: str = Field(default="", description="一句话决策理由")


# ================================================================
# 流量日志回调
# ================================================================


def _is_traffic_logging_enabled() -> bool:
    """是否启用 LLM 流量日志。"""
    val = os.environ.get("THP_LLM_LOG_TRAFFIC", "")
    return val.strip().lower() in ("1", "true", "yes", "on")


def _format_traffic_block(title: str, body: str) -> str:
    """格式化终端日志块。"""
    separator = "─" * 60
    return f"\n{separator}\n{title}\n{separator}\n{body}\n"


class LCTrafficCallback:
    """LangChain 流量日志回调。

    记录发往 LLM 的请求和收到的响应，格式与原 client.py 的日志兼容。
    可作为 LangChain BaseCallbackHandler 使用，也可手动调用。
    """

    def __init__(self) -> None:
        self._start_time: float = 0.0
        self._provider: str = ""
        self._model: str = ""

    def on_llm_start(self, provider: str, model: str, prompt_text: str) -> None:
        """LLM 调用开始时记录请求。"""
        self._start_time = time.perf_counter()
        self._provider = provider
        self._model = model

        if not _is_traffic_logging_enabled():
            return
        title = f"LLM Request → {provider} / {model}"
        # 截取前 2000 字符防止日志过长
        body = prompt_text[:2000]
        if len(prompt_text) > 2000:
            body += f"\n... (truncated, total {len(prompt_text)} chars)"
        _TRAFFIC_LOGGER.info("%s", _format_traffic_block(title, body))

    def on_llm_end(self, response_text: str, input_tokens: int = 0, output_tokens: int = 0) -> None:
        """LLM 调用完成时记录响应。"""
        latency = time.perf_counter() - self._start_time

        if not _is_traffic_logging_enabled():
            return
        token_line = f"Tokens: in={input_tokens} out={output_tokens}"
        body = f"{response_text[:1000]}\n\n{token_line}"
        title = f"LLM Response ← {self._provider} / {self._model} ({latency:.2f}s)"
        _TRAFFIC_LOGGER.info("%s", _format_traffic_block(title, body))


# 全局流量回调实例
_traffic_callback = LCTrafficCallback()


def configure_llm_traffic_logging(enabled: bool = True) -> None:
    """配置 LLM 流量日志输出到终端。"""
    if enabled:
        os.environ["THP_LLM_LOG_TRAFFIC"] = "1"
    else:
        os.environ.pop("THP_LLM_LOG_TRAFFIC", None)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(message)s"))
    _TRAFFIC_LOGGER.setLevel(logging.INFO if enabled else logging.WARNING)
    _TRAFFIC_LOGGER.handlers.clear()
    if enabled:
        _TRAFFIC_LOGGER.addHandler(handler)
    _TRAFFIC_LOGGER.propagate = False


# ================================================================
# ChatModel 工厂
# ================================================================


def create_chat_model(config: ProviderConfig) -> Any:
    """根据 ProviderConfig 创建 LangChain ChatModel 实例。

    支持的 provider:
        - anthropic → ChatAnthropic
        - openai / deepseek / qwen / glm / kimi / minimax / volcengine / longcat → ChatOpenAI
        - ollama → ChatOllama
        - mock → FakeListChatModel

    Args:
        config: LLM 提供商配置。

    Returns:
        LangChain BaseChatModel 实例。

    Raises:
        ValueError: 未知的 provider。
        ImportError: 对应的 LangChain 包未安装。
    """
    provider = config.provider.lower()

    if provider == "anthropic":
        try:
            from langchain_anthropic import ChatAnthropic
        except ImportError:
            raise ImportError(
                "langchain-anthropic 未安装，请运行: pip install langchain-anthropic"
            )
        kwargs: Dict[str, Any] = {
            "model": config.model,
            "api_key": config.api_key or None,
            "temperature": config.temperature,
            "max_tokens": config.max_tokens,
            "timeout": config.timeout_seconds,
            "max_retries": config.max_retries,
        }
        if config.base_url:
            kwargs["base_url"] = config.base_url
        return ChatAnthropic(**kwargs)

    if provider == "ollama":
        try:
            from langchain_ollama import ChatOllama
        except ImportError:
            raise ImportError(
                "langchain-ollama 未安装，请运行: pip install langchain-ollama"
            )
        base_url = config.base_url or "http://localhost:11434"
        return ChatOllama(
            model=config.model,
            base_url=base_url,
            temperature=config.temperature,
            num_predict=config.max_tokens,
        )

    if provider == "mock":
        from langchain_core.language_models import FakeListChatModel
        return FakeListChatModel(
            responses=['{"action": "CALL", "amount": 0, "reasoning": "mock"}'],
        )

    # 所有 OpenAI 兼容的 provider
    openai_providers = {
        "openai", "deepseek", "qwen", "glm", "kimi", "minimax", "volcengine", "longcat",
    }
    if provider in openai_providers:
        try:
            from langchain_openai import ChatOpenAI
        except ImportError:
            raise ImportError(
                "langchain-openai 未安装，请运行: pip install langchain-openai"
            )
        kwargs: Dict[str, Any] = {
            "model": config.model,
            "api_key": config.api_key or "placeholder",
            "max_tokens": config.max_tokens,
            "timeout": config.timeout_seconds,
            "max_retries": config.max_retries,
        }
        if config.base_url:
            kwargs["base_url"] = config.base_url

        # 思考模式（DeepSeek）：reasoning_effort 和 extra_body 直接传入
        effort = getattr(config, "reasoning_effort", "") or ""
        if effort and effort != "disabled":
            kwargs["reasoning_effort"] = effort
            kwargs["extra_body"] = {"thinking": {"type": "enabled"}}
            logger.info(
                "思考模式已启用(effort=%s), temperature=%s 被忽略",
                effort, config.temperature,
            )
        else:
            kwargs["temperature"] = config.temperature

        return ChatOpenAI(**kwargs)

    raise ValueError(
        f"未知的 LLM 提供商: {config.provider}。"
        f"支持: anthropic, openai, deepseek, qwen, glm, kimi, minimax, volcengine, longcat, ollama, mock"
    )


def build_fake_chat_model(responses: List[str]) -> Any:
    """创建 FakeListChatModel（用于测试）。

    Args:
        responses: 预设的响应列表，按调用顺序返回。

    Returns:
        FakeListChatModel 实例。
    """
    from langchain_core.language_models import FakeListChatModel
    return FakeListChatModel(responses=responses)


class MockClient:
    """向后兼容的 Mock 客户端（替代原 client.py 的 MockClient）。

    内部使用 FakeListChatModel，提供与原 MockClient 相同的接口，
    确保现有测试代码无需大改。

    典型用法:
        mock = MockClient(responses=['{"action": "CALL", "amount": 0}'])
        response = mock.generate("prompt", "system")
    """

    def __init__(self, responses: Optional[List[str]] = None) -> None:
        self._responses = responses or ['{"action": "CALL", "amount": 0, "reasoning": "mock"}']
        self._idx: int = 0
        self._call_log: List[Dict[str, str]] = []
        self.config = ProviderConfig(provider="mock", model="mock")

        # 调用统计（与原 LLMClient 兼容）
        self._call_count: int = 0
        self._total_latency: float = 0.0
        self._total_input_tokens: int = 0
        self._total_output_tokens: int = 0

    def add_response(self, response_json: str) -> None:
        """追加一个预设响应。"""
        self._responses.append(response_json)
        self._idx = 0

    def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        timeout: Optional[float] = None,
    ) -> LCResponse:
        """返回预设响应（与原 LLMClient.generate 接口兼容）。"""
        self._call_log.append({"prompt": prompt, "system": system_prompt})
        text = self._responses[self._idx % len(self._responses)]
        self._idx += 1

        self._call_count += 1
        self._total_latency += 0.01
        self._total_input_tokens += 100
        self._total_output_tokens += 20

        return LCResponse(
            text=text,
            model="mock",
            provider="mock",
            latency_seconds=0.01,
            input_tokens=100,
            output_tokens=20,
        )

    @property
    def call_log(self) -> List[Dict[str, str]]:
        return self._call_log

    @property
    def stats(self) -> Dict[str, Any]:
        """返回调用统计。"""
        return {
            "call_count": self._call_count,
            "total_latency": round(self._total_latency, 2),
            "avg_latency": round(self._total_latency / max(1, self._call_count), 2),
            "total_input_tokens": self._total_input_tokens,
            "total_output_tokens": self._total_output_tokens,
        }


# ================================================================
# LCEL Chain 构建
# ================================================================


def build_decision_chain(
    chat_model: Any,
    prompt_template: Any,
    parser: Any,
) -> Any:
    """构建 LangChain 决策 Chain。

    使用 LCEL 管道语法: prompt_template | chat_model | parser

    Args:
        chat_model: LangChain ChatModel 实例。
        prompt_template: ChatPromptTemplate 实例。
        parser: PydanticOutputParser 实例。

    Returns:
        LangChain Runnable（可 invoke / stream 的 Chain）。
    """
    return prompt_template | chat_model | parser


# ================================================================
# LangChain 响应适配
# ================================================================


class LCResponse:
    """LangChain 调用结果适配器。

    将 LangChain 的输出包装为与原 LLMResponse 兼容的接口，
    便于在 llm_bot.py 中平滑替换。
    """

    def __init__(
        self,
        text: str,
        model: str = "",
        provider: str = "",
        latency_seconds: float = 0.0,
        input_tokens: int = 0,
        output_tokens: int = 0,
        parsed_output: Optional[LCDecisionOutput] = None,
    ) -> None:
        self.text = text
        self.model = model
        self.provider = provider
        self.latency_seconds = latency_seconds
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.parsed_output = parsed_output


class LCChainWrapper:
    """LangChain Chain 包装器。

    提供与原 LLMClient.generate() 兼容的接口，
    同时添加流量日志、统计追踪和 Context 缓存功能。

    典型用法:
        wrapper = LCChainWrapper(chain, provider_config, traffic_callback)
        response = wrapper.generate(variables, system_prompt_text)
    """

    def __init__(
        self,
        chain: Any,
        config: ProviderConfig,
        traffic_callback: Optional[LCTrafficCallback] = None,
    ) -> None:
        self._chain = chain
        self.config = config
        self._traffic = traffic_callback or _traffic_callback

        # 调用统计
        self._call_count: int = 0
        self._total_latency: float = 0.0
        self._total_input_tokens: int = 0
        self._total_output_tokens: int = 0

        # 最近一次调用的上下文（用于前端调试面板）
        self._last_context: Dict[str, Any] = {}
        # 最近一次错误（None 表示上次调用成功）
        self.last_error: Optional[LLMError] = None

    def generate(
        self,
        variables: Dict[str, Any],
        system_prompt_text: str = "",
        user_prompt_text: str = "",
    ) -> Optional[LCResponse]:
        """执行 LangChain Chain 调用。

        Args:
            variables: Prompt 模板变量字典。
            system_prompt_text: 系统提示文本（用于日志）。
            user_prompt_text: 用户提示文本（用于日志）。

        Returns:
            LCResponse 包装对象，错误时返回 None。
        """
        full_prompt = f"[System]\n{system_prompt_text}\n\n[User]\n{user_prompt_text}"

        # 记录请求
        self._traffic.on_llm_start(self.config.provider, self.config.model, full_prompt)

        start = time.perf_counter()
        try:
            result = self._chain.invoke(variables)
        except Exception as e:
            latency = time.perf_counter() - start
            kind = classify_llm_exception(e)
            self.last_error = LLMError(kind, str(e))
            self._traffic.on_llm_end(f"ERROR[{kind}]: {e}", 0, 0)
            logger.warning(
                "LangChain 调用失败 (%s/%s) [%s]: %s",
                self.config.provider, self.config.model, kind, e,
            )
            # 失败同样缓存上下文,调试面板不再隐藏失败调用
            self._last_context = {
                "provider": self.config.provider,
                "model": self.config.model,
                "system_prompt": system_prompt_text,
                "user_prompt": user_prompt_text,
                "raw_response": "",
                "error": f"[{kind}] {e}",
                "latency_seconds": round(latency, 3),
                "input_tokens": 0,
                "output_tokens": 0,
            }
            return None

        self.last_error = None
        latency = time.perf_counter() - start

        # 提取文本
        if isinstance(result, LCDecisionOutput):
            text = json.dumps(result.model_dump(), ensure_ascii=False)
        elif hasattr(result, "content"):
            text = result.content
        else:
            text = str(result)

        # Token 估算（LangChain 不直接返回 usage，需要从 AIMessage 取）
        input_tokens = 0
        output_tokens = 0
        if hasattr(result, "usage_metadata") and result.usage_metadata:
            input_tokens = result.usage_metadata.get("input_tokens", 0)
            output_tokens = result.usage_metadata.get("output_tokens", 0)
        elif hasattr(result, "response_metadata") and result.response_metadata:
            usage = result.response_metadata.get("token_usage", {})
            input_tokens = usage.get("prompt_tokens", 0)
            output_tokens = usage.get("completion_tokens", 0)

        # 记录响应
        self._traffic.on_llm_end(text, input_tokens, output_tokens)

        # 更新统计
        self._call_count += 1
        self._total_latency += latency
        self._total_input_tokens += input_tokens
        self._total_output_tokens += output_tokens

        # 缓存最近一次上下文（用于前端调试）
        self._last_context = {
            "provider": self.config.provider,
            "model": self.config.model,
            "system_prompt": system_prompt_text,
            "user_prompt": user_prompt_text,
            "raw_response": text,
            "latency_seconds": round(latency, 3),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        }

        return LCResponse(
            text=text,
            model=self.config.model,
            provider=self.config.provider,
            latency_seconds=round(latency, 3),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            parsed_output=result if isinstance(result, LCDecisionOutput) else None,
        )

    @property
    def last_context(self) -> Dict[str, Any]:
        """获取最近一次 LLM 调用的完整上下文（供前端调试面板使用）。"""
        return self._last_context

    @property
    def stats(self) -> Dict[str, Any]:
        """返回调用统计。"""
        return {
            "call_count": self._call_count,
            "total_latency": round(self._total_latency, 2),
            "avg_latency": round(self._total_latency / max(1, self._call_count), 2),
            "total_input_tokens": self._total_input_tokens,
            "total_output_tokens": self._total_output_tokens,
        }

