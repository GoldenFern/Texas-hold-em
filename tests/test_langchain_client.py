"""LCChainWrapper 全链路测试 —— generate、错误分类、失败上下文缓存。"""

from __future__ import annotations

import pytest

from src.llm.config import ProviderConfig
from src.llm.langchain_client import (
    LCChainWrapper,
    LLMError,
    build_fake_chat_model,
    classify_llm_exception,
)
from src.llm.prompt_builder import PromptBuilder


def make_wrapper(responses: list[str]) -> LCChainWrapper:
    fake = build_fake_chat_model(responses)
    chain = PromptBuilder.get_decision_prompt_template() | fake
    return LCChainWrapper(chain, ProviderConfig(provider="mock", model="mock"))


class TestGenerate:
    def test_full_chain_returns_text(self) -> None:
        wrapper = make_wrapper(['{"动作": "跟注", "金额": 0, "理由": "测试"}'])
        resp = wrapper.generate(
            variables={"game_state": "状态", "session_context": ""},
            system_prompt_text="sys",
            user_prompt_text="user",
        )
        assert resp is not None
        assert "跟注" in resp.text
        assert wrapper.stats["call_count"] == 1
        assert wrapper.last_error is None

    def test_last_context_cached_on_success(self) -> None:
        wrapper = make_wrapper(['{"动作": "过牌"}'])
        wrapper.generate(
            variables={"game_state": "G", "session_context": ""},
            system_prompt_text="S", user_prompt_text="U",
        )
        ctx = wrapper.last_context
        assert ctx["system_prompt"] == "S"
        assert ctx["user_prompt"] == "U"
        assert "过牌" in ctx["raw_response"]

    def test_exception_returns_none_and_caches_error_context(self) -> None:
        """链路异常 → None + 类型化 last_error + 失败上下文可见(L4)。"""

        class BoomModel:
            def invoke(self, *_args, **_kwargs):
                raise TimeoutError("request timed out")

        wrapper = LCChainWrapper(
            BoomModel(), ProviderConfig(provider="mock", model="mock"),
        )
        resp = wrapper.generate(
            variables={}, system_prompt_text="S", user_prompt_text="U",
        )
        assert resp is None
        assert isinstance(wrapper.last_error, LLMError)
        assert wrapper.last_error.kind == "timeout"
        assert "timeout" in wrapper.last_context["error"]
        assert wrapper.last_context["system_prompt"] == "S"


class TestErrorClassification:
    @pytest.mark.parametrize("exc,expected", [
        (ValueError("401 Unauthorized: invalid api key"), "auth"),
        (RuntimeError("429 rate limit exceeded"), "rate_limit"),
        (TimeoutError("read timed out"), "timeout"),
        (ValueError("Invalid json output"), "parse"),
        (ConnectionError("connection refused"), "network"),
        (Exception("mystery"), "unknown"),
    ])
    def test_kinds(self, exc: Exception, expected: str) -> None:
        assert classify_llm_exception(exc) == expected


class TestCreateChatModel:
    def test_unknown_provider_raises(self) -> None:
        from src.llm.langchain_client import create_chat_model
        with pytest.raises(ValueError):
            create_chat_model(ProviderConfig(provider="nope", model="x"))

    def test_openai_compatible_gets_max_tokens_and_retries(self) -> None:
        """L1/L9 回归: max_tokens 采用可配置默认(4096),重试传入模型。"""
        from src.llm.langchain_client import create_chat_model
        cfg = ProviderConfig(provider="deepseek", model="deepseek-chat",
                             api_key="k")
        model = create_chat_model(cfg)
        assert model.max_tokens == 4096
        assert model.max_retries == cfg.max_retries
