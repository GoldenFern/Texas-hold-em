"""LLM 客户端测试 —— MockClient、超时处理、错误传播。"""

import pytest

from src.llm.client import (
    LLMClientFactory,
    LLMError,
    LLMResponse,
    LLMTimeoutError,
    MockClient,
)
from src.llm.config import ProviderConfig


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
