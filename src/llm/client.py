"""LLM 客户端抽象层 — 多后端统一接口。

支持：Anthropic Claude, OpenAI GPT, 本地 Ollama。
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from src.llm.config import ProviderConfig

logger = logging.getLogger(__name__)
_TRAFFIC_LOGGER = logging.getLogger("src.llm.traffic")

_CREDENTIAL_HINTS: Dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY 或 THP_LLM_API_KEY",
    "openai": "OPENAI_API_KEY 或 THP_LLM_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY 或 THP_LLM_API_KEY",
    "qwen": "DASHSCOPE_API_KEY 或 THP_LLM_API_KEY",
    "glm": "GLM_API_KEY 或 THP_LLM_API_KEY",
    "kimi": "MOONSHOT_API_KEY 或 THP_LLM_API_KEY",
    "minimax": "MINIMAX_API_KEY 或 THP_LLM_API_KEY",
    "volcengine": "ARK_API_KEY 或 THP_LLM_API_KEY",
    "longcat": "LONGCAT_API_KEY 或 THP_LLM_API_KEY",
}


def _credential_error(provider: str) -> LLMCredentialError:
    """构建 API Key 缺失异常。"""
    hint = _CREDENTIAL_HINTS.get(provider, "THP_LLM_API_KEY")
    return LLMCredentialError(f"缺少 {provider} API Key，请设置 {hint}")


def _is_credential_error(exc: Exception) -> bool:
    """判断异常是否由 API Key 缺失/无效引起。"""
    msg = str(exc).lower()
    return any(
        token in msg
        for token in ("credential", "api_key", "api key", "authentication", "unauthorized")
    )


def is_llm_traffic_logging_enabled() -> bool:
    """是否向终端输出 LLM 请求/响应。"""
    val = os.environ.get("THP_LLM_LOG_TRAFFIC", "")
    return val.strip().lower() in ("1", "true", "yes", "on")


def configure_llm_traffic_logging(enabled: bool = True) -> None:
    """配置 LLM 流量日志输出到终端。"""
    if enabled:
        os.environ["THP_LLM_LOG_TRAFFIC"] = "1"
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(message)s"))
    _TRAFFIC_LOGGER.setLevel(logging.INFO if enabled else logging.WARNING)
    _TRAFFIC_LOGGER.handlers.clear()
    if enabled:
        _TRAFFIC_LOGGER.addHandler(handler)
    _TRAFFIC_LOGGER.propagate = False


def _format_traffic_block(title: str, body: str) -> str:
    """格式化终端日志块。"""
    separator = "─" * 60
    return f"\n{separator}\n{title}\n{separator}\n{body}\n"


def _log_llm_request(
    provider: str,
    model: str,
    endpoint: str,
    payload: Dict[str, Any],
) -> None:
    """记录发往 API 供应商的请求。"""
    if not is_llm_traffic_logging_enabled():
        return
    safe_payload = json.loads(json.dumps(payload, ensure_ascii=False, default=str))
    body = json.dumps(safe_payload, ensure_ascii=False, indent=2)
    title = f"LLM Request → {provider} / {model}\nEndpoint: {endpoint}"
    _TRAFFIC_LOGGER.info("%s", _format_traffic_block(title, body))


def _log_llm_response(
    provider: str,
    model: str,
    *,
    text: str,
    latency_seconds: float,
    input_tokens: int = 0,
    output_tokens: int = 0,
    error: str = "",
) -> None:
    """记录 API 供应商返回的响应。"""
    if not is_llm_traffic_logging_enabled():
        return
    if error:
        body = f"ERROR: {error}"
        title = f"LLM Response ← {provider} / {model} ({latency_seconds:.2f}s)"
    else:
        token_line = f"Tokens: in={input_tokens} out={output_tokens}"
        body = f"{text}\n\n{token_line}"
        title = f"LLM Response ← {provider} / {model} ({latency_seconds:.2f}s)"
    _TRAFFIC_LOGGER.info("%s", _format_traffic_block(title, body))


@dataclass
class LLMResponse:
    """LLM 调用结果。"""

    text: str
    model: str
    provider: str
    latency_seconds: float
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0


class LLMError(Exception):
    """LLM 调用基础异常。"""


class LLMTimeoutError(LLMError):
    """LLM 调用超时。"""


class LLMAPIError(LLMError):
    """LLM API 返回错误。"""


class LLMParseError(LLMError):
    """LLM 响应无法解析。"""


class LLMCredentialError(LLMError):
    """LLM API Key 未配置或无效。"""


class LLMClient(ABC):
    """LLM 客户端抽象基类。

    每个后端实现此接口，提供 generate 和 generate_stream 方法。
    """

    def __init__(self, config: ProviderConfig) -> None:
        self.config = config
        self._call_count: int = 0
        self._total_latency: float = 0.0
        self._total_input_tokens: int = 0
        self._total_output_tokens: int = 0

    @abstractmethod
    def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        timeout: Optional[float] = None,
    ) -> LLMResponse:
        """同步生成响应。"""

    @abstractmethod
    def generate_stream(
        self,
        prompt: str,
        system_prompt: str = "",
        on_token: Optional[Callable[[str], None]] = None,
        timeout: Optional[float] = None,
    ) -> LLMResponse:
        """流式生成响应，每收到一个 token 调用 on_token 回调。"""

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

    def _record_call(self, response: LLMResponse) -> None:
        """记录一次调用统计。"""
        self._call_count += 1
        self._total_latency += response.latency_seconds
        self._total_input_tokens += response.input_tokens
        self._total_output_tokens += response.output_tokens


class AnthropicClient(LLMClient):
    """Anthropic Claude API 客户端。"""

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            if not self.config.api_key:
                raise _credential_error(self.config.provider)
            try:
                import anthropic
                self._client = anthropic.Anthropic(api_key=self.config.api_key)
            except ImportError:
                raise LLMError(
                    "anthropic 包未安装，请运行: pip install anthropic"
                )
            except Exception as e:
                if _is_credential_error(e):
                    raise _credential_error(self.config.provider) from e
                raise
        return self._client

    def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        timeout: Optional[float] = None,
    ) -> LLMResponse:
        client = self._get_client()
        timeout_s = timeout or self.config.timeout_seconds

        kwargs: Dict[str, Any] = {
            "model": self.config.model,
            "max_tokens": self.config.max_tokens,
            "temperature": self.config.temperature,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system_prompt:
            kwargs["system"] = system_prompt

        _log_llm_request(
            self.config.provider,
            self.config.model,
            "anthropic.messages.create",
            kwargs,
        )

        start = time.perf_counter()
        try:
            response = client.messages.create(**kwargs)
        except Exception as e:
            latency = time.perf_counter() - start
            _log_llm_response(
                self.config.provider,
                self.config.model,
                text="",
                latency_seconds=latency,
                error=str(e),
            )
            raise LLMAPIError(f"Anthropic API 错误: {e}") from e

        latency = time.perf_counter() - start
        if latency > timeout_s:
            raise LLMTimeoutError(
                f"Anthropic 调用超时 ({latency:.1f}s > {timeout_s}s)"
            )

        content = response.content
        text = ""
        input_tokens = response.usage.input_tokens if hasattr(response, "usage") else 0
        output_tokens = response.usage.output_tokens if hasattr(response, "usage") else 0
        cached_tokens = getattr(response.usage, "cache_read_input_tokens", 0) if hasattr(response, "usage") else 0

        for block in content:
            if hasattr(block, "text"):
                text += block.text

        result = LLMResponse(
            text=text,
            model=self.config.model,
            provider="anthropic",
            latency_seconds=round(latency, 3),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_tokens=cached_tokens,
        )
        _log_llm_response(
            self.config.provider,
            self.config.model,
            text=text,
            latency_seconds=latency,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
        self._record_call(result)
        return result

    def generate_stream(
        self,
        prompt: str,
        system_prompt: str = "",
        on_token: Optional[Callable[[str], None]] = None,
        timeout: Optional[float] = None,
    ) -> LLMResponse:
        client = self._get_client()
        timeout_s = timeout or self.config.timeout_seconds

        kwargs: Dict[str, Any] = {
            "model": self.config.model,
            "max_tokens": self.config.max_tokens,
            "temperature": self.config.temperature,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system_prompt:
            kwargs["system"] = system_prompt

        start = time.perf_counter()
        full_text = ""
        try:
            with client.messages.stream(**kwargs) as stream:
                for event in stream:
                    if hasattr(event, "delta") and hasattr(event.delta, "text"):
                        token = event.delta.text
                        full_text += token
                        if on_token:
                            on_token(token)
                    if time.perf_counter() - start > timeout_s:
                        raise LLMTimeoutError("流式调用超时")
        except LLMTimeoutError:
            raise
        except Exception as e:
            raise LLMAPIError(f"Anthropic 流式 API 错误: {e}") from e

        latency = time.perf_counter() - start
        result = LLMResponse(
            text=full_text,
            model=self.config.model,
            provider="anthropic",
            latency_seconds=round(latency, 3),
        )
        self._record_call(result)
        return result


class OpenAIClient(LLMClient):
    """OpenAI 兼容 API 客户端（GPT / DeepSeek / Qwen / GLM / Kimi / MiniMax）。"""

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            if not self.config.api_key:
                raise _credential_error(self.config.provider)
            try:
                import openai
                kwargs: Dict[str, Any] = {"api_key": self.config.api_key}
                if self.config.base_url:
                    kwargs["base_url"] = self.config.base_url
                self._client = openai.OpenAI(**kwargs)
            except ImportError:
                raise LLMError(
                    "openai 包未安装，请运行: pip install openai"
                )
            except Exception as e:
                if _is_credential_error(e):
                    raise _credential_error(self.config.provider) from e
                raise
        return self._client

    def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        timeout: Optional[float] = None,
    ) -> LLMResponse:
        client = self._get_client()
        timeout_s = timeout or self.config.timeout_seconds

        messages: List[Dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        request_payload = {
            "model": self.config.model,
            "messages": messages,
            "max_tokens": self.config.max_tokens,
            "temperature": self.config.temperature,
        }
        endpoint = self.config.base_url or "https://api.openai.com/v1"
        _log_llm_request(
            self.config.provider,
            self.config.model,
            f"{endpoint.rstrip('/')}/chat/completions",
            request_payload,
        )

        start = time.perf_counter()
        try:
            response = client.chat.completions.create(
                model=self.config.model,
                messages=messages,
                max_tokens=self.config.max_tokens,
                temperature=self.config.temperature,
            )
        except Exception as e:
            latency = time.perf_counter() - start
            _log_llm_response(
                self.config.provider,
                self.config.model,
                text="",
                latency_seconds=latency,
                error=str(e),
            )
            raise LLMAPIError(f"OpenAI API 错误: {e}") from e

        latency = time.perf_counter() - start
        if latency > timeout_s:
            raise LLMTimeoutError(
                f"OpenAI 调用超时 ({latency:.1f}s > {timeout_s}s)"
            )

        choice = response.choices[0]
        text = choice.message.content or ""
        usage = response.usage
        input_tokens = usage.prompt_tokens if usage else 0
        output_tokens = usage.completion_tokens if usage else 0

        result = LLMResponse(
            text=text,
            model=self.config.model,
            provider=self.config.provider,
            latency_seconds=round(latency, 3),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
        _log_llm_response(
            self.config.provider,
            self.config.model,
            text=text,
            latency_seconds=latency,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
        self._record_call(result)
        return result

    def generate_stream(
        self,
        prompt: str,
        system_prompt: str = "",
        on_token: Optional[Callable[[str], None]] = None,
        timeout: Optional[float] = None,
    ) -> LLMResponse:
        client = self._get_client()
        timeout_s = timeout or self.config.timeout_seconds

        messages: List[Dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        start = time.perf_counter()
        full_text = ""
        try:
            stream = client.chat.completions.create(
                model=self.config.model,
                messages=messages,
                max_tokens=self.config.max_tokens,
                temperature=self.config.temperature,
                stream=True,
            )
            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    token = chunk.choices[0].delta.content
                    full_text += token
                    if on_token:
                        on_token(token)
                if time.perf_counter() - start > timeout_s:
                    raise LLMTimeoutError("流式调用超时")
        except LLMTimeoutError:
            raise
        except Exception as e:
            raise LLMAPIError(f"OpenAI 流式 API 错误: {e}") from e

        latency = time.perf_counter() - start
        result = LLMResponse(
            text=full_text,
            model=self.config.model,
            provider="openai",
            latency_seconds=round(latency, 3),
        )
        self._record_call(result)
        return result


class OllamaClient(LLMClient):
    """本地 Ollama 客户端（零成本/离线）。"""

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        if not config.base_url:
            config.base_url = "http://localhost:11434"
        self._session: Any = None

    def _get_session(self) -> Any:
        if self._session is None:
            try:
                import requests
                self._session = requests.Session()
            except ImportError:
                raise LLMError("requests 包未安装")
        return self._session

    def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        timeout: Optional[float] = None,
    ) -> LLMResponse:
        session = self._get_session()
        timeout_s = timeout or self.config.timeout_seconds

        payload: Dict[str, Any] = {
            "model": self.config.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": self.config.temperature,
                "num_predict": self.config.max_tokens,
            },
        }
        if system_prompt:
            payload["system"] = system_prompt

        endpoint = f"{self.config.base_url.rstrip('/')}/api/generate"
        _log_llm_request(
            self.config.provider,
            self.config.model,
            endpoint,
            payload,
        )

        start = time.perf_counter()
        try:
            resp = session.post(
                f"{self.config.base_url}/api/generate",
                json=payload,
                timeout=timeout_s,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            latency = time.perf_counter() - start
            _log_llm_response(
                self.config.provider,
                self.config.model,
                text="",
                latency_seconds=latency,
                error=str(e),
            )
            raise LLMAPIError(f"Ollama API 错误: {e}") from e

        latency = time.perf_counter() - start
        text = data.get("response", "")
        eval_count = data.get("eval_count", 0)
        prompt_eval_count = data.get("prompt_eval_count", 0)

        result = LLMResponse(
            text=text,
            model=self.config.model,
            provider="ollama",
            latency_seconds=round(latency, 3),
            input_tokens=prompt_eval_count,
            output_tokens=eval_count,
        )
        _log_llm_response(
            self.config.provider,
            self.config.model,
            text=text,
            latency_seconds=latency,
            input_tokens=prompt_eval_count,
            output_tokens=eval_count,
        )
        self._record_call(result)
        return result

    def generate_stream(
        self,
        prompt: str,
        system_prompt: str = "",
        on_token: Optional[Callable[[str], None]] = None,
        timeout: Optional[float] = None,
    ) -> LLMResponse:
        session = self._get_session()
        timeout_s = timeout or self.config.timeout_seconds

        payload: Dict[str, Any] = {
            "model": self.config.model,
            "prompt": prompt,
            "stream": True,
            "options": {
                "temperature": self.config.temperature,
                "num_predict": self.config.max_tokens,
            },
        }
        if system_prompt:
            payload["system"] = system_prompt

        start = time.perf_counter()
        full_text = ""
        try:
            resp = session.post(
                f"{self.config.base_url}/api/generate",
                json=payload,
                timeout=timeout_s,
                stream=True,
            )
            resp.raise_for_status()
            for line in resp.iter_lines(decode_unicode=True):
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                    token = chunk.get("response", "")
                    full_text += token
                    if on_token:
                        on_token(token)
                    if chunk.get("done", False):
                        break
                except json.JSONDecodeError:
                    continue
                if time.perf_counter() - start > timeout_s:
                    raise LLMTimeoutError("流式调用超时")
        except LLMTimeoutError:
            raise
        except Exception as e:
            raise LLMAPIError(f"Ollama 流式 API 错误: {e}") from e

        latency = time.perf_counter() - start
        result = LLMResponse(
            text=full_text,
            model=self.config.model,
            provider="ollama",
            latency_seconds=round(latency, 3),
        )
        self._record_call(result)
        return result


class MockClient(LLMClient):
    """测试用 Mock 客户端。

    返回预设响应，不调用真实 API。
    """

    def __init__(self, config: Optional[ProviderConfig] = None, responses: Optional[List[str]] = None) -> None:
        cfg = config or ProviderConfig(provider="mock", model="mock")
        super().__init__(cfg)
        self._responses = responses or ['{"action": "CALL", "amount": 0, "reasoning": "mock"}']
        self._idx: int = 0
        self._call_log: List[Dict[str, str]] = []

    def add_response(self, response_json: str) -> None:
        """追加一个预设响应。"""
        self._responses.append(response_json)
        self._idx = 0

    def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        timeout: Optional[float] = None,
    ) -> LLMResponse:
        self._call_log.append({"prompt": prompt, "system": system_prompt})
        text = self._responses[self._idx % len(self._responses)]
        self._idx += 1
        result = LLMResponse(
            text=text,
            model="mock",
            provider="mock",
            latency_seconds=0.01,
            input_tokens=100,
            output_tokens=20,
        )
        self._record_call(result)
        return result

    def generate_stream(
        self,
        prompt: str,
        system_prompt: str = "",
        on_token: Optional[Callable[[str], None]] = None,
        timeout: Optional[float] = None,
    ) -> LLMResponse:
        self._call_log.append({"prompt": prompt, "system": system_prompt})
        text = self._responses[self._idx % len(self._responses)]
        self._idx += 1
        if on_token:
            for char in text:
                on_token(char)
        result = LLMResponse(
            text=text,
            model="mock",
            provider="mock",
            latency_seconds=0.01,
        )
        self._record_call(result)
        return result

    @property
    def call_log(self) -> List[Dict[str, str]]:
        return self._call_log


class LLMClientFactory:
    """LLM 客户端工厂。

    根据 ProviderConfig.provider 创建对应的客户端实例。
    """

    _REGISTRY: Dict[str, type] = {
        "anthropic": AnthropicClient,
        "openai": OpenAIClient,
        "deepseek": OpenAIClient,    # DeepSeek（OpenAI 兼容）
        "qwen": OpenAIClient,        # 通义千问（OpenAI 兼容）
        "glm": OpenAIClient,         # 智谱 GLM（OpenAI 兼容）
        "kimi": OpenAIClient,        # 月之暗面 Kimi（OpenAI 兼容）
        "minimax": OpenAIClient,     # 稀宇科技 MiniMax（OpenAI 兼容）
        "volcengine": OpenAIClient,  # 字节跳动火山引擎（OpenAI 兼容）
        "longcat": OpenAIClient,     # 美团 LongCat（OpenAI 兼容）
        "ollama": OllamaClient,
        "mock": MockClient,
    }

    @classmethod
    def create(cls, config: ProviderConfig) -> LLMClient:
        """根据配置创建 LLM 客户端。"""
        client_cls = cls._REGISTRY.get(config.provider)
        if client_cls is None:
            raise ValueError(
                f"未知的 LLM 提供商: {config.provider}。"
                f"支持: {list(cls._REGISTRY.keys())}"
            )
        return client_cls(config)

    @classmethod
    def register(cls, provider: str, client_cls: type) -> None:
        """注册自定义 LLM 客户端。"""
        cls._REGISTRY[provider] = client_cls
