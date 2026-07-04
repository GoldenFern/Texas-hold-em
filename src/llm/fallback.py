"""降级策略管理 —— LLM 失败时的兜底方案。

降级链:
    Claude Sonnet 4 (15s)
      → Claude Haiku / GPT-4o-mini (10s)
        → 本地 Ollama (8s)
          → 本地 SharkBot 规则引擎（终极兜底）
"""

from __future__ import annotations

import logging
from typing import Callable, List, Optional

from src.engine.game import Action, GameState
from src.engine.player import Player
from src.llm.client import (
    LLMClient,
    LLMAPIError,
    LLMCredentialError,
    LLMError,
    LLMResponse,
    LLMTimeoutError,
    MockClient,
)
from src.llm.config import ProviderConfig

logger = logging.getLogger(__name__)

# 降级决策函数类型
FallbackDecider = Callable[[GameState, Player], Action]


class FallbackChain:
    """多级降级链。

    按顺序尝试调用，直到某一级成功返回合法结果。
    """

    def __init__(self) -> None:
        self._fallback_clients: List[LLMClient] = []
        self._ultimate_fallback: Optional[FallbackDecider] = None

    def add_llm_fallback(self, config: ProviderConfig) -> None:
        """添加一个 LLM 降级客户端。"""
        from src.llm.client import LLMClientFactory
        try:
            client = LLMClientFactory.create(config)
            self._fallback_clients.append(client)
        except Exception as e:
            logger.warning("无法创建降级客户端 %s: %s", config.provider, e)

    def set_ultimate_fallback(self, decider: FallbackDecider) -> None:
        """设置终极降级决策器（规则引擎）。"""
        self._ultimate_fallback = decider

    def execute(
        self,
        prompt: str,
        system_prompt: str,
        game: GameState,
        player: Player,
    ) -> Optional[Action]:
        """按降级链顺序尝试获取决策。

        Args:
            prompt: 用户 prompt。
            system_prompt: 系统 prompt。
            game: 当前游戏状态。
            player: 当前玩家。

        Returns:
            合法的 Action，或 None（如果所有降级均失败）。
        """
        # 尝试 LLM 降级链
        for client in self._fallback_clients:
            try:
                response = client.generate(prompt, system_prompt)
                if response and response.text:
                    from src.llm.response_parser import ResponseParser
                    action = ResponseParser.parse_action(response.text, player, game)
                    if action is not None:
                        logger.info(
                            "降级到 %s 成功: %s",
                            client.config.provider,
                            action,
                        )
                        return action
            except (LLMTimeoutError, LLMAPIError, LLMCredentialError, LLMError) as e:
                logger.debug("降级 %s 失败: %s", client.config.provider, e)
                continue

        # 终极降级：规则引擎
        if self._ultimate_fallback is not None:
            logger.info("使用终极降级（规则引擎）")
            return self._ultimate_fallback(game, player)

        return None

    @property
    def has_fallbacks(self) -> bool:
        """是否有降级方案。"""
        return len(self._fallback_clients) > 0 or self._ultimate_fallback is not None


def build_default_fallback_chain() -> FallbackChain:
    """构建默认降级链（包含 Mock 用于测试）。"""
    chain = FallbackChain()
    # 测试用 Mock 降级
    chain.add_llm_fallback(ProviderConfig(
        provider="mock",
        model="mock",
        timeout_seconds=5.0,
    ))
    return chain
