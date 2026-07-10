"""LLM 驱动的扑克机器人 —— 基于 LangChain 的决策管道。

每一轮该 AI 行动时直接调用 LLM 获取决策，不做降级、不做频率控制。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from src.ai.bots import BoltzmannBot, BotFactory, BotProfile, BotStyle
from src.ai.strategy import postflop_hand_strength
from src.engine.game import Action, ActionType, GameState
from src.engine.player import Player
from src.llm.config import LLMConfig, ProviderConfig, load_config
from src.llm.context_manager import ContextManager
from src.llm.langchain_client import (
    LCChainWrapper,
    LCResponse,
    create_chat_model,
)
from src.llm.prompt_builder import PromptBuilder
from src.llm.response_parser import ResponseParser

logger = logging.getLogger(__name__)

# 最大上下文手牌数（始终发送完整上下文）
_MAX_CONTEXT_HANDS = 50
# 固定 Max Tokens
_FIXED_MAX_TOKENS = 100000


class LLMBot(BoltzmannBot):
    """LLM 驱动的扑克机器人。

    每一轮该 AI 行动时直接调用 LLM API 获取决策。
    LLM 失败时使用规则引擎兜底（不做模型降级）。
    """

    def __init__(
        self,
        name: str,
        llm_config: Optional[LLMConfig] = None,
        seed: int = 42,
        context_manager: Optional[ContextManager] = None,
    ) -> None:
        super().__init__(name, BotProfile(BotStyle.LLM, 0.15, "LLM"), seed)

        self._llm_config = llm_config or load_config()
        self._chain_wrapper: Optional[LCChainWrapper] = None
        self._setup_client()

        # 规则引擎兜底
        self._rule_bot = BotFactory.create(BotStyle.BALANCED, name=f"{name}_rule", seed=seed)

        # 上下文管理器
        self._context_manager = context_manager or ContextManager(
            bot_name=name,
            context_window_hands=_MAX_CONTEXT_HANDS,
        )

        # 决策统计
        self.llm_decisions: int = 0
        self.rule_decisions: int = 0
        self._decision_log: List[Dict[str, Any]] = []
        self._max_log_size = _MAX_CONTEXT_HANDS * 10
        self._current_hole_cards_str: str = ""
        self._last_llm_context: Dict[str, Any] = {}

    def _setup_client(self) -> None:
        """初始化 LangChain ChatModel。"""
        cfg = self._llm_config
        try:
            model = create_chat_model(cfg.primary)
        except Exception as e:
            logger.warning("无法创建 ChatModel (%s)，将使用规则引擎", e)
            self._chain_wrapper = None
            return

        prompt_template = PromptBuilder.get_decision_prompt_template()
        chain = prompt_template | model
        self._chain_wrapper = LCChainWrapper(chain, cfg.primary)

    # ================================================================
    # 核心决策
    # ================================================================

    def decide(self, game_state: GameState, player: Player) -> Action:
        """每一轮直接调用 LLM 获取决策。失败时规则引擎兜底。"""
        self.hands_seen += 1

        if player.hole_cards:
            self._current_hole_cards_str = PromptBuilder._format_cards(player.hole_cards)

        hand_id = game_state.hand_id

        action = self._llm_decide(game_state, player)
        if action is not None:
            self.llm_decisions += 1
            self._log_decision("LLM", action, hand_id=hand_id)
            return action

        # LLM 失败 → 规则引擎兜底
        self.rule_decisions += 1
        action = self._rule_bot.decide(game_state, player)
        self._log_decision("规则引擎", action, hand_id=hand_id)
        return action

    def _llm_decide(self, game: GameState, player: Player) -> Optional[Action]:
        """调用 LLM 获取决策。"""
        if self._chain_wrapper is None:
            return None

        try:
            hand_strength = postflop_hand_strength(player.hole_cards, game.community_cards)
            equity_pct = hand_strength * 100.0
            opponent_stats = self._gather_opponent_stats(game)
            session_context = self._context_manager.get_context_for_prompt()

            game_state_text = PromptBuilder.build_game_state_text(
                game=game, player=player,
                hand_strength=hand_strength, equity_pct=equity_pct,
                opponent_stats=opponent_stats,
            )
            session_context_text = PromptBuilder.build_session_context_text(session_context)
            system_prompt = PromptBuilder.get_system_prompt()

            variables = {
                "game_state": game_state_text,
                "session_context": session_context_text,
            }

            response = self._chain_wrapper.generate(
                variables=variables,
                system_prompt_text=system_prompt,
                user_prompt_text=game_state_text + session_context_text,
            )

            if response and response.text:
                action = ResponseParser.parse_action(response.text, player, game)
                if action is not None:
                    self._last_llm_context = {
                        **self._chain_wrapper.last_context,
                        "parsed_action": str(action),
                        "session_context": session_context,
                        "table_image": self._context_manager.get_table_image(),
                        "call_index": self.llm_decisions + 1,
                    }
                    logger.info(
                        "LLM 决策 (%s/%s, %.1fs): %s -> %s",
                        self._chain_wrapper.config.provider,
                        self._chain_wrapper.config.model,
                        response.latency_seconds,
                        ResponseParser.extract_reasoning(response.text),
                        action,
                    )
                    return action
        except Exception as e:
            logger.warning("LLM 调用失败: %s", e)

        return None

    # ================================================================
    # 辅助方法
    # ================================================================

    def _gather_opponent_stats(self, game: GameState) -> Dict[str, Dict[str, float]]:
        """收集对手统计数据（用于 Prompt 注入）。

        优先从 ContextManager 获取真实统计数据。
        """
        stats: Dict[str, Dict[str, float]] = {}
        for p in game.players:
            if p.is_human or p.status.value >= 3:  # OUT
                continue

            profile = self._context_manager.get_opponent_stats(p.name)
            if profile.hands_played > 0:
                stats[p.name] = {
                    "vpip": profile.vpip,
                    "pfr": profile.pfr,
                    "aggression": profile.aggression_factor,
                    "classification": profile.classification,
                    "hands_played": profile.hands_played,
                }
                if profile.showdown_hands:
                    stats[p.name]["showdown_hands"] = profile.showdown_hands[-3:]
            else:
                stats[p.name] = {
                    "vpip": 0.25,
                    "pfr": 0.15,
                    "aggression": 0.5,
                    "classification": "未知（数据不足）",
                    "hands_played": 0,
                }
        return stats

    def _log_decision(self, source: str, action: Action, hand_id: int = 0) -> None:
        """记录决策到日志。"""
        entry = {
            "来源": source,
            "动作": action.action_type.name,
            "金额": action.amount,
            "是否全下": action.is_all_in,
        }
        self._decision_log.append(entry)
        if len(self._decision_log) > self._max_log_size:
            self._decision_log = self._decision_log[-self._max_log_size:]

        # 同步记录到 ContextManager（用于桌面形象追踪和手牌摘要）
        self._context_manager.record_action(
            bot_name=self.name,
            action_type=action.action_type,
            hole_cards=self._current_hole_cards_str,
            hand_id=hand_id,
        )

    # ================================================================
    # 上下文管理接口（供 GameManager 调用）
    # ================================================================

    def end_hand(self, won: bool = False, profit: int = 0) -> None:
        self._context_manager.end_hand(won=won, profit=profit, reporter=None)

    @property
    def context_manager(self) -> ContextManager:
        return self._context_manager

    @property
    def last_llm_context(self) -> Dict[str, Any]:
        return self._last_llm_context

    # ================================================================
    # 统计与调试
    # ================================================================

    @property
    def decision_stats(self) -> Dict[str, Any]:
        total = max(1, self.llm_decisions + self.rule_decisions)
        return {
            "总决策次数": total,
            "LLM 决策次数": self.llm_decisions,
            "规则引擎兜底次数": self.rule_decisions,
            "LLM 使用率": round(self.llm_decisions / total, 3),
            "管道统计": self._chain_wrapper.stats if self._chain_wrapper else {},
        }

    def __repr__(self) -> str:
        provider = self._chain_wrapper.config.provider if self._chain_wrapper else "none"
        model = self._chain_wrapper.config.model if self._chain_wrapper else "none"
        return f"LLMBot({self.name}, {provider}/{model})"
