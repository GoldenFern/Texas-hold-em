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
        # 新模型参数：对手建模
        F_max: float = 0.75,
        lambda_fold: float = 2.0,
        nu: float = 1.0,
        q_inf_ratio: float = 0.5,
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
        # 对手建模参数（统计物理启发）
        self.F_max = F_max              # 最大弃牌率
        self.lambda_fold = lambda_fold  # fold equity 对下注尺度的敏感度
        self.nu = nu                    # 对手跟注范围收紧速度
        self.q_inf_ratio = q_inf_ratio  # q_inf = max(0.05, win_rate * q_inf_ratio)

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

        # Bet / Raise（如果可用）—— 通过 EV 最大化搜索最优下注额
        bet_action = (
            ActionType.BET if ActionType.BET in legal
            else ActionType.RAISE if ActionType.RAISE in legal
            else None
        )
        if bet_action is not None and active_opponents >= 0:
            # 确定最小/最大合法下注增量（BB 单位）
            # _ev_bet 公式期望 x = 本轮新增投入（增量），非总下注额
            player_chips_bb = player.chips / bb
            if bet_action == ActionType.BET:
                min_r = game_state.big_blind / bb  # 主动下注 = BB
                max_bet_increment = player_chips_bb
            else:
                # RAISE: 增量为 max(min_raise, last_raise)，不含 to_call
                min_r = max(game_state.min_raise, game_state.last_raise) / bb
                max_bet_increment = player_chips_bb

            if min_r <= max_bet_increment:
                x_opt, ev_opt = self._find_optimal_bet(
                    pot, win_rate, active_opponents, min_r, max_bet_increment,
                )
                action_evs[bet_action] = ev_opt
                bet_sizes[bet_action] = x_opt

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

    def _q_inf(self, win_rate: float) -> float:
        """根据胜率计算底线胜率 q_inf（被最强范围 call 后的胜率）。

        强牌（w 高）被 call 后仍强 → q_inf 接近 w；
        弱牌（w 低）被 call 后几乎必输 → q_inf 接近 0。
        线性插值公式: q_inf = max(0.05, w * (1 - q_inf_ratio) + w^2 * q_inf_ratio)
        """
        w = win_rate
        # 用 q_inf_ratio 控制 w 的二次项权重：0=纯线性，1=纯平方
        q_inf = w * (1.0 - self.q_inf_ratio) + w * w * self.q_inf_ratio
        return max(0.05, min(w, q_inf))

    def _ev_bet(self, x: float, pot: float, win_rate: float, n_opponents: int) -> float:
        """计算下注 x BB 的期望收益（统计物理启发模型）。

        F(x) = F_max * (1 - exp(-lambda_fold * z))
        q(x) = q_inf + (w - q_inf) * exp(-nu * z)
        z = x / pot

        多人底池：使用期望跟注人数 n_call = n * (1-F)，近似为
        EV = Σ P(k callers) * [q * (P + (k+1)*x) - x]
           ≈ F^n * P + (1-F^n) * [q * (P + (1+E[k|k≥1])*x) - x]
        其中 E[k|k≥1] ≈ max(1, n*(1-F))（至少一人跟注时）
        """
        if n_opponents <= 0:
            return win_rate * (pot + 2 * x) - x
        if x <= 0 or pot <= 0:
            return win_rate * pot

        z = x / pot
        F = self.F_max * (1.0 - math.exp(-self.lambda_fold * z))
        fp = max(0.0, min(self.F_max, F))
        all_fold = fp ** n_opponents if n_opponents > 0 else 0.0

        # 条件胜率
        if self.nu > 1e-6:
            q_inf = self._q_inf(win_rate)
            q = q_inf + (win_rate - q_inf) * math.exp(-self.nu * z)
        else:
            q = win_rate

        # 期望跟注人数（至少一人时）
        exp_callers = max(1.0, n_opponents * (1.0 - fp))
        ev_called = q * (pot + (1.0 + exp_callers) * x) - x
        return all_fold * pot + (1.0 - all_fold) * ev_called

    def _find_optimal_bet(
        self, pot: float, win_rate: float, n_opponents: int,
        min_bet: float, max_bet: float, n_candidates: int = 15,
    ) -> tuple[float, float]:
        """搜索最优下注额 x* = argmax EV_raise(x)。

        在 [min_bet, max_bet] 内搜索最大化 EV 的下注额。
        候选点包括标准尺度 (1/4P, 1/3P, 1/2P, 2/3P, 3/4P, P, 1.5P, 2P) + all-in。
        """
        if min_bet >= max_bet:
            x_best = max_bet
            return x_best, self._ev_bet(x_best, pot, win_rate, n_opponents)

        # 候选下注尺度
        fractions = [0.25, 0.33, 0.50, 0.67, 0.75, 1.0, 1.25, 1.5, 2.0]
        candidates = []
        for frac in fractions:
            x = frac * pot
            if min_bet <= x <= max_bet:
                candidates.append(x)
        # 始终加入边界
        if min_bet not in candidates:
            candidates.append(min_bet)
        if max_bet not in candidates:
            candidates.append(max_bet)

        # 评估所有候选
        best_x = min_bet
        best_ev = float("-inf")
        for x in sorted(candidates):
            ev = self._ev_bet(x, pot, win_rate, n_opponents)
            if ev > best_ev:
                best_ev = ev
                best_x = x

        return best_x, best_ev

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
               temperature: float | None = None) -> BoltzmannBot:
        """创建指定风格的 Boltzmann-EV Bot。
        
        Args:
            temperature: 自定义温度（若 None 则使用风格预设值）。
        """
        if style == BotStyle.LLM:
            from src.llm.llm_bot import LLMBot
            return LLMBot(name or "LLM", seed=seed)

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
        import zlib
        styles = [
            BotStyle.COLD, BotStyle.COOL, BotStyle.BALANCED,
            BotStyle.WARM, BotStyle.HOT, BotStyle.CHAOS,
        ]
        return [cls.create(s, seed=zlib.crc32(s.value.encode()) % 10000) for s in styles]

    @classmethod
    def list_styles(cls) -> List[BotProfile]:
        return [p for s, p in BOT_PROFILES.items() if s != BotStyle.LLM]


