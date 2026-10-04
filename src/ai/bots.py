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

import json
import math
import os
import random
from dataclasses import dataclass, replace
from enum import Enum
from typing import Dict, List, Optional, Sequence, Tuple

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
    """机器人参数配置 —— 温度 + Boltzmann 报告的对手响应参数。"""

    style: BotStyle
    temperature: float          # softmax 温度系数 (T = τ·pot)
    display_name: str = ""
    description: str = ""
    F_max: float = 0.68         # 对手弃牌率上限
    lambda_fold: float = 1.8    # fold equity 饱和速率
    nu: float = 1.2             # 跟注范围收紧速率
    q_delta: float = 0.15       # 被跟注后的胜率折减: q_inf = max(0.05, w - q_delta)


# 内置默认参数（docs/boltzmann_report.tex 实用参数建议）；
# config/bot_profiles.json 存在时覆盖同名字段
_BUILTIN_PROFILES: Dict[BotStyle, BotProfile] = {
    BotStyle.COLD: BotProfile(
        style=BotStyle.COLD, temperature=0.03,
        display_name="极冷 T=0.03",
        description="近乎确定性，只选 EV 最高的动作。",
        F_max=0.75, lambda_fold=2.0, nu=2.2, q_delta=0.30,
    ),
    BotStyle.COOL: BotProfile(
        style=BotStyle.COOL, temperature=0.07,
        display_name="偏冷 T=0.07",
        description="明显偏好高 EV 动作，中强牌入池。",
        F_max=0.72, lambda_fold=2.0, nu=1.5, q_delta=0.20,
    ),
    BotStyle.BALANCED: BotProfile(
        style=BotStyle.BALANCED, temperature=0.15,
        display_name="均衡 T=0.15",
        description="温和均衡，EV 驱动决策。",
        F_max=0.68, lambda_fold=1.8, nu=1.2, q_delta=0.15,
    ),
    BotStyle.WARM: BotProfile(
        style=BotStyle.WARM, temperature=0.30,
        display_name="偏热 T=0.30",
        description="EV 差异被部分抹平，更爱探索和施压。",
        F_max=0.62, lambda_fold=1.5, nu=1.0, q_delta=0.10,
    ),
    BotStyle.HOT: BotProfile(
        style=BotStyle.HOT, temperature=0.60,
        display_name="炎热 T=0.60",
        description="Fold 的 EV 优势不明显，几乎不弃牌。",
        F_max=0.55, lambda_fold=1.0, nu=0.6, q_delta=0.05,
    ),
    BotStyle.CHAOS: BotProfile(
        style=BotStyle.CHAOS, temperature=1.20,
        display_name="混沌 T=1.20",
        description="近乎均匀随机，无视牌力。",
        F_max=0.50, lambda_fold=0.8, nu=0.3, q_delta=0.05,
    ),
    BotStyle.LLM: BotProfile(
        style=BotStyle.LLM, temperature=0.15,
        display_name="LLM",
        description="LLM 驱动。",
        F_max=0.68, lambda_fold=1.8, nu=1.2, q_delta=0.15,
    ),
    BotStyle.RLCARD: BotProfile(
        style=BotStyle.RLCARD, temperature=0.15,
        display_name="算无遗策",
        description="RLCard 强化学习驱动。",
    ),
}

_PROFILES_CONFIG = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "config", "bot_profiles.json",
)


def _load_profiles() -> Dict[BotStyle, BotProfile]:
    """加载风格参数表：内置默认 + config/bot_profiles.json 字段覆盖。"""
    profiles = dict(_BUILTIN_PROFILES)
    try:
        with open(_PROFILES_CONFIG, "r", encoding="utf-8") as f:
            raw = json.load(f).get("profiles", {})
    except (OSError, json.JSONDecodeError):
        return profiles

    for style_name, overrides in raw.items():
        try:
            style = BotStyle(style_name)
        except ValueError:
            continue
        base = profiles[style]
        profiles[style] = BotProfile(
            style=style,
            temperature=float(overrides.get("temperature", base.temperature)),
            display_name=base.display_name,
            description=base.description,
            F_max=float(overrides.get("F_max", base.F_max)),
            lambda_fold=float(overrides.get("lambda_fold", base.lambda_fold)),
            nu=float(overrides.get("nu", base.nu)),
            q_delta=float(overrides.get("q_delta", base.q_delta)),
        )
    return profiles


BOT_PROFILES: Dict[BotStyle, BotProfile] = _load_profiles()

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
    ) -> None:
        self.name = name
        self.profile = profile
        self.rng = random.Random(seed)
        # 翻牌后 MC 分析器，翻牌前查多人胜率表
        self.analyzer = BattleAnalyzer(
            preflop_sims=0, postflop_sims=postflop_sims, seed=seed,
        )
        # 对手模型（由 GameManager 注入共享实例；无数据时退回风格常数）
        self._opponent_model = None

        self.hands_seen: int = 0

    def set_opponent_model(self, model) -> None:
        """注入共享 OpponentModel（逐对手 F_max/λ 估计）。"""
        self._opponent_model = model

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
        # 仍在局中的对手；已全下者不可能弃牌(F_i=0)但仍争夺底池
        opponents = [
            p for p in game_state.players
            if p.is_in_hand and p.name != player.name
        ]
        active_opponents = len(opponents)
        pot = game_state.pot.total / bb
        to_call = max(0, game_state.current_bet - player.current_bet) / bb

        # 胜率：翻牌前查多人真实胜率表，翻牌后 MC equity share
        if game_state.phase == GamePhase.PRE_FLOP:
            win_rate = preflop_hand_strength(hole_cards, active_opponents) / 100.0
        else:
            analysis = self.analyzer.analyze(
                hole_cards, community, active_opponents, game_state, player,
            )
            dist = analysis.get("ranking_distribution", [])
            equity_entry = next(
                (e for e in dist if e.get("rank") == -1), None,
            )
            win_rate = (
                equity_entry["prob"] / 100.0 if equity_entry
                else 0.5
            )

        # 逐对手响应参数（有观测数据时收缩混合，否则风格常数；全下者 F=0）
        fold_maxes: List[float] = []
        lams: List[float] = []
        for opp in opponents:
            if opp.is_all_in:
                fold_maxes.append(0.0)
                lams.append(self.profile.lambda_fold)
            elif self._opponent_model is not None:
                fold_maxes.append(
                    self._opponent_model.fold_max(opp.name, self.profile.F_max)
                )
                lams.append(
                    self._opponent_model.lam(opp.name, self.profile.lambda_fold)
                )
            else:
                fold_maxes.append(self.profile.F_max)
                lams.append(self.profile.lambda_fold)

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
        if bet_action is not None:
            # 确定最小/最大合法下注增量（BB 单位）
            # _ev_bet 公式期望 x = 相对当前下注的增量;面对下注时的
            # to_call 在 _ev_bet 内部以 x_eff = x + to_call 计入
            player_chips_bb = player.chips / bb
            if bet_action == ActionType.BET:
                min_r = game_state.big_blind / bb  # 主动下注 = BB
            else:
                # RAISE: 增量下限为 max(min_raise, last_raise)
                min_r = max(game_state.min_raise, game_state.last_raise) / bb
            max_bet_increment = player_chips_bb

            if min_r <= max_bet_increment:
                x_opt, ev_opt = self._find_optimal_bet(
                    pot, win_rate, fold_maxes, lams, min_r, max_bet_increment,
                    to_call=to_call,
                )
                action_evs[bet_action] = ev_opt
                bet_sizes[bet_action] = x_opt

        # Check 存在时移除 Fold（Fold 严格不优于 Check）
        if ActionType.CHECK in legal and ActionType.FOLD in action_evs:
            del action_evs[ActionType.FOLD]

        # 玻尔兹曼采样（T 以 pot 标度：概率比在不同 pot 下保持恒定）
        T = self.temperature * max(pot, 1.0)  # 下限 1BB 防 pot=0 除零
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
        """被最强跟注范围 call 后的底线胜率（报告偏移形式）。

        q_inf = max(0.05, w - q_delta)。
        """
        return max(0.05, min(win_rate, win_rate - self.profile.q_delta))

    def _ev_bet(
        self,
        x: float,
        pot: float,
        win_rate: float,
        fold_maxes: Sequence[float],
        lams: Sequence[float],
        to_call: float = 0.0,
    ) -> float:
        """下注/加注的期望收益（逐对手响应模型）。

        F_i(x_eff) = F_max_i · (1 − e^(−λ_i·z)),  z = x_eff/pot
        q(x_eff)   = q_inf + (w − q_inf) · e^(−ν·z)
        all_fold   = Π F_i
        E[k | k≥1] = Σ(1−F_i) / (1 − Π F_i)   (条件期望的精确式)
        EV(x | c)  = all_fold·P + (1−all_fold)·[q·(P + (1+k)·x_eff) − x_eff]

        其中有效投入 x_eff = x + c（c = 行动前还需跟注额）：
        加注者须先补齐跟注再加注，每个跟注者也须先补齐再匹配加注，
        因此弃牌压力与被跟注分支都以 x_eff 度量。BET 路径 c=0,
        公式退化为纯下注模型。全弃牌分支不投入 x_eff（未获匹配的
        加注部分返还），EV 仍为 P。

        Args:
            x: 相对当前下注的新增增量（BB）。
            pot: 当前底池（BB）。
            win_rate: 当前 equity share。
            fold_maxes: 各对手的 F_max（全下者为 0）。
            lams: 各对手的 λ。
            to_call: 需补齐的跟注额 c（BB），主动下注时为 0。

        Returns:
            期望收益（BB）。
        """
        if not fold_maxes:
            # 无对手：底池已属于自己
            return pot
        if x <= 0 or pot <= 0:
            return win_rate * pot

        x_eff = x + max(0.0, to_call)
        z = x_eff / pot
        fold_probs = [
            max(0.0, min(fm, fm * (1.0 - math.exp(-lam * z))))
            for fm, lam in zip(fold_maxes, lams)
        ]
        all_fold = math.prod(fold_probs)

        # 条件胜率（被跟注后对手范围收紧）
        if self.profile.nu > 1e-6:
            q_inf = self._q_inf(win_rate)
            q = q_inf + (win_rate - q_inf) * math.exp(-self.profile.nu * z)
        else:
            q = win_rate

        # 期望跟注人数（条件于至少一人跟注）
        expected_callers = sum(1.0 - fp for fp in fold_probs)
        if all_fold >= 1.0 - 1e-12:
            return pot
        exp_callers_given_call = expected_callers / (1.0 - all_fold)
        ev_called = q * (pot + (1.0 + exp_callers_given_call) * x_eff) - x_eff
        return all_fold * pot + (1.0 - all_fold) * ev_called

    def _find_optimal_bet(
        self,
        pot: float,
        win_rate: float,
        fold_maxes: Sequence[float],
        lams: Sequence[float],
        min_bet: float,
        max_bet: float,
        to_call: float = 0.0,
    ) -> Tuple[float, float]:
        """搜索最优下注额 x* = argmax EV_bet(x)。

        候选为标准底池比例 (0.25P…2P) + 区间边界。
        """
        if min_bet >= max_bet:
            return max_bet, self._ev_bet(
                max_bet, pot, win_rate, fold_maxes, lams, to_call,
            )

        fractions = [0.25, 0.33, 0.50, 0.67, 0.75, 1.0, 1.25, 1.5, 2.0]
        candidates = [
            frac * pot for frac in fractions
            if min_bet <= frac * pot <= max_bet
        ]
        candidates.extend([min_bet, max_bet])

        best_x = min_bet
        best_ev = float("-inf")
        for x in sorted(set(candidates)):
            ev = self._ev_bet(x, pot, win_rate, fold_maxes, lams, to_call)
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
            # 仅覆盖温度,保留该风格的对手响应参数(F_max/λ/ν/q_delta),
            # 否则会静默回落到 dataclass 默认值、改变线上决策行为
            profile = replace(profile, temperature=temperature)
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


