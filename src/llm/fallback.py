"""降级策略管理 —— LLM 失败时的兜底方案（LangChain 版本）。

使用 LangChain 的 Runnable.with_fallbacks() 实现 LLM 级别的降级，
规则引擎作为终极兜底。

降级链:
    主力模型 (15s)
      → 降级模型 1 (10s)
        → 降级模型 2 (10s)
          → 规则引擎 SharkBot（终极兜底）
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

from src.engine.game import Action, GameState
from src.engine.player import Player
from src.llm.config import ProviderConfig

logger = logging.getLogger(__name__)

# 降级决策函数类型
FallbackDecider = Callable[[GameState, Player], Action]


class FallbackChain:
    """多级降级链（LangChain 适配版本）。

    在 LangChain 架构下，LLM 级别的降级由 Runnable.with_fallbacks() 处理。
    此类的职责简化为：
        1. 构建包含主模型和降级模型的 chain list
        2. 提供规则引擎终极兜底
    """

    def __init__(self) -> None:
        self._fallback_configs: List[ProviderConfig] = []
        self._ultimate_fallback: Optional[FallbackDecider] = None
        self._chain_wrappers: Dict[str, Any] = {}  # provider -> LCChainWrapper
        # 向后兼容：存储创建的 LLM 客户端（测试可能需要访问）
        self._fallback_clients: List[Any] = []

    def add_llm_fallback(self, config: ProviderConfig) -> None:
        """添加一个 LLM 降级配置。

        Args:
            config: 降级 LLM 的 ProviderConfig。
        """
        self._fallback_configs.append(config)

    def set_ultimate_fallback(self, decider: FallbackDecider) -> None:
        """设置终极降级决策器（规则引擎）。

        Args:
            decider: 接受 (GameState, Player) 返回 Action 的可调用对象。
        """
        self._ultimate_fallback = decider

    def execute_ultimate(
        self,
        game: GameState,
        player: Player,
    ) -> Optional[Action]:
        """执行终极降级（规则引擎）。

        Args:
            game: 当前游戏状态。
            player: 当前玩家。

        Returns:
            合法的 Action，或 None。
        """
        if self._ultimate_fallback is not None:
            logger.info("所有 LLM 降级失败，使用规则引擎兜底")
            return self._ultimate_fallback(game, player)
        return None

    def execute(
        self,
        prompt: str,
        system_prompt: str,
        game: GameState,
        player: Player,
    ) -> Optional[Action]:
        """向后兼容的降级链执行方法。

        遍历每个降级 LLM 配置，尝试调用 LLM 并解析为 Action。
        若全部失败，调用终极兜底（规则引擎）。

        Args:
            prompt: 用户 prompt。
            system_prompt: 系统 prompt。
            game: 当前游戏状态。
            player: 当前玩家。

        Returns:
            合法的 Action，或 None。
        """
        from src.llm.langchain_client import create_chat_model, MockClient
        from src.llm.response_parser import ResponseParser
        from langchain_core.messages import HumanMessage, SystemMessage

        # 尝试 LLM 降级链
        for i, config in enumerate(self._fallback_configs):
            try:
                # 优先使用预设的客户端（用于测试注入坏响应）
                if i < len(self._fallback_clients):
                    client = self._fallback_clients[i]
                else:
                    client = create_chat_model(config)

                # 如果是 MockClient（向后兼容），使用其 generate 方法
                if isinstance(client, MockClient):
                    response = client.generate(prompt, system_prompt)
                    text = response.text
                else:
                    # LangChain ChatModel
                    messages = []
                    if system_prompt:
                        messages.append(SystemMessage(content=system_prompt))
                    messages.append(HumanMessage(content=prompt))
                    result = client.invoke(messages)
                    text = result.content if hasattr(result, 'content') else str(result)

                if text:
                    action = ResponseParser.parse_action(text, player, game)
                    if action is not None:
                        logger.info("降级到 %s 成功: %s", config.provider, action)
                        return action
            except Exception as e:
                logger.debug("降级 %s 失败: %s", config.provider, e)
                continue

        # 终极降级：规则引擎
        return self.execute_ultimate(game, player)

    @property
    def fallback_configs(self) -> List[ProviderConfig]:
        """获取所有 LLM 降级配置。"""
        return self._fallback_configs

    @property
    def has_fallbacks(self) -> bool:
        """是否有降级方案。"""
        return len(self._fallback_configs) > 0 or self._ultimate_fallback is not None


def build_default_fallback_chain() -> FallbackChain:
    """构建默认降级链（Mock 用于测试）。"""
    chain = FallbackChain()
    chain.add_llm_fallback(ProviderConfig(
        provider="mock",
        model="mock",
        timeout_seconds=5.0,
    ))
    return chain
