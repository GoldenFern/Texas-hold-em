"""AI 机器人 —— Boltzmann-EV 统一决策引擎。

所有 Bot 使用同一算法：计算各合法动作的期望收益（EV），然后通过
玻尔兹曼分布 P ∝ exp(EV/T) 采样。温度 T 是唯一个性参数。

风格预设（仅温度不同，名称反映决策的"温度"而非传统扑克风格）：
    COLD (0.03) — 极冷，近乎确定性地选最优动作
    COOL (0.07) — 偏冷，明显偏好高 EV
    BALANCED (0.15) — 温和均衡，默认值
    WARM (0.30) — 偏热，EV 差异被部分抹平
    HOT (0.60) — 炎热，Fold 的 EV 优势不明显
    CHAOS (1.20) — 极热/混沌，近乎均匀随机
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

from src.ai.strategy import preflop_hand_strength
from src.analysis.battle_analyzer import BattleAnalyzer
from src.engine.card import Cards
from src.engine.game import Action, ActionType, GameState
from src.engine.player import Player
from src.utils.constants import GamePhase


class BotStyle(Enum):
    """机器人风格枚举 —— 按温度命名，反映决策的随机性程度。"""

    COLD = "COLD"           # T=0.03  极冷
    COOL = "COOL"           # T=0.07  偏冷
    BALANCED = "BALANCED"   # T=0.15  均衡（默认）
    WARM = "WARM"           # T=0.30  偏热
    HOT = "HOT"             # T=0.60  炎热
    CHAOS = "CHAOS"         # T=1.20  混沌
    LLM = "LLM"
    RLCARD = "RLCARD"


@dataclass
class BotProfile:
    """机器人参数配置——仅温度。"""

    style: BotStyle
    temperature: float  # BB 单位
    display_name: str = ""
    description: str = ""


# 温度预设（pot 标度系数；T = coefficient * pot, 单位 BB）
BOT_PROFILES: Dict[BotStyle, BotProfile] = {
    BotStyle.COLD: BotProfile(
        style=BotStyle.COLD, temperature=0.03,
        display_name="极冷 T=0.03",
        description="近乎确定性，只选 EV 最高的动作。",
    ),
    BotStyle.COOL: BotProfile(
        style=BotStyle.COOL, temperature=0.07,
        display_name="偏冷 T=0.07",
        description="明显偏好高 EV 动作，中强牌入池。",
    ),
    BotStyle.BALANCED: BotProfile(
        style=BotStyle.BALANCED, temperature=0.15,
        display_name="均衡 T=0.15",
        description="温和均衡，EV 驱动决策。",
    ),
    BotStyle.WARM: BotProfile(
        style=BotStyle.WARM, temperature=0.30,
        display_name="偏热 T=0.30",
        description="EV 差异被部分抹平，更爱探索和施压。",
    ),
    BotStyle.HOT: BotProfile(
        style=BotStyle.HOT, temperature=0.60,
        display_name="炎热 T=0.60",
        description="Fold 的 EV 优势不明显，几乎不弃牌。",
    ),
    BotStyle.CHAOS: BotProfile(
        style=BotStyle.CHAOS, temperature=1.20,
        display_name="混沌 T=1.20",
        description="近乎均匀随机，无视牌力。",
    ),
    BotStyle.LLM: BotProfile(
        style=BotStyle.LLM, temperature=0.15,
        display_name="LLM",
        description="LLM 驱动。",
    ),
    BotStyle.RLCARD: BotProfile(
        style=BotStyle.RLCARD, temperature=0.15,
        display_name="算无遗策",
        description="RLCard 强化学习驱动。",
    ),
}

# 风格显示名 -> BotStyle 映射
STYLE_IDIOM_MAP: Dict[str, BotStyle] = {
    "极冷 T=0.03": BotStyle.COLD,
    "偏冷 T=0.07": BotStyle.COOL,
    "均衡 T=0.15": BotStyle.BALANCED,
    "偏热 T=0.30": BotStyle.WARM,
    "炎热 T=0.60": BotStyle.HOT,
    "混沌 T=1.20": BotStyle.CHAOS,
    "LLM": BotStyle.LLM,
    "算无遗策": BotStyle.RLCARD,
}


class BoltzmannBot:
    """Boltzmann-EV 统一决策 Bot。

    所有合法动作计算 EV（BB 单位），通过 P ∝ exp(EV/T) 采样。
    温度 T 是唯一的风格参数。
    """

    def __init__(
        self, name: str, profile: BotProfile,
        seed: int = 42,
        postflop_sims: int = 200,
        bet_k_value: float = 0.6,
        bet_k_bluff: float = 0.65,
        bet_cap_frac: float = 0.75,
        bet_strategy: str = "separated",
    ) -> None:
        self.name = name
        self.profile = profile
        self.rng = random.Random(seed)
        # 翻牌后 MC 分析器（200 次），翻牌前跳过 MC
        self.analyzer = BattleAnalyzer(
            preflop_sims=0, postflop_sims=postflop_sims, seed=seed,
        )
        # 下注参数
        self.bet_k_value = bet_k_value
        self.bet_k_bluff = bet_k_bluff
        self.bet_cap_frac = bet_cap_frac
        self.bet_strategy = bet_strategy  # "blended", "value_only", "separated"

        self.hands_seen: int = 0

    @property
    def style(self) -> BotStyle:
        return self.profile.style

    @property
    def temperature(self) -> float:
        return self.profile.temperature

    # ---- 主决策入口 ----

    def decide(self, game_state: GameState, player: Player) -> Action:
        """核心决策：评估各动作 EV -> 玻尔兹曼采样。"""
        self.hands_seen += 1
        legal = game_state.get_legal_actions(player)
        if not legal:
            return Action(player.name, ActionType.FOLD)
        if len(legal) == 1:
            return Action(player.name, legal[0])

        # 获取 win_rate 和 pot 数据
        bb = game_state.big_blind
        hole_cards = player.hole_cards
        community = game_state.community_cards
        active_opponents = sum(
            1 for p in game_state.players
            if not p.is_folded and p.name != player.name and p.status.value < 3
        )
        pot = game_state.pot.total / bb
        to_call = max(0, game_state.current_bet - player.current_bet) / bb
        player_bet = player.current_bet / bb
        max_bet = game_state.get_max_bet(player) / bb

        # 胜率：翻牌前查表，翻牌后 MC
        if game_state.phase == GamePhase.PRE_FLOP:
            raw_equity = preflop_hand_strength(hole_cards) / 100.0
            # 多人底池修正：指数衰减近似（查表值基于 vs 1 个对手）
            if active_opponents > 1:
                win_rate = raw_equity ** (1.0 + 0.3 * (active_opponents - 1))
            else:
                win_rate = raw_equity
        else:
            analysis = self.analyzer.analyze(
                hole_cards, community, active_opponents, game_state, player,
            )
            dist = analysis.get("ranking_distribution", [])
            win_rate = dist[0]["prob"] / 100.0 if dist else 0.5

        # 计算各动作 EV
        action_evs: Dict[ActionType, float] = {}
        bet_sizes: Dict[ActionType, float] = {}  # Bet/Raise 对应的下注额

        # Fold
        action_evs[ActionType.FOLD] = 0.0

        # Check（如果可用）
        if ActionType.CHECK in legal:
            action_evs[ActionType.CHECK] = win_rate * pot

        # Call（如果可用）
        if ActionType.CALL in legal and to_call > 0:
            action_evs[ActionType.CALL] = win_rate * (pot + to_call) - to_call

        # Bet / Raise（如果可用）——胜率驱动下注额（含 value + bluff）
        bet_action = (
            ActionType.BET if ActionType.BET in legal
            else ActionType.RAISE if ActionType.RAISE in legal
            else None
        )
        if bet_action is not None and active_opponents >= 0:
            cap = self.bet_cap_frac * pot  # 下注上限（pot 的倍数）

            if self.bet_strategy == "value_only":
                # 纯价值下注：下注额与胜率成正比
                x = win_rate * self.bet_k_value * pot

            elif self.bet_strategy == "separated":
                # 分离策略：强牌 value，弱牌 bluff（固定比例）
                if win_rate > 0.55:
                    x = win_rate * self.bet_k_value * pot  # 价值下注
                else:
                    x = self.bet_k_bluff * pot  # 诈唬下注（固定大小）

            else:  # "blended"（默认/当前策略）
                x_value = win_rate * self.bet_k_value * pot
                x_bluff = (1.0 - win_rate) * self.bet_k_bluff * pot * 0.5
                x = x_value + x_bluff

            x = min(x, cap)  # 上限不超过 cap

            # 确定最小合法下注额
            if bet_action == ActionType.BET:
                min_r = game_state.big_blind / bb  # 主动下注 = BB
            else:
                min_r = game_state.get_min_raise_amount(player) / bb  # 加注 = min_raise

            if x >= min_r and min_r <= max_bet:
                # 下注额合法：上限截断（隐含 all-in），无 all-in 候选人
                x = min(x, max_bet)
                ev = self._ev_bet(x, pot, win_rate, active_opponents)
                action_evs[bet_action] = ev
                bet_sizes[bet_action] = x

        # Check 存在时移除 Fold（Fold 严格不优于 Check）
        if ActionType.CHECK in legal and ActionType.FOLD in action_evs:
            del action_evs[ActionType.FOLD]

        # 玻尔兹曼采样（T 以 pot 标度：概率比在不同 pot 下保持恒定）
        T = self.temperature * pot  # pot-scale coefficient -> actual temperature in BB
        # 数值稳定：减去最大 EV
        max_ev = max(action_evs.values())
        weights = {a: math.exp((e - max_ev) / T) for a, e in action_evs.items()}
        total = sum(weights.values())

        r = self.rng.random() * total
        cumulative = 0.0
        chosen = list(action_evs.keys())[0]  # fallback
        for action, w in weights.items():
            cumulative += w
            if r <= cumulative:
                chosen = action
                break

        # 构造 Action
        return self._build_action(player, game_state, chosen, bet_sizes.get(chosen, 0), bb)

    # ---- Bet EV 计算 ----

    def _ev_bet(self, x: float, pot: float, win_rate: float, n_opponents: int) -> float:
        """计算下注 X BB 的期望收益。

        f(X) = min(0.8, X / (X + 0.5 * pot))
        每个对手独立以概率 f 弃牌。
        """
        if n_opponents <= 0:
            return win_rate * (pot + 2 * x) - x  # 无人可弃，纯粹价值下注
        fp = min(0.8, x / (x + 0.5 * pot))
        all_fold = fp ** n_opponents
        return all_fold * pot + (1 - all_fold) * (win_rate * (pot + 2 * x) - x)

    # ---- Action 构造 ----

    def _build_action(
        self, player: Player, game_state: GameState,
        action_type: ActionType, bet_size_bb: float, bb: int,
    ) -> Action:
        """根据动作类型构造 Action 对象。"""
        if action_type in (ActionType.FOLD, ActionType.CHECK):
            return Action(player.name, action_type)

        if action_type == ActionType.CALL:
            return Action(player.name, ActionType.CALL)

        # BET / RAISE
        amount = int(bet_size_bb * bb)
        to_call = game_state.current_bet - player.current_bet
        if action_type == ActionType.RAISE:
            # Raise 时 amount 应该是 total bet（含 current_bet）
            amount = to_call + amount
        amount = max(amount, game_state.get_min_raise_amount(player))
        amount = min(amount, game_state.get_max_bet(player))
        amount = min(amount, player.chips + player.current_bet)

        is_all_in = amount >= player.chips + player.current_bet
        return Action(player.name, action_type, amount=amount, is_all_in=is_all_in)

    # ---- 统计 ----

    def reset_stats(self) -> None:
        self.hands_seen = 0

    def __repr__(self) -> str:
        return f"{self.profile.display_name} ({self.name}, T={self.temperature:.2f}*pot)"


# ================================================================
# 工厂
# ================================================================

class BotFactory:
    """机器人工厂 —— 接口不变，内部统一创建 BoltzmannBot。"""

    @classmethod
    def create(cls, style: BotStyle, name: str = "", seed: int = 42,
               temperature: float | None = None,
               rlcard_config: dict | None = None) -> BoltzmannBot:
        """创建指定风格的 Boltzmann-EV Bot。

        Args:
            temperature: 自定义温度（若 None 则使用风格预设值）。
            rlcard_config: bot 级别的 RLCard 配置覆盖字典。
        """
        if style == BotStyle.LLM:
            from src.llm.llm_bot import LLMBot
            return LLMBot(name or "LLM", seed=seed)

        if style == BotStyle.RLCARD:
            from src.rlcard.rlcard_bot import RLCardBot
            from src.rlcard.config import load_rlcard_config
            rl_config = load_rlcard_config(bot_override=rlcard_config)
            return RLCardBot(name or "RLCard", seed=seed, rlcard_config=rl_config)

        profile = BOT_PROFILES.get(style)
        if profile is None:
            raise ValueError(f"未知的机器人风格: {style}")
        name = name or style.value
        if temperature is not None:
            profile = BotProfile(
                style=profile.style, temperature=temperature,
                display_name=profile.display_name, description=profile.description,
            )
        return BoltzmannBot(name, profile, seed)

    @classmethod
    def create_llm(
        cls, name: str = "LLM", provider: str = "anthropic",
        model: str = "", seed: int = 42,
    ) -> BoltzmannBot:
        """创建 LLM Bot。"""
        from src.llm.llm_bot import LLMBot
        from src.llm.config import LLMConfig, ProviderConfig, load_config

        if provider == "mock" or model == "mock":
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
    def create_all_styles(cls) -> List[BoltzmannBot]:
        """创建所有 6 种温度的 Boltzmann Bot。"""
        styles = [
            BotStyle.COLD, BotStyle.COOL, BotStyle.BALANCED,
            BotStyle.WARM, BotStyle.HOT, BotStyle.CHAOS,
        ]
        return [cls.create(s, seed=hash(s.value) % 10000) for s in styles]

    @classmethod
    def list_styles(cls) -> List[BotProfile]:
        styles: List[BotProfile] = []
        for s, p in BOT_PROFILES.items():
            if s == BotStyle.LLM:
                continue
            if s == BotStyle.RLCARD:
                from src.rlcard import is_available
                if not is_available():
                    continue
            styles.append(p)
        return styles


