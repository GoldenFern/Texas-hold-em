"""LLM 上下文管理器 —— 会话级状态追踪与 Prompt 注入。

追踪对手统计数据、自身桌面形象、手牌历史摘要、摊牌信息，
为 LLM 决策提供超越当前手牌的上下文。

设计原则：
    1. 独立于 PromptBuilder——ContextManager 负责数据聚合，PromptBuilder 负责格式化。
    2. 接收 HandReporter 的统计数据，不重复计算。
    3. 所有历史数据保留最近 N 手（由 context_window_hands 控制）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.engine.game import ActionType
from src.utils.constants import GamePhase


@dataclass
class HandSummary:
    """一手牌的轻量摘要，用于上下文注入。"""

    hand_id: int
    won: bool
    profit: int
    hole_cards: str
    action_summary: str  # 浓缩的动作描述


@dataclass
class OpponentProfile:
    """单个对手的综合画像。"""

    name: str
    vpip: float = 0.0
    pfr: float = 0.0
    aggression_factor: float = 0.0
    hands_played: int = 0
    classification: str = "未知"  # Rock / TAG / LAG / Calling Station / 未知
    showdown_hands: List[str] = field(default_factory=list)  # 最近摊牌展示的手牌


# 对手分类阈值
_OPPONENT_CLASSIFICATION = [
    # (label, vpip_max, pfr_max, strategy_hint)
    ("岩石 (Rock)",      0.15, 0.10, "极紧，多偷盲，面对加注弃牌"),
    ("紧凶 (TAG)",       0.25, 0.20, "标准紧凶，用 GTO 对抗"),
    ("松凶 (LAG)",       0.40, 0.30, "激进松凶，设陷阱用强牌跟注"),
    ("跟注站 (Calling Station)", 1.00, 0.15, "跟注过多，价值下注不诈唬"),
]


def classify_opponent(vpip: float, pfr: float) -> tuple:
    """根据 VPIP/PFR 对对手进行分类。

    Returns:
        (分类标签, 策略提示)
    """
    for label, vpip_max, pfr_max, hint in _OPPONENT_CLASSIFICATION:
        if vpip <= vpip_max and pfr <= pfr_max:
            return label, hint
    # 兜底：松凶
    return "松凶 (LAG)", "激进松凶，设陷阱用强牌跟注"


class ContextManager:
    """会话级上下文管理器。

    在 GameManager 中为每个 LLMBot 维护一个实例，
    每手牌结束时调用 end_hand() 更新状态。

    典型用法:
        ctx = ContextManager(bot_name="LLMBot1", context_window_hands=5)
        # 每手牌结束后:
        ctx.end_hand(reporter, hand_result)
        # 每次 LLM 决策前:
        context_str = ctx.get_context_for_prompt()
    """

    def __init__(
        self,
        bot_name: str = "",
        context_window_hands: int = 5,
    ) -> None:
        self._bot_name = bot_name
        self._context_window_hands = context_window_hands

        # 手牌历史摘要（最近 N 手）
        self._hand_summaries: List[HandSummary] = []

        # 自身桌面形象追踪
        self._own_total_actions: int = 0
        self._own_aggressive_actions: int = 0  # BET + RAISE
        self._own_passive_actions: int = 0     # CALL + CHECK
        self._own_fold_actions: int = 0

        # 对手画像缓存（按名称索引）
        self._opponent_profiles: Dict[str, OpponentProfile] = {}

        # 当前手牌的动作记录（用于构建摘要）
        self._current_hand_actions: List[str] = []
        self._current_hand_id: int = 0
        self._current_hole_cards: str = ""

    # ================================================================
    # 公共接口
    # ================================================================

    def record_action(
        self,
        bot_name: str,
        action_type: ActionType,
        hole_cards: str = "",
        hand_id: int = 0,
    ) -> None:
        """记录当前手牌中的一个动作（由 LLMBot 在每次决策后调用）。

        Args:
            bot_name: 执行动作的玩家名。
            action_type: 动作类型。
            hole_cards: 底牌字符串（如 "Ah Kh"）。
            hand_id: 当前手牌编号。
        """
        self._current_hand_id = hand_id
        if hole_cards:
            self._current_hole_cards = hole_cards

        # 记录动作描述
        self._current_hand_actions.append(action_type.name)

        # 仅追踪自身的桌面形象统计
        if bot_name == self._bot_name:
            self._own_total_actions += 1
            if action_type in (ActionType.BET, ActionType.RAISE):
                self._own_aggressive_actions += 1
            elif action_type in (ActionType.CALL, ActionType.CHECK):
                self._own_passive_actions += 1
            elif action_type == ActionType.FOLD:
                self._own_fold_actions += 1

    def end_hand(
        self,
        won: bool = False,
        profit: int = 0,
        reporter=None,  # Optional[HandReporter]
    ) -> None:
        """手牌结束时调用，更新摘要和对手数据。

        Args:
            won: 自身是否赢得这手牌。
            profit: 这手牌的净利润。
            reporter: HandReporter 实例，用于获取真实对手统计。
        """
        # 构建手牌摘要
        action_str = " → ".join(self._current_hand_actions[-6:]) or "无动作"
        summary = HandSummary(
            hand_id=self._current_hand_id,
            won=won,
            profit=profit,
            hole_cards=self._current_hole_cards,
            action_summary=action_str,
        )
        self._hand_summaries.append(summary)

        # 限制保留最近 N 手
        if len(self._hand_summaries) > self._context_window_hands:
            self._hand_summaries = self._hand_summaries[-self._context_window_hands:]

        # 从 HandReporter 同步对手统计数据
        if reporter is not None:
            self._sync_opponent_stats(reporter)

        # 重置当前手牌状态
        self._current_hand_actions = []
        self._current_hole_cards = ""

    def record_showdown(
        self,
        opponent_name: str,
        hole_cards: str,
    ) -> None:
        """记录对手在摊牌时展示的手牌。

        Args:
            opponent_name: 对手名称。
            hole_cards: 手牌字符串（如 "Ah Kh"）。
        """
        if opponent_name not in self._opponent_profiles:
            self._opponent_profiles[opponent_name] = OpponentProfile(name=opponent_name)
        profile = self._opponent_profiles[opponent_name]
        profile.showdown_hands.append(hole_cards)
        # 最多保留 5 手摊牌记录
        if len(profile.showdown_hands) > 5:
            profile.showdown_hands = profile.showdown_hands[-5:]

    def get_opponent_stats(self, player_name: str) -> OpponentProfile:
        """获取指定对手的综合画像。

        Args:
            player_name: 对手名称。

        Returns:
            OpponentProfile，若未记录则返回默认空画像。
        """
        return self._opponent_profiles.get(
            player_name,
            OpponentProfile(name=player_name),
        )

    def get_table_image(self) -> Dict[str, Any]:
        """获取自身桌面形象摘要。

        Returns:
            包含 aggression_freq、fold_freq、image_label 的字典。
        """
        total = max(1, self._own_total_actions)
        agg_freq = self._own_aggressive_actions / total
        fold_freq = self._own_fold_actions / total

        # 根据数据分类自身形象
        if agg_freq > 0.4:
            image_label = "激进"
        elif fold_freq > 0.6:
            image_label = "偏紧"
        elif agg_freq < 0.15:
            image_label = "被动"
        else:
            image_label = "均衡"

        return {
            "aggression_frequency": round(agg_freq, 2),
            "fold_frequency": round(fold_freq, 2),
            "total_actions_tracked": self._own_total_actions,
            "image_label": image_label,
        }

    def get_session_summary(self) -> str:
        """生成会话级别的文本摘要，可直接注入 Prompt。

        Returns:
            格式化的上下文文本段落。
        """
        lines: List[str] = []

        # 手牌历史
        if self._hand_summaries:
            lines.append("=== 会话上下文 ===")
            lines.append(f"最近手牌（共 {len(self._hand_summaries)} 手）：")
            for h in self._hand_summaries:
                result = "赢" if h.won else "输"
                sign = "+" if h.profit >= 0 else ""
                lines.append(
                    f"  手牌 #{h.hand_id}: {result} {sign}${h.profit}, "
                    f"底牌 [{h.hole_cards}], 动作: {h.action_summary}"
                )

            # 趋势检测
            if len(self._hand_summaries) >= 3:
                recent = self._hand_summaries[-3:]
                wins = sum(1 for h in recent if h.won)
                if wins == 0:
                    lines.append("  ⚠ 最近 3 手全输，可能需要调整策略。")
                elif wins == 3:
                    lines.append("  ✓ 最近 3 手全赢，桌面形象可能偏强，可利用此形象诈唬。")

        # 自身桌面形象
        image = self.get_table_image()
        if image["total_actions_tracked"] > 0:
            if not self._hand_summaries:
                lines.append("=== 会话上下文 ===")
            lines.append(
                f"你的桌面形象：{image['image_label']}"
                f"（进攻频率 {image['aggression_frequency']:.0%}，"
                f"弃牌频率 {image['fold_frequency']:.0%}，"
                f"共 {image['total_actions_tracked']} 次动作）"
            )

        return "\n".join(lines) if lines else ""

    def get_opponents_context(self) -> str:
        """生成对手画像的文本摘要，可直接注入 Prompt。

        Returns:
            格式化的对手信息段落。
        """
        if not self._opponent_profiles:
            return ""

        lines = ["=== 对手画像 ==="]
        for name, profile in self._opponent_profiles.items():
            if profile.hands_played == 0:
                lines.append(f"  {name}: 暂无数据")
                continue

            cls_label, hint = classify_opponent(profile.vpip, profile.pfr)

            parts = [
                f"{name}:",
                f"入池率 {profile.vpip:.0%},",
                f"加注率 {profile.pfr:.0%},",
                f"侵略因子 {profile.aggression_factor:.1f},",
                f"（{profile.hands_played} 手）",
                f"— {cls_label}",
            ]
            lines.append("  " + " ".join(parts))

            # 摊牌手牌
            if profile.showdown_hands:
                lines.append(f"    曾摊牌: {', '.join(profile.showdown_hands[-3:])}")

            # 策略提示
            lines.append(f"    策略: {hint}")

        return "\n".join(lines)

    def get_context_for_prompt(self) -> str:
        """聚合所有上下文为单个文本块（用于注入 Prompt）。

        Returns:
            可直接拼接在决策 Prompt 后面的上下文字符串。
        """
        parts: List[str] = []

        session_summary = self.get_session_summary()
        if session_summary:
            parts.append(session_summary)

        opponents_context = self.get_opponents_context()
        if opponents_context:
            parts.append(opponents_context)

        return "\n\n".join(parts) if parts else ""

    def reset(self) -> None:
        """重置所有上下文（新 session 时调用）。"""
        self._hand_summaries.clear()
        self._own_total_actions = 0
        self._own_aggressive_actions = 0
        self._own_passive_actions = 0
        self._own_fold_actions = 0
        self._opponent_profiles.clear()
        self._current_hand_actions.clear()
        self._current_hand_id = 0
        self._current_hole_cards = ""

    # ================================================================
    # 内部方法
    # ================================================================

    def _sync_opponent_stats(self, reporter) -> None:
        """从 HandReporter 同步真实对手统计数据。

        Args:
            reporter: HandReporter 实例。
        """
        from src.analysis.reporter import PlayerStats

        all_stats: List[PlayerStats] = reporter.get_all_stats()
        for stats in all_stats:
            if stats.name == self._bot_name:
                continue  # 跳过自身
            if stats.hands_played == 0:
                continue

            profile = self._opponent_profiles.get(stats.name)
            if profile is None:
                profile = OpponentProfile(name=stats.name)
                self._opponent_profiles[stats.name] = profile

            profile.vpip = stats.vpip
            profile.pfr = stats.pfr
            profile.aggression_factor = stats.aggression_factor
            profile.hands_played = stats.hands_played
            cls_label, _ = classify_opponent(stats.vpip, stats.pfr)
            profile.classification = cls_label
