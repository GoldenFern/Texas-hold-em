"""游戏状态 → LLM Prompt 序列化器。

将 GameState 和 Player 对象转换为结构化的自然语言 Prompt，
供 LLM 进行扑克决策。
"""

from __future__ import annotations

from typing import Dict, List, Optional

from src.engine.card import Card, Cards
from src.engine.game import GameState
from src.engine.player import Player
from src.utils.constants import ActionType, GamePhase, PlayerStatus


class PromptBuilder:
    """构建 LLM 决策 Prompt 和系统提示。

    设计原则：
        1. 预计算所有数学量（牌力、赔率）— LLM 不擅概率计算。
        2. 明确标注合法动作和金额区间。
        3. 结构化格式，降低解析失败概率。
    """

    # 阶段中文名映射
    _PHASE_NAMES: Dict[GamePhase, str] = {
        GamePhase.PRE_FLOP: "翻牌前 (Pre-flop)",
        GamePhase.FLOP: "翻牌 (Flop)",
        GamePhase.TURN: "转牌 (Turn)",
        GamePhase.RIVER: "河牌 (River)",
    }

    # 位置名称映射（基于与庄位的距离）
    @staticmethod
    def _get_position_name(player: Player, game: GameState) -> str:
        """获取玩家位置名称。"""
        if player.is_dealer:
            return "庄位 (BTN)"
        if player.is_small_blind:
            return "小盲 (SB)"
        if player.is_big_blind:
            return "大盲 (BB)"

        active = [p for p in game.players if p.chips > 0]
        n = len(active)
        sorted_seats = sorted(p.seat for p in active)
        try:
            dealer_pos = sorted_seats.index(game.dealer_index)
            player_pos = sorted_seats.index(player.seat)
        except ValueError:
            return "未知"

        offset = (player_pos - dealer_pos) % n
        if n >= 6:
            if offset == n - 1:
                return "关煞 (CO)"
            if offset == n - 2:
                return "劫位 (HJ)"
            if offset == 1:
                return "枪口 (UTG)"
            if offset == 2:
                return "UTG+1"
            if offset == 3:
                return "UTG+2"
            if offset == 4:
                return "中间 (MP)"
        elif n >= 4:
            if offset == 1:
                return "枪口 (UTG)"
            if offset == n - 1:
                return "关煞 (CO)"
        return f"位置 {offset}"

    @classmethod
    def build_decision_prompt(
        cls,
        game: GameState,
        player: Player,
        hand_strength: float = 0.0,
        equity_pct: float = 0.0,
        opponent_stats: Optional[Dict[str, Dict[str, float]]] = None,
    ) -> str:
        """构建完整的决策 Prompt。

        Args:
            game: 当前游戏状态。
            player: 当前行动的玩家。
            hand_strength: 预计算的手牌强度 (0.0–1.0)。
            equity_pct: 蒙特卡洛估算胜率 (0–100)。
            opponent_stats: 对手统计数据 {name: {vpip, pfr, aggression, ...}}。

        Returns:
            格式化的 User Prompt 字符串。
        """
        sections: List[str] = []

        # === 游戏状态 ===
        sections.append("=== GAME STATE ===")
        phase_name = cls._PHASE_NAMES.get(game.phase, str(game.phase))
        community_str = cls._format_cards(game.community_cards) or "无"
        hole_str = cls._format_cards(player.hole_cards)
        to_call = game.current_bet - player.current_bet

        sections.append(f"Hand #{game.hand_id} | Phase: {phase_name} | Pot: ${game.pot.total}")
        sections.append(f"Your stack: ${player.chips} | To call: ${max(0, to_call)}")
        sections.append(f"Community cards: {community_str}")
        sections.append(f"Your hole cards: {hole_str}")

        # 手牌客观数据
        strength_pct = round(hand_strength * 100)
        if equity_pct > 0:
            sections.append(f"Hand strength: {strength_pct}% | Equity (Monte Carlo): {equity_pct:.1f}%")
        else:
            sections.append(f"Hand strength: {strength_pct}%")

        # 底池赔率
        if to_call > 0:
            pot_after_call = game.pot.total + to_call
            required = round(to_call / pot_after_call * 100, 1)
            sections.append(f"Pot odds: need {required}% equity to call (pot odds ratio: {round(pot_after_call / to_call, 1)}:1)")
        else:
            sections.append("Pot odds: free to check")

        # 听牌检测
        if game.phase != GamePhase.PRE_FLOP and len(game.community_cards) >= 3:
            flush_draw, straight_draw = cls._detect_draws(player.hole_cards, game.community_cards)
            draw_parts = []
            if flush_draw:
                draw_parts.append("同花听牌")
            if straight_draw:
                draw_parts.append("顺子听牌")
            if draw_parts:
                sections.append(f"Draws: {', '.join(draw_parts)}")

        # === 位置 ===
        sections.append("")
        sections.append("=== POSITION ===")
        pos_name = cls._get_position_name(player, game)
        sections.append(f"Seat {player.seat} — {pos_name}")
        if player.is_dealer:
            sections.append("You are the dealer (best position).")
        if player.is_small_blind:
            sections.append("You are the small blind (worst postflop position).")
        if player.is_big_blind:
            sections.append("You are the big blind.")

        # === 对手信息 ===
        sections.append("")
        sections.append("=== OPPONENTS ===")
        active_count = 0
        for p in game.players:
            if p.name == player.name or p.status == PlayerStatus.OUT:
                continue
            if p.status not in (PlayerStatus.ACTIVE, PlayerStatus.ALL_IN):
                continue
            active_count += 1

            parts = [f"{p.name} (Seat {p.seat}): Stack ${p.chips}"]
            if p.status == PlayerStatus.ALL_IN:
                parts.append("[ALL-IN]")
            if p.is_dealer:
                parts.append("[BTN]")
            if p.is_small_blind:
                parts.append("[SB]")
            if p.is_big_blind:
                parts.append("[BB]")
            if p.is_folded:
                parts.append("[FOLDED]")

            # 本轮下注
            if p.current_bet > 0:
                parts.append(f"| Bet this round: ${p.current_bet}")

            # 统计数据
            if opponent_stats and p.name in opponent_stats:
                stats = opponent_stats[p.name]
                stat_parts = []
                if "vpip" in stats:
                    stat_parts.append(f"VPIP:{stats['vpip']:.0%}")
                if "pfr" in stats:
                    stat_parts.append(f"PFR:{stats['pfr']:.0%}")
                if "aggression" in stats:
                    stat_parts.append(f"AF:{stats['aggression']:.1f}")
                if stat_parts:
                    parts.append("| " + " ".join(stat_parts))

            sections.append("  " + " ".join(parts))

        if active_count == 0:
            sections.append("  (no opponents remain)")

        # === 本轮动作 ===
        sections.append("")
        sections.append("=== ACTIONS THIS ROUND ===")
        if game.actions_this_round:
            for action in game.actions_this_round:
                sections.append(f"  {repr(action)}")
        else:
            sections.append("  (no actions yet — you are first to act)")

        # === 合法动作 ===
        sections.append("")
        sections.append("=== LEGAL ACTIONS ===")
        legal_actions = game.get_legal_actions(player)
        legal_strs = cls._format_legal_actions(legal_actions, game, player)
        sections.append("  " + "\n  ".join(legal_strs))

        # === 输出格式 ===
        sections.append("")
        sections.append("=== OUTPUT ===")
        sections.append('Respond with EXACTLY one JSON object (no markdown fences, no extra text):')
        sections.append('{"action": "FOLD|CHECK|CALL|BET|RAISE", "amount": <int>, "reasoning": "<brief reason>"}')
        sections.append("Include 'amount' only for BET/RAISE. All other actions use amount: 0.")

        return "\n".join(sections)

    @classmethod
    def build_advisor_prompt(
        cls,
        game: GameState,
        player: Player,
        hand_strength: float = 0.0,
        equity_pct: float = 0.0,
    ) -> str:
        """构建策略顾问 Prompt（模式 B）。

        与决策 Prompt 类似，但输出格式不同 —— 返回建议和解释。
        """
        decision_prompt = cls.build_decision_prompt(game, player, hand_strength, equity_pct)

        # 替换输出格式说明
        lines = decision_prompt.split("\n")
        # 找到 === OUTPUT === 部分并替换
        output_idx = None
        for i, line in enumerate(lines):
            if line.strip() == "=== OUTPUT ===":
                output_idx = i
                break

        if output_idx is not None:
            lines = lines[:output_idx]
            lines.append("=== OUTPUT ===")
            lines.append("Provide your recommendation with detailed reasoning:")
            lines.append('{"recommendation": "<action>", "amount": <int>, "reasoning": "<detailed strategic analysis>"}')
            lines.append("Explain WHY this is the best play — consider pot odds, implied odds, position, opponent tendencies, and game theory.")

        return "\n".join(lines)

    @classmethod
    def build_commentary_prompt(
        cls,
        hand_history: Dict,
    ) -> str:
        """构建解说 Prompt（模式 C）。

        Args:
            hand_history: 一手牌的历史摘要字典。
        """
        lines = [
            "You are a charismatic poker commentator. Analyze this hand and provide",
            "an entertaining, insightful commentary in Chinese (2-5 sentences).",
            "Include: key decision points, notable bluffs or hero calls, and the final outcome.",
            "",
            f"Hand #{hand_history.get('hand_id', '?')}",
            f"Community cards: {hand_history.get('community_cards', [])}",
            f"Pot: ${hand_history.get('pot_total', 0)}",
            f"Winners: {hand_history.get('winners', {})}",
            f"Key actions: {hand_history.get('actions', [])}",
            "",
            "Respond with just the commentary text, no JSON.",
        ]
        return "\n".join(lines)

    @classmethod
    def get_system_prompt(cls) -> str:
        """获取系统 Prompt（模式 A — 决策）。"""
        return (
            "You are an elite Texas Hold'em No-Limit poker player. "
            "Your goal is to maximize expected value (EV) in every decision.\n\n"
            "Rules:\n"
            "- Choose ONLY from the LEGAL ACTIONS listed.\n"
            "- BET/RAISE amount must be between MIN_RAISE and MAX_BET.\n"
            "- Consider pot odds, implied odds, position, hand strength, opponent ranges, and stack sizes.\n"
            "- Respond ONLY with a valid JSON object. No markdown fences, no extra text.\n"
            '- Format: {"action": "FOLD|CHECK|CALL|BET|RAISE", "amount": <int>, "reasoning": "<one sentence>"}'
        )

    @classmethod
    def get_advisor_system_prompt(cls) -> str:
        """获取系统 Prompt（模式 B — 顾问）。"""
        return (
            "You are a world-class Texas Hold'em poker coach. "
            "Provide strategic advice with clear, educational reasoning. "
            "Explain the WHY behind each recommendation. "
            "Consider game theory optimal (GTO) principles, exploitative adjustments, "
            "and common poker concepts (pot odds, implied odds, range advantage, position).\n\n"
            "Respond with a JSON object containing your recommendation and detailed reasoning."
        )

    # ================================================================
    # 辅助方法
    # ================================================================

    @staticmethod
    def _format_cards(cards: Cards) -> str:
        """格式化牌列表为字符串。"""
        if not cards:
            return "无"
        return " ".join(c.short_str for c in cards)

    @staticmethod
    def _detect_draws(hole_cards: Cards, community_cards: Cards) -> tuple:
        """检测听牌（复用 strategy.py 逻辑的简化版）。"""
        from collections import Counter
        all_cards = hole_cards + community_cards

        # 同花听牌
        suit_counts = Counter(c.suit for c in all_cards)
        flush_draw = any(count == 4 for count in suit_counts.values())

        # 顺子听牌
        ranks = sorted(set(c.rank.value for c in all_cards))
        straight_draw = False
        for i in range(len(ranks) - 3):
            if ranks[i + 3] - ranks[i] <= 4:
                straight_draw = True
                break
        if 14 in ranks and {2, 3, 4}.issubset(set(ranks)):
            straight_draw = True

        return flush_draw, straight_draw

    @staticmethod
    def _format_legal_actions(
        legal: List[ActionType],
        game: GameState,
        player: Player,
    ) -> List[str]:
        """格式化合法动作列表（含金额范围）。"""
        result = []
        min_raise = game.get_min_raise_amount(player)
        max_bet = game.get_max_bet(player)
        to_call = game.current_bet - player.current_bet

        for action in legal:
            if action == ActionType.FOLD:
                result.append("FOLD — 弃牌")
            elif action == ActionType.CHECK:
                result.append("CHECK — 过牌")
            elif action == ActionType.CALL:
                result.append(f"CALL ${to_call} — 跟注")
            elif action == ActionType.BET:
                result.append(f"BET (${min_raise}–${max_bet}) — 下注")
            elif action == ActionType.RAISE:
                result.append(f"RAISE (${min_raise}–${max_bet}) — 加注")
            elif action == ActionType.ALL_IN:
                all_in_amount = player.chips + player.current_bet
                result.append(f"ALL-IN (${all_in_amount}) — 全下")
        return result
