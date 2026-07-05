"""LLM 驱动的扑克机器人 —— BotBase 子类。

支持：
    - 混合决策（LLM + 规则引擎降级）
    - 多后端自动切换
    - 调用频率控制（every / critical / mixed）
    - 蒙特卡洛胜率注入
    - 对手统计注入
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from src.ai.bots import BoltzmannBot, BotFactory, BotProfile, BotStyle
from src.ai.strategy import (
    has_draw,
    is_premium_hand,
    postflop_hand_strength,
    preflop_hand_strength,
)
from src.engine.game import Action, ActionType, GameState
from src.engine.player import Player
from src.llm.client import (
    LLMClient,
    LLMClientFactory,
    LLMCredentialError,
    LLMError,
    LLMResponse,
    LLMTimeoutError,
    MockClient,
)
from src.llm.config import LLMConfig, ProviderConfig, load_config
from src.llm.fallback import FallbackChain
from src.llm.prompt_builder import PromptBuilder
from src.llm.response_parser import ResponseParser
from src.utils.constants import GamePhase

logger = logging.getLogger(__name__)


class LLMBot(BoltzmannBot):
    """LLM 驱动的扑克机器人。

    继承 BotBase，覆写 decide() 方法接入 LLM 决策。
    降级机制确保 API 故障不影响游戏运行。

    Attributes:
        llm_client: 主力 LLM 客户端。
        fallback_chain: 多级降级链。
        call_frequency: LLM 调用频率策略。
        decision_log: 最近 N 次决策记录。
    """

    def __init__(
        self,
        name: str,
        llm_config: Optional[LLMConfig] = None,
        seed: int = 42,
    ) -> None:
        # 使用 Shark 配置作为降级基准（最接近 GTO）
        from src.ai.bots import BOT_PROFILES
        profile = BOT_PROFILES[BotStyle.SHARK]
        super().__init__(name, profile, seed)

        # LLM 配置
        self._llm_config = llm_config or load_config()
        self._llm_client: Optional[LLMClient] = None
        self._fallback_chain: FallbackChain = FallbackChain()
        self._setup_clients()

        # 降级规则引擎（SharkBot）
        self._rule_bot = BotFactory.create(BotStyle.SHARK, name=f"{name}_rule", seed=seed)
        self._fallback_chain.set_ultimate_fallback(
            lambda g, p: self._rule_bot.decide(g, p)
        )

        # 决策统计
        self.llm_decisions: int = 0
        self.rule_decisions: int = 0
        self.fallback_decisions: int = 0
        self._decision_log: List[Dict[str, Any]] = []
        self._max_log_size = self._llm_config.context_window_hands * 10

    def _setup_clients(self) -> None:
        """初始化 LLM 客户端和降级链。

        若 LLM 包未安装或 API key 未配置，自动降级为 MockClient，
        确保机器人始终可用（实际使用时会被规则引擎兜底）。
        """
        cfg = self._llm_config

        # 主力客户端
        try:
            self._llm_client = LLMClientFactory.create(cfg.primary)
        except (ImportError, ModuleNotFoundError) as e:
            logger.debug("LLM 包未安装 (%s)，使用 MockClient 降级", e)
            self._llm_client = MockClient()
        except Exception as e:
            logger.debug("无法创建主力 LLM 客户端 (%s)，使用 MockClient 降级", e)
            self._llm_client = MockClient()

        # 降级链
        for fb_cfg in cfg.fallbacks:
            try:
                self._fallback_chain.add_llm_fallback(fb_cfg)
            except Exception as e:
                logger.debug("无法添加降级客户端 %s: %s", fb_cfg.provider, e)

    # ================================================================
    # 核心决策
    # ================================================================

    def decide(self, game_state: GameState, player: Player) -> Action:
        """核心决策函数。

        根据 call_frequency 策略决定使用 LLM 还是规则引擎。

        Args:
            game_state: 当前游戏状态。
            player: 当前玩家（此机器人）。

        Returns:
            要执行的 Action。
        """
        self.hands_seen += 1

        # 检查是否需要 LLM
        if self._should_use_llm(game_state, player):
            action, used_fallback = self._llm_decide(game_state, player)
            if action is not None:
                if used_fallback:
                    self.fallback_decisions += 1
                    self._log_decision("fallback", action)
                else:
                    self.llm_decisions += 1
                    self._log_decision("llm", action)
                return action
            # LLM 和降级链均失败 → 规则引擎兜底
            self.fallback_decisions += 1
            return self._rule_decide(game_state, player)

        # 直接使用规则引擎
        self.rule_decisions += 1
        return self._rule_decide(game_state, player)

    def _llm_decide(self, game: GameState, player: Player) -> tuple:
        """使用 LLM 进行决策。

        Returns:
            (action, used_fallback): action 为合法的 Action（或 None），
            used_fallback 表示是否使用了降级链/规则引擎。
        """
        # 1. 构建 prompt
        hand_strength = postflop_hand_strength(player.hole_cards, game.community_cards)
        equity_pct = self._estimate_equity(game, player)
        opponent_stats = self._gather_opponent_stats(game)

        prompt = PromptBuilder.build_decision_prompt(
            game=game,
            player=player,
            hand_strength=hand_strength,
            equity_pct=equity_pct,
            opponent_stats=opponent_stats,
        )
        system_prompt = PromptBuilder.get_system_prompt()

        # 2. 尝试主力 LLM
        if self._llm_client is not None:
            try:
                response = self._llm_client.generate(prompt, system_prompt)
                if response and response.text:
                    action = ResponseParser.parse_action(response.text, player, game)
                    if action is not None:
                        logger.info(
                            "LLM 决策 (%s/%s, %.1fs): %s → %s",
                            self._llm_client.config.provider,
                            self._llm_client.config.model,
                            response.latency_seconds,
                            ResponseParser.extract_reasoning(response.text),
                            action,
                        )
                        return action, False
            except LLMTimeoutError:
                logger.warning("主力 LLM 超时，尝试降级链")
            except LLMCredentialError as e:
                logger.warning("主力 LLM 未配置 API Key，尝试降级链: %s", e)
            except LLMError as e:
                logger.warning("主力 LLM 错误: %s", e)

        # 3. 降级链
        action = self._fallback_chain.execute(prompt, system_prompt, game, player)
        if action is not None:
            return action, True

        return None, True

    def _rule_decide(self, game: GameState, player: Player) -> Action:
        """使用规则引擎（SharkBot）决策。"""
        action = self._rule_bot.decide(game, player)
        self._log_decision("rule", action)
        return action

    # ================================================================
    # 调用频率控制
    # ================================================================

    def _should_use_llm(self, game: GameState, player: Player) -> bool:
        """判断当前决策是否应使用 LLM。

        策略:
            every: 每次都调用 LLM。
            critical: 仅关键局面（大底池、河牌、面对全下、大波动）。
            mixed: 每 3 次 + 所有关键局面。
        """
        cfg = self._llm_config
        if cfg.call_frequency == "every":
            return True

        # 判断是否为关键局面
        is_critical = self._is_critical_decision(game, player)

        if cfg.call_frequency == "critical":
            return is_critical

        if cfg.call_frequency == "mixed":
            return is_critical or (self.hands_seen % 3 == 0)

        return False

    def _is_critical_decision(self, game: GameState, player: Player) -> bool:
        """判断是否为关键决策点。"""
        # 河牌决策
        if game.phase == GamePhase.RIVER:
            return True

        # 面对全下
        for p in game.players:
            if p.is_all_in and not p.is_folded:
                return True

        # 大底池（>= 30 BB）
        if game.pot.total >= game.big_blind * 30:
            return True

        # 自己筹码压力大（<= 20 BB）
        if player.chips <= game.big_blind * 20:
            return True

        # 手持顶级牌
        if is_premium_hand(player.hole_cards):
            return True

        # 有听牌（翻牌后）
        if game.phase != GamePhase.PRE_FLOP and len(game.community_cards) >= 3:
            flush_draw, straight_draw = has_draw(player.hole_cards, game.community_cards)
            if flush_draw or straight_draw:
                return True

        return False

    # ================================================================
    # 辅助方法
    # ================================================================

    def _estimate_equity(self, game: GameState, player: Player) -> float:
        """估算当前手牌胜率（基于 MC 胜率）。"""
        strength = postflop_hand_strength(player.hole_cards, game.community_cards)
        return strength * 100.0

    def _gather_opponent_stats(self, game: GameState) -> Dict[str, Dict[str, float]]:
        """收集对手统计数据（用于 Prompt 注入）。"""
        stats: Dict[str, Dict[str, float]] = {}
        for p in game.players:
            if p.is_human or p.status.value >= 3:  # OUT
                continue
            # 目前从 BotProfile 获取参数
            # 未来可从 HandReporter 获取真实统计
            stats[p.name] = {
                "vpip": 0.25,
                "pfr": 0.15,
                "aggression": 0.5,
            }
        return stats

    def _log_decision(self, source: str, action: Action) -> None:
        """记录决策到日志。"""
        entry = {
            "source": source,
            "action_type": action.action_type.name,
            "amount": action.amount,
            "is_all_in": action.is_all_in,
        }
        self._decision_log.append(entry)
        if len(self._decision_log) > self._max_log_size:
            self._decision_log = self._decision_log[-self._max_log_size:]

    # ================================================================
    # 统计与调试
    # ================================================================

    @property
    def decision_stats(self) -> Dict[str, Any]:
        """返回决策统计摘要。"""
        total = max(1, self.llm_decisions + self.rule_decisions + self.fallback_decisions)
        return {
            "total_decisions": total - 1 + 1,  # 避免除零
            "llm_decisions": self.llm_decisions,
            "rule_decisions": self.rule_decisions,
            "fallback_decisions": self.fallback_decisions,
            "llm_rate": round(self.llm_decisions / total, 3),
            "llm_client_stats": self._llm_client.stats if self._llm_client else {},
        }

    def __repr__(self) -> str:
        provider = self._llm_client.config.provider if self._llm_client else "none"
        model = self._llm_client.config.model if self._llm_client else "none"
        return f"LLMBot({self.name}, {provider}/{model})"
