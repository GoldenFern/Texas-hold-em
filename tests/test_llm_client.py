"""LLM 客户端测试 —— MockClient、超时处理、错误传播。"""

import pytest

from src.llm.client import (
    LLMClientFactory,
    LLMCredentialError,
    LLMError,
    LLMAPIError,
    LLMParseError,
    LLMResponse,
    LLMTimeoutError,
    MockClient,
    OpenAIClient,
)
from src.llm.config import ProviderConfig
from src.llm.fallback import FallbackChain


class TestMockClient:
    """Mock 客户端测试。"""

    def test_mock_returns_preset_response(self) -> None:
        client = MockClient(responses=['{"action": "CHECK", "amount": 0, "reasoning": "test"}'])
        response = client.generate("test prompt")
        assert response is not None
        assert "CHECK" in response.text
        assert response.provider == "mock"
        assert response.latency_seconds < 0.1

    def test_mock_cycles_responses(self) -> None:
        client = MockClient(responses=[
            '{"action": "FOLD", "amount": 0, "reasoning": "r1"}',
            '{"action": "CALL", "amount": 0, "reasoning": "r2"}',
        ])
        r1 = client.generate("p1")
        r2 = client.generate("p2")
        r3 = client.generate("p3")
        assert "FOLD" in r1.text
        assert "CALL" in r2.text
        assert "FOLD" in r3.text  # 循环回第一个

    def test_mock_logs_calls(self) -> None:
        client = MockClient(responses=['{"action": "CHECK", "amount": 0, "reasoning": "x"}'])
        client.generate("prompt A")
        client.generate("prompt B")
        assert len(client.call_log) == 2
        assert client.call_log[0]["prompt"] == "prompt A"
        assert client.call_log[1]["prompt"] == "prompt B"

    def test_mock_stream_callback(self) -> None:
        client = MockClient(responses=['{"action": "CHECK", "amount": 0, "reasoning": "x"}'])
        tokens: list[str] = []
        client.generate_stream("test", on_token=lambda t: tokens.append(t))
        assert len(tokens) > 0
        assert "".join(tokens) == client._responses[0]

    def test_stats_tracking(self) -> None:
        client = MockClient()
        for _ in range(5):
            client.generate("test")
        stats = client.stats
        assert stats["call_count"] == 5
        assert stats["avg_latency"] < 0.1


class TestLLMClientFactory:
    """客户端工厂测试。"""

    def test_create_mock_client(self) -> None:
        config = ProviderConfig(provider="mock", model="mock")
        client = LLMClientFactory.create(config)
        assert isinstance(client, MockClient)

    def test_create_unknown_provider_raises(self) -> None:
        config = ProviderConfig(provider="nonexistent", model="x")
        with pytest.raises(ValueError, match="未知的 LLM 提供商"):
            LLMClientFactory.create(config)

    def test_register_custom_provider(self) -> None:
        class CustomClient(MockClient):
            pass

        LLMClientFactory.register("custom_test", CustomClient)
        config = ProviderConfig(provider="custom_test", model="test")
        client = LLMClientFactory.create(config)
        assert isinstance(client, CustomClient)


class TestCredentialHandling:
    """API Key 缺失时的异常与降级。"""

    def test_openai_client_raises_credential_error_without_key(self) -> None:
        client = OpenAIClient(ProviderConfig(
            provider="deepseek",
            model="deepseek-v4-pro",
            base_url="https://api.deepseek.com",
        ))
        with pytest.raises(LLMCredentialError, match="deepseek"):
            client.generate("test", "system")

    def test_fallback_chain_skips_missing_credentials(self) -> None:
        chain = FallbackChain()
        chain.add_llm_fallback(ProviderConfig(
            provider="deepseek",
            model="deepseek-v4-flash",
            base_url="https://api.deepseek.com",
        ))
        called = {"count": 0}

        def rule_fallback(game, player) -> None:
            called["count"] += 1
            return None

        chain.set_ultimate_fallback(rule_fallback)

        action = chain.execute("prompt", "system", game=None, player=None)  # type: ignore[arg-type]
        assert action is None
        assert called["count"] == 1

    def test_traffic_logging_writes_request_and_response(self, capsys) -> None:
        import os

        from src.llm.client import (
            _log_llm_request,
            _log_llm_response,
            configure_llm_traffic_logging,
            is_llm_traffic_logging_enabled,
        )

        configure_llm_traffic_logging(enabled=True)
        assert is_llm_traffic_logging_enabled()
        _log_llm_request(
            "deepseek",
            "deepseek-v4-pro",
            "https://api.deepseek.com/v1/chat/completions",
            {"messages": [{"role": "user", "content": "fold?"}]},
        )
        _log_llm_response(
            "deepseek",
            "deepseek-v4-pro",
            text='{"action": "CALL", "amount": 0}',
            latency_seconds=1.23,
            input_tokens=120,
            output_tokens=18,
        )

        captured = capsys.readouterr()
        assert "LLM Request" in captured.err
        assert "LLM Response" in captured.err
        assert "deepseek-v4-pro" in captured.err
        assert "fold?" in captured.err

        configure_llm_traffic_logging(enabled=False)
        assert not is_llm_traffic_logging_enabled()
        assert "THP_LLM_LOG_TRAFFIC" not in os.environ

        _log_llm_request(
            "deepseek",
            "deepseek-v4-pro",
            "https://api.deepseek.com/v1/chat/completions",
            {"messages": [{"role": "user", "content": "should not log"}]},
        )
        captured_after_disable = capsys.readouterr()
        assert "LLM Request" not in captured_after_disable.err
        assert "should not log" not in captured_after_disable.err


class TestLLMExceptions:
    """LLM 异常类测试。"""

    def test_llm_error_base(self) -> None:
        err = LLMError("base error message")
        assert str(err) == "base error message"
        assert isinstance(err, Exception)

    def test_llm_timeout_error(self) -> None:
        err = LLMTimeoutError("timeout after 15s")
        assert str(err) == "timeout after 15s"
        assert isinstance(err, LLMError)
        assert isinstance(err, Exception)

    def test_llm_api_error(self) -> None:
        err = LLMAPIError("API returned 500")
        assert "API" in str(err)
        assert isinstance(err, LLMError)

    def test_llm_parse_error(self) -> None:
        err = LLMParseError("无法解析 JSON")
        assert isinstance(err, LLMError)


class TestLLMResponse:
    """LLMResponse 数据类字段测试。"""

    def test_response_fields(self) -> None:
        resp = LLMResponse(
            text='{"action": "CALL"}',
            model="claude-sonnet-4",
            provider="anthropic",
            latency_seconds=1.234,
            input_tokens=500,
            output_tokens=100,
            cached_tokens=200,
        )
        assert resp.text == '{"action": "CALL"}'
        assert resp.model == "claude-sonnet-4"
        assert resp.provider == "anthropic"
        assert resp.latency_seconds == 1.234
        assert resp.input_tokens == 500
        assert resp.output_tokens == 100
        assert resp.cached_tokens == 200

    def test_response_default_tokens(self) -> None:
        resp = LLMResponse(
            text="ok",
            model="test",
            provider="mock",
            latency_seconds=0.01,
        )
        assert resp.input_tokens == 0
        assert resp.output_tokens == 0
        assert resp.cached_tokens == 0
