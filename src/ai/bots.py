"""AI 机器人 —— 6 种不同风格的德州扑克陪玩机器人。

风格：
    TAG — 紧凶型：只玩好牌，一旦入池则极具侵略性。
    LAG — 松凶型：玩很多牌，持续施压。
    Nit — 极紧型：只玩顶级牌（AA/KK/QQ/AK）。
    CallingStation — 跟注站：几乎不弃牌，极少加注。
    Maniac — 疯子型：几乎每手都玩，疯狂加注和诈唬。
    Shark — 鲨鱼型：接近 GTO 的平衡打法，自适应调整。
"""

from __future__ import annotations

import random
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

from src.ai.strategy import (
    calculate_pot_odds,
    has_draw,
    is_premium_hand,
    postflop_hand_strength,
    preflop_hand_strength,
    randomize_action,
)
from src.engine.card import Cards
from src.engine.game import Action, ActionType, GameState
from src.engine.player import Player
from src.utils.constants import GamePhase


class BotStyle(Enum):
    """机器人风格枚举。"""

    TAG = "TAG"
    LAG = "LAG"
    NIT = "NIT"
    CALLING_STATION = "CALLING_STATION"
    MANIAC = "MANIAC"
    SHARK = "SHARK"
    LLM = "LLM"  # LLM 驱动的自适应机器人


@dataclass
class BotProfile:
    """机器人参数配置。"""

    style: BotStyle

    # 翻牌前入场门槛（手牌强度 0–100）
    vpip_threshold: int
    # 3-bet / 加注倾向 (0.0–1.0)
    aggression: float
    # 诈唬频率 (0.0–1.0)
    bluff_frequency: float
    # 面对加注时的弃牌倾向 (0.0–1.0)
    fold_to_raise: float
    # 持续下注 (c-bet) 频率 (0.0–1.0)
    cbet_frequency: float
    # 位置敏感度 (0.0–1.0)
    position_sensitivity: float

    # 显示
    display_name: str = ""
    description: str = ""


# 预定义机器人配置
BOT_PROFILES: Dict[BotStyle, BotProfile] = {
    BotStyle.TAG: BotProfile(
        style=BotStyle.TAG,
        vpip_threshold=40,
        aggression=0.75,
        bluff_frequency=0.15,
        fold_to_raise=0.4,
        cbet_frequency=0.8,
        position_sensitivity=0.7,
        display_name="紧凶型 (TAG)",
        description="只玩好牌，一旦入池极具侵略性。",
    ),
    BotStyle.LAG: BotProfile(
        style=BotStyle.LAG,
        vpip_threshold=25,
        aggression=0.9,
        bluff_frequency=0.3,
        fold_to_raise=0.2,
        cbet_frequency=0.9,
        position_sensitivity=0.6,
        display_name="松凶型 (LAG)",
        description="玩很多牌，持续施加压力。",
    ),
    BotStyle.NIT: BotProfile(
        style=BotStyle.NIT,
        vpip_threshold=70,
        aggression=0.5,
        bluff_frequency=0.02,
        fold_to_raise=0.7,
        cbet_frequency=0.6,
        position_sensitivity=0.3,
        display_name="极紧型 (Nit)",
        description="只玩顶级强牌，超级保守。",
    ),
    BotStyle.CALLING_STATION: BotProfile(
        style=BotStyle.CALLING_STATION,
        vpip_threshold=0,
        aggression=0.05,
        bluff_frequency=0.01,
        fold_to_raise=0.03,
        cbet_frequency=0.1,
        position_sensitivity=0.05,
        display_name="跟注站 (Calling Station)",
        description="几乎从不弃牌，极少加注。",
    ),
    BotStyle.MANIAC: BotProfile(
        style=BotStyle.MANIAC,
        vpip_threshold=10,
        aggression=0.95,
        bluff_frequency=0.6,
        fold_to_raise=0.02,
        cbet_frequency=0.95,
        position_sensitivity=0.05,
        display_name="疯子型 (Maniac)",
        description="任何两张牌都玩，疯狂加注和诈唬。",
    ),
    BotStyle.SHARK: BotProfile(
        style=BotStyle.SHARK,
        vpip_threshold=35,
        aggression=0.65,
        bluff_frequency=0.2,
        fold_to_raise=0.35,
        cbet_frequency=0.75,
        position_sensitivity=0.85,
        display_name="鲨鱼型 (Shark)",
        description="接近 GTO 的平衡打法，善用位置优势。",
    ),
    BotStyle.LLM: BotProfile(
        style=BotStyle.LLM,
        vpip_threshold=35,
        aggression=0.65,
        bluff_frequency=0.2,
        fold_to_raise=0.35,
        cbet_frequency=0.75,
        position_sensitivity=0.85,
        display_name="LLM 自适应 (AI)",
        description="基于大语言模型的智能决策，自适应调整策略。",
    ),
}


class BotBase(ABC):
    """机器人基类。

    每个机器人风格通过调整阈值和行为概率来实现差异化。
    """

    def __init__(self, name: str, profile: BotProfile, seed: int = 42) -> None:
        self.name = name
        self.profile = profile
        self.rng = random.Random(seed)

        # 运行时统计
        self.hands_seen: int = 0
        self.hands_played: int = 0
        self.total_aggressive_actions: int = 0

    @property
    def style(self) -> BotStyle:
        return self.profile.style

    def decide(self, game_state: GameState, player: Player) -> Action:
        """核心决策函数。

        根据游戏阶段、手牌强度、底池赔率和机器人风格
        决定当前最佳动作。

        Args:
            game_state: 当前游戏状态。
            player: 此机器人对应的玩家。

        Returns:
            要执行的动作。
        """
        self.hands_seen += 1
        legal = game_state.get_legal_actions(player)
        if not legal:
            return Action(player.name, ActionType.FOLD)

        # 仅有一个合法动作时直接执行
        if len(legal) == 1:
            action_type = legal[0]
            return self._make_action(player, game_state, action_type)

        hole_cards = player.hole_cards
        community = game_state.community_cards
        pf_strength = preflop_hand_strength(hole_cards)
        pot_odds = self._get_pot_odds(game_state, player)
        hand_strength = postflop_hand_strength(hole_cards, community)

        # 分阶段决策
        if game_state.phase == GamePhase.PRE_FLOP:
            action_type = self._decide_preflop(
                legal, pf_strength, pot_odds, game_state, player
            )
        else:
            action_type = self._decide_postflop(
                legal, hand_strength, pot_odds, game_state, player
            )

        return self._make_action(player, game_state, action_type)

    def _decide_preflop(
        self,
        legal: List[ActionType],
        pf_strength: int,
        pot_odds: float,
        game_state: GameState,
        player: Player,
    ) -> ActionType:
        """翻牌前决策。"""
        profile = self.profile
        threshold = profile.vpip_threshold

        # 位置调整
        pos_adj = self._position_adjustment(game_state, player)
        threshold = int(threshold * (1.0 - pos_adj * profile.position_sensitivity))

        can_check = ActionType.CHECK in legal
        can_raise = ActionType.RAISE in legal or ActionType.BET in legal
        to_call = game_state.current_bet - player.current_bet

        # 已经在大盲位且无人加注 → 倾向于看翻牌
        if can_check and to_call == 0:
            # 随机加注（挤压打法）
            if can_raise and pf_strength >= threshold:
                if self.rng.random() < profile.aggression * 0.4:
                    return ActionType.RAISE
            return ActionType.CHECK

        # 手牌强度不足 → 按 fold_to_raise 决定弃牌概率
        if pf_strength < threshold:
            if to_call == 0:
                return ActionType.CHECK
            # fold_to_raise 主导弃牌决策
            if self.rng.random() < profile.fold_to_raise:
                return ActionType.FOLD
            # 诈唬加注
            if can_raise and self.rng.random() < profile.bluff_frequency:
                return ActionType.RAISE
            # 否则跟注
            if ActionType.CALL in legal:
                return ActionType.CALL
            return ActionType.FOLD

        # 手牌足够好
        # 顶级牌 → 总是加注/再加注
        if is_premium_hand(player.hole_cards) or pf_strength >= 70:
            if can_raise:
                return ActionType.RAISE
            return ActionType.CALL

        # 好牌但非顶级 → 按侵略性决定
        if can_raise:
            if self.rng.random() < profile.aggression:
                return ActionType.RAISE
            return ActionType.CALL

        return ActionType.CALL

    def _decide_postflop(
        self,
        legal: List[ActionType],
        hand_strength: float,
        pot_odds: float,
        game_state: GameState,
        player: Player,
    ) -> ActionType:
        """翻牌后决策。"""
        profile = self.profile
        can_check = ActionType.CHECK in legal
        can_raise = ActionType.RAISE in legal or ActionType.BET in legal
        to_call = game_state.current_bet - player.current_bet

        # 听牌检测
        flush_draw, straight_draw = has_draw(player.hole_cards, game_state.community_cards)
        has_draw_potential = flush_draw or straight_draw

        # 强牌 (>= 0.6 → 两对或更好)
        if hand_strength >= 0.6:
            if can_raise:
                if self.rng.random() < profile.aggression:
                    return ActionType.RAISE
            return ActionType.CALL if to_call > 0 else ActionType.CHECK

        # 中等牌力或有听牌
        if hand_strength >= 0.3 or has_draw_potential:
            # 计算隐含赔率
            effective_odds = pot_odds * (0.7 if has_draw_potential else 1.0)
            if effective_odds < 0.35:  # 赔率合适
                if can_raise and self.rng.random() < profile.cbet_frequency:
                    if game_state.phase == GamePhase.FLOP and len(game_state.actions_this_round) == 0:
                        return ActionType.BET  # c-bet
                    if self.rng.random() < profile.aggression * 0.5:
                        return ActionType.RAISE
                return ActionType.CALL if to_call > 0 else ActionType.CHECK

            # 赔率不合适但可能有隐含赔率
            if has_draw_potential and to_call <= game_state.big_blind * 3:
                return ActionType.CALL

            # 诈唬
            if can_raise and self.rng.random() < profile.bluff_frequency:
                return ActionType.BET if ActionType.BET in legal else ActionType.RAISE

        # 弱牌
        if to_call == 0:
            # 免费看牌
            if can_raise and self.rng.random() < profile.bluff_frequency * 0.5:
                return ActionType.BET
            return ActionType.CHECK

        # 需要跟注 → 弃牌或跟注
        if to_call <= game_state.big_blind:  # 极小额下注
            return ActionType.CALL

        if can_raise and self.rng.random() < profile.bluff_frequency * 0.3:
            return ActionType.RAISE

        return ActionType.FOLD

    def _make_action(
        self,
        player: Player,
        game_state: GameState,
        action_type: ActionType,
    ) -> Action:
        """根据动作类型构造 Action 对象（含合理金额）。"""
        if action_type in (ActionType.FOLD, ActionType.CHECK):
            return Action(player_name=player.name, action_type=action_type)

        if action_type == ActionType.CALL:
            return Action(player_name=player.name, action_type=ActionType.CALL)

        # BET / RAISE
        if action_type in (ActionType.BET, ActionType.RAISE):
            to_call = game_state.current_bet - player.current_bet
            min_raise = game_state.get_min_raise_amount(player)
            max_bet = game_state.get_max_bet(player)

            if min_raise >= player.chips + player.current_bet:
                return Action(
                    player.name, action_type,
                    amount=player.chips + player.current_bet,
                    is_all_in=True,
                )

            # 选择合理的加注额
            profile = self.profile

            # 标准加注：底池的 50%–100%
            pot_sized = int(game_state.pot.total * (0.5 + 0.5 * profile.aggression))
            bet_amount = max(min_raise, min(pot_sized, max_bet))

            # 偶尔超池下注（侵略型）
            if self.rng.random() < profile.aggression * 0.3:
                bet_amount = int(bet_amount * 1.5)

            bet_amount = min(bet_amount, max_bet)
            bet_amount = max(bet_amount, min_raise)
            bet_amount = min(bet_amount, player.chips + player.current_bet)

            is_all_in = bet_amount >= player.chips + player.current_bet
            return Action(
                player.name, action_type,
                amount=bet_amount,
                is_all_in=is_all_in,
            )

        return Action(player.name, ActionType.FOLD)

    def _get_pot_odds(self, game_state: GameState, player: Player) -> float:
        """计算当前跟注的底池赔率。"""
        to_call = game_state.current_bet - player.current_bet
        if to_call <= 0:
            return 0.0
        return calculate_pot_odds(to_call, game_state.pot.total)

    def _position_adjustment(
        self, game_state: GameState, player: Player
    ) -> float:
        """计算位置质量因子（0.0–1.0，越高位置越好）。

        正确处理非连续座位（有玩家淘汰时座位号不连续）。
        """
        active_players = [p for p in game_state.players if p.chips > 0]
        n = len(active_players)
        if n <= 2:
            return 0.5
        if player.seat == game_state.dealer_index:
            return 1.0  # 庄位最佳

        # 按座位号排序活跃玩家
        sorted_seats = sorted(p.seat for p in active_players)
        try:
            dealer_pos = sorted_seats.index(game_state.dealer_index)
        except ValueError:
            return 0.5
        try:
            player_pos = sorted_seats.index(player.seat)
        except ValueError:
            return 0.5

        # 计算庄位之后的位置偏移（顺时针），越大位置越差
        offset = (player_pos - dealer_pos) % n
        # 返回位置质量：距离庄位越近越高
        return max(0.0, 1.0 - offset / n)

    def reset_stats(self) -> None:
        """重置统计数据。"""
        self.hands_seen = 0
        self.hands_played = 0
        self.total_aggressive_actions = 0

    def __repr__(self) -> str:
        return f"{self.profile.display_name} ({self.name})"


# ================================================================
# 具体机器人子类（可进一步定制）
# ================================================================

class TAGBot(BotBase):
    """紧凶型机器人。"""

    def __init__(self, name: str = "TAG", seed: int = 42) -> None:
        super().__init__(name, BOT_PROFILES[BotStyle.TAG], seed)


class LAGBot(BotBase):
    """松凶型机器人。"""

    def __init__(self, name: str = "LAG", seed: int = 42) -> None:
        super().__init__(name, BOT_PROFILES[BotStyle.LAG], seed)


class NitBot(BotBase):
    """极紧型机器人。"""

    def __init__(self, name: str = "Nit", seed: int = 42) -> None:
        super().__init__(name, BOT_PROFILES[BotStyle.NIT], seed)


class CallingStationBot(BotBase):
    """跟注站机器人。"""

    def __init__(self, name: str = "CallingStation", seed: int = 42) -> None:
        super().__init__(name, BOT_PROFILES[BotStyle.CALLING_STATION], seed)


class ManiacBot(BotBase):
    """疯子型机器人。"""

    def __init__(self, name: str = "Maniac", seed: int = 42) -> None:
        super().__init__(name, BOT_PROFILES[BotStyle.MANIAC], seed)


class SharkBot(BotBase):
    """鲨鱼型机器人。"""

    def __init__(self, name: str = "Shark", seed: int = 42) -> None:
        super().__init__(name, BOT_PROFILES[BotStyle.SHARK], seed)


# ================================================================
# 工厂
# ================================================================

class BotFactory:
    """机器人工厂。"""

    _STYLE_MAP: Dict[BotStyle, type] = {
        BotStyle.TAG: TAGBot,
        BotStyle.LAG: LAGBot,
        BotStyle.NIT: NitBot,
        BotStyle.CALLING_STATION: CallingStationBot,
        BotStyle.MANIAC: ManiacBot,
        BotStyle.SHARK: SharkBot,
    }

    @classmethod
    def create(cls, style: BotStyle, name: str = "", seed: int = 42) -> BotBase:
        """创建指定风格的机器人。"""
        if style == BotStyle.LLM:
            from src.llm.llm_bot import LLMBot
            name = name or "LLM"
            return LLMBot(name, seed=seed)

        bot_cls = cls._STYLE_MAP.get(style)
        if bot_cls is None:
            raise ValueError(f"未知的机器人风格: {style}")
        name = name or style.value
        return bot_cls(name, seed)

    @classmethod
    def create_llm(
        cls,
        name: str = "LLM",
        provider: str = "anthropic",
        model: str = "",
        seed: int = 42,
    ) -> BotBase:
        """便捷方法：创建 LLM 驱动的机器人。

        Args:
            name: 机器人名称。
            provider: LLM 提供商 ("anthropic", "openai", "ollama", "mock")。
            model: 模型标识符（空则使用默认）。
            seed: 随机种子。

        Returns:
            LLMBot 实例。
        """
        from src.llm.llm_bot import LLMBot
        from src.llm.config import LLMConfig, ProviderConfig, load_config

        if provider == "mock" or model == "mock":
            # 测试用 Mock
            llm_config = LLMConfig()
            llm_config.primary = ProviderConfig(provider="mock", model="mock")
            return LLMBot(name, llm_config, seed)

        llm_config = load_config()
        if provider:
            llm_config.primary.provider = provider
        if model:
            llm_config.primary.model = model
        return LLMBot(name, llm_config, seed)

    @classmethod
    def create_all_styles(cls) -> List[BotBase]:
        """创建所有 6 种风格的机器人。"""
        bots = []
        for style in BotStyle:
            bots.append(cls.create(style, seed=hash(style.value) % 10000))
        return bots

    @classmethod
    def list_styles(cls) -> List[BotProfile]:
        """列出所有可用的机器人风格。"""
        return list(BOT_PROFILES.values())
