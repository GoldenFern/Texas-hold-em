"""LLM 客户端测试 —— MockClient、工厂、流量日志（LangChain 版本）。"""

import pytest

from src.llm.langchain_client import (
    MockClient,
    LCTrafficCallback,
    create_chat_model,
    build_fake_chat_model,
    LCResponse,
    configure_llm_traffic_logging,
)
from src.llm.config import ProviderConfig
from src.llm.fallback import FallbackChain


class TestMockClient:
    """Mock 客户端测试（向后兼容接口）。"""

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

    def test_stats_tracking(self) -> None:
        client = MockClient()
        for _ in range(5):
            client.generate("test")
        stats = client.stats
        assert stats["call_count"] == 5
        assert stats["avg_latency"] < 0.1


class TestLangChainFactory:
    """LangChain ChatModel 工厂测试。"""

    def test_create_mock_model(self) -> None:
        """测试通过 create_chat_model 创建 mock。"""
        config = ProviderConfig(provider="mock", model="mock")
        model = create_chat_model(config)
        assert model is not None
        from langchain_core.language_models import FakeListChatModel
        assert isinstance(model, FakeListChatModel)

    def test_create_unknown_provider_raises(self) -> None:
        """未知 provider 应抛出 ValueError。"""
        config = ProviderConfig(provider="nonexistent", model="x")
        with pytest.raises(ValueError, match="未知的 LLM 提供商"):
            create_chat_model(config)

    def test_build_fake_chat_model(self) -> None:
        """测试 build_fake_chat_model 辅助函数。"""
        model = build_fake_chat_model(["response 1", "response 2"])
        from langchain_core.language_models import FakeListChatModel
        assert isinstance(model, FakeListChatModel)


class TestCredentialHandling:
    """API Key 缺失时的降级。"""

    def test_fallback_chain_skips_missing_credentials(self) -> None:
        """降级链跳过未配置的 LLM，使用规则引擎兜底。"""
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

        action = chain.execute_ultimate(game=None, player=None)  # type: ignore[arg-type]
        assert action is None
        assert called["count"] == 1

    def test_traffic_logging_writes_request_and_response(self, capsys) -> None:
        """流量日志记录请求和响应到 stderr。"""
        import os

        configure_llm_traffic_logging(enabled=True)

        callback = LCTrafficCallback()
        callback.on_llm_start("deepseek", "deepseek-v4-pro", "test prompt content")
        callback.on_llm_end('{"action": "CALL", "amount": 0}', input_tokens=120, output_tokens=18)

        captured = capsys.readouterr()
        assert "LLM Request" in captured.err
        assert "LLM Response" in captured.err
        assert "deepseek-v4-pro" in captured.err

        configure_llm_traffic_logging(enabled=False)
        assert "THP_LLM_LOG_TRAFFIC" not in os.environ

        # 禁用后不再输出
        saved_handler_count = len(
            __import__('logging').getLogger("src.llm.traffic").handlers
        )
        assert saved_handler_count == 0


class TestLCResponse:
    """LCResponse 数据类字段测试。"""

    def test_response_fields(self) -> None:
        resp = LCResponse(
            text='{"action": "CALL"}',
            model="claude-sonnet-4",
            provider="anthropic",
            latency_seconds=1.234,
            input_tokens=500,
            output_tokens=100,
        )
        assert resp.text == '{"action": "CALL"}'
        assert resp.model == "claude-sonnet-4"
        assert resp.provider == "anthropic"
        assert resp.latency_seconds == 1.234
        assert resp.input_tokens == 500
        assert resp.output_tokens == 100
        assert resp.parsed_output is None

    def test_response_default_tokens(self) -> None:
        resp = LCResponse(
            text="ok",
            model="test",
            provider="mock",
            latency_seconds=0.01,
        )
        assert resp.input_tokens == 0
        assert resp.output_tokens == 0
