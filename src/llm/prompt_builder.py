"""游戏状态 → LLM Prompt 序列化器（基于 LangChain ChatPromptTemplate）。

将 GameState 和 Player 对象转换为结构化的中文 Prompt，
通过 LangChain 的 ChatPromptTemplate 管理 system / human 消息模板。

设计原则：
    1. 预计算所有数学量（牌力、赔率）—— LLM 不擅长概率计算。
    2. 明确标注合法动作和金额区间。
    3. 全中文 Prompt，适配国内大模型（DeepSeek / Qwen / GLM 等）。
    4. 返回 ChatPromptTemplate，与 LangChain LCEL 管道对接。
"""

from __future__ import annotations

from typing import Dict, List, Optional

from langchain_core.prompts import ChatPromptTemplate

from src.engine.card import Card, Cards
from src.engine.game import GameState
from src.engine.player import Player
from src.utils._card_helpers import count_outs
from src.utils.constants import ActionType, GamePhase, PlayerStatus


class PromptBuilder:
    """构建 LLM 决策 Prompt（基于 LangChain ChatPromptTemplate）。

    提供三种模式：
        - 决策模式（A）：返回 ChatPromptTemplate + 游戏状态构建函数
        - 顾问模式（B）：返回 ChatPromptTemplate（策略建议）
        - 解说模式（C）：返回纯文本 Prompt（赛后解说）
    """

    # 阶段中文名
    _PHASE_NAMES: Dict[GamePhase, str] = {
        GamePhase.WAITING: "等待开始",
        GamePhase.PRE_FLOP: "翻牌前",
        GamePhase.FLOP: "翻牌",
        GamePhase.TURN: "转牌",
        GamePhase.RIVER: "河牌",
        GamePhase.SHOWDOWN: "摊牌",
        GamePhase.FINISHED: "已结束",
    }


    @staticmethod
    def _get_position_name(player: Player, game: GameState) -> str:
        """获取玩家位置中文名称。"""
        if player.is_dealer:
            return "庄位"
        if player.is_small_blind:
            return "小盲"
        if player.is_big_blind:
            return "大盲"

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
                return "关煞位"
            if offset == n - 2:
                return "劫位"
            if offset == 1:
                return "枪口位"
            if offset == 2:
                return "枪口+1"
            if offset == 3:
                return "枪口+2"
            if offset == 4:
                return "中间位"
        elif n >= 4:
            if offset == 1:
                return "枪口位"
            if offset == n - 1:
                return "关煞位"
        return f"位置 {offset}"

    # ================================================================
    # 系统提示（全中文）
    # ================================================================

    @classmethod
    def get_system_prompt(cls) -> str:
        """获取系统提示（模式 A — 决策）。"""
        return (
            "你是一位世界级的无限注德州扑克玩家。"
            "你的目标是在每一次决策中最大化期望价值（EV）。\n\n"
            "决策流程：\n"
            "1. 评估你的手牌强度以及它与公共牌的连接程度。\n"
            "2. 根据对手的动作和统计数据，推断他们的手牌范围。\n"
            "3. 计算底池赔率并与你的胜率进行比较。\n"
            "4. 考虑你的桌面形象以及对手如何看待你。\n"
            "5. 选择最大化长期 EV 的动作。\n\n"
            "参考示例：\n\n"
            "示例 1：位置有利时的强牌\n"
            "  你在关煞位持有 A♠ K♠，面对枪口位 3BB 的加注。"
            "你的手牌是顶级范围（前 5%）。枪口位范围偏紧（约 10-12%），但你有位置优势。\n"
            "  → 动作：加注到 9BB。理由：为了价值而 3-bet，隔离对手，夺取主动权。\n\n"
            "示例 2：面对进攻的听牌\n"
            "  你在 K♦ 9♠ 2♥ 的翻牌面持有 7♠ 8♠，面对紧凶对手 2/3 底池的持续下注。"
            "你有一个卡顺听牌（约 17% 胜率），底池赔率需要约 28% 胜率。\n"
            "  → 动作：弃牌。理由：胜率低于底池赔率要求，且位置不利。\n\n"
            "示例 3：河牌价值下注\n"
            "  你在干燥牌面持有顶对好踢脚。对手（跟注站类型）已经过牌。"
            "跟注站跟注范围过宽——你应该比正常情况更大的价值下注。\n"
            "  → 动作：下注 2/3 底池。理由：从松被动型对手身上榨取最大价值。\n\n"
            "规则：\n"
            "- 只能从列出的合法动作中选择。\n"
            "- 下注/加注金额必须在最小加注和最大下注之间。\n"
            "- 综合考虑底池赔率、位置、手牌强度、对手范围和筹码深度。\n"
            "- 在 JSON 输出中包含结构化的「分析」字段，展示你的推理过程。\n"
            "- 只回复一个合法的 JSON 对象，不要使用 markdown 代码块，不要有额外文字。"
        )

    @classmethod
    def get_advisor_system_prompt(cls) -> str:
        """获取系统提示（模式 B — 顾问）。"""
        return (
            "你是一位世界级的德州扑克教练。"
            "请提供战略建议，附上清晰、有教育意义的推理过程。"
            "解释每条建议背后的「为什么」。"
            "综合考虑博弈论最优（GTO）原则、利用性调整，"
            "以及常见的扑克概念（底池赔率、隐含赔率、范围优势、位置）。\n\n"
            "请回复一个 JSON 对象，包含你的建议和详细推理。"
        )

    # ================================================================
    # 游戏状态文本构建（纯游戏逻辑，LangChain 不参与）
    # ================================================================

    @classmethod
    def build_game_state_text(
        cls,
        game: GameState,
        player: Player,
        hand_strength: float = 0.0,
        equity_pct: float = 0.0,
        opponent_stats: Optional[Dict[str, Dict[str, float]]] = None,
    ) -> str:
        """构建游戏状态文本（HumanMessage 的内容）。

        包含游戏状态、位置、对手信息、本轮动作、合法动作等。
        这是纯扑克领域逻辑，LangChain 不参与此部分。

        Args:
            game: 当前游戏状态。
            player: 当前行动的玩家。
            hand_strength: 预计算的手牌强度 (0.0–1.0)。
            equity_pct: 蒙特卡洛估算胜率 (0–100)。
            opponent_stats: 对手统计数据。

        Returns:
            格式化的游戏状态文本。
        """
        sections: List[str] = []

        # === 游戏状态 ===
        sections.append("=== 游戏状态 ===")
        phase_name = cls._PHASE_NAMES.get(game.phase, str(game.phase))
        community_str = cls._format_cards(game.community_cards) or "无"
        hole_str = cls._format_cards(player.hole_cards)
        to_call = game.current_bet - player.current_bet

        sections.append(f"手牌 #{game.hand_id} | 阶段: {phase_name} | 底池: ${game.pot.total}")
        sections.append(f"你的筹码: ${player.chips} | 需要跟注: ${max(0, to_call)}")
        sections.append(f"公共牌: {community_str}")
        sections.append(f"你的底牌: {hole_str}")

        # 手牌客观数据
        strength_pct = round(hand_strength * 100)
        if equity_pct > 0:
            sections.append(f"手牌强度: {strength_pct}% | 胜率（蒙特卡洛）: {equity_pct:.1f}%")
        else:
            sections.append(f"手牌强度: {strength_pct}%")

        # 底池赔率
        if to_call > 0:
            from src.utils.poker_math import pot_odds as _po
            required = round(_po(to_call, game.pot.total) * 100, 1)
            ratio = round(game.pot.total / to_call, 1)
            sections.append(f"底池赔率: 需要 {required}% 胜率才能跟注（赔率比: {ratio}:1）")
        else:
            sections.append("底池赔率: 免费过牌")

        # 听牌检测（含 outs 计数）
        if game.phase != GamePhase.PRE_FLOP and len(game.community_cards) >= 3:
            info = count_outs(player.hole_cards, game.community_cards)
            draw_parts = []
            if info.flush_draw:
                draw_parts.append("同花听牌")
            if info.straight_draw == "oesd":
                draw_parts.append("两头顺听牌")
            elif info.straight_draw == "gutshot":
                draw_parts.append("卡顺听牌")
            if draw_parts:
                joined = "、".join(draw_parts)
                sections.append(f"听牌: {joined}（补牌 outs: {info.outs} 张）")

        # === 位置 ===
        sections.append("")
        sections.append("=== 位置 ===")
        pos_name = cls._get_position_name(player, game)
        sections.append(f"座位 {player.seat} — {pos_name}")
        if player.is_dealer:
            sections.append("你是庄位（最优位置）。")
        if player.is_small_blind:
            sections.append("你是小盲（翻牌后位置最差）。")
        if player.is_big_blind:
            sections.append("你是大盲。")

        # === 对手信息 ===
        sections.append("")
        sections.append("=== 对手 ===")
        active_count = 0
        for p in game.players:
            if p.name == player.name or p.status == PlayerStatus.OUT:
                continue
            if p.status not in (PlayerStatus.ACTIVE, PlayerStatus.ALL_IN):
                continue
            active_count += 1

            parts = [f"{p.name}（座位 {p.seat}）: 筹码 ${p.chips}"]
            if p.status == PlayerStatus.ALL_IN:
                parts.append("[已全下]")
            if p.is_dealer:
                parts.append("[庄位]")
            if p.is_small_blind:
                parts.append("[小盲]")
            if p.is_big_blind:
                parts.append("[大盲]")
            if p.is_folded:
                parts.append("[已弃牌]")

            # 本轮下注
            if p.current_bet > 0:
                parts.append(f"| 本轮下注: ${p.current_bet}")

            # 统计数据
            if opponent_stats and p.name in opponent_stats:
                stats = opponent_stats[p.name]
                stat_parts = []
                if stats.get("is_default_prior"):
                    stat_parts.append("[无观测数据]")
                if "vpip" in stats:
                    stat_parts.append(f"入池率:{stats['vpip']:.0%}")
                if "pfr" in stats:
                    stat_parts.append(f"加注率:{stats['pfr']:.0%}")
                if "aggression" in stats:
                    stat_parts.append(f"侵略因子:{stats['aggression']:.1f}")
                if "classification" in stats:
                    stat_parts.append(f"[{stats['classification']}]")
                if stat_parts:
                    parts.append("| " + " ".join(stat_parts))
                # 摊牌手牌记录
                showdown = stats.get("showdown_hands", [])
                if showdown:
                    parts.append(f"| 曾摊牌: {', '.join(showdown)}")

            sections.append("  " + " ".join(parts))

        if active_count == 0:
            sections.append("  （无剩余对手）")

        # === 本轮动作 ===
        sections.append("")
        sections.append("=== 本轮动作 ===")
        if game.actions_this_round:
            action_cn = {"FOLD": "弃牌", "CHECK": "过牌", "CALL": "跟注",
                         "BET": "下注", "RAISE": "加注"}
            for action in game.actions_this_round:
                name = action_cn.get(action.action_type.name, action.action_type.name)
                amount_str = f" ${action.amount}" if action.amount > 0 else ""
                all_in_str = "（全下）" if action.is_all_in else ""
                sections.append(f"  {action.player_name}: {name}{amount_str}{all_in_str}")
        else:
            sections.append("  （尚无动作——你是第一个行动）")

        # === 合法动作 ===
        sections.append("")
        sections.append("=== 合法动作 ===")
        legal_actions = game.get_legal_actions(player)
        legal_strs = cls._format_legal_actions(legal_actions, game, player)
        sections.append("  " + "\n  ".join(legal_strs))

        # === 下注金额指导 ===
        if any(a in legal_actions for a in (ActionType.BET, ActionType.RAISE)):
            pot_total = game.pot.total
            sections.append("")
            sections.append("=== 下注尺度参考 ===")
            sections.append(f"  底池: ${pot_total}")
            sections.append(f"  小注（1/3 底池 ≈ ${max(1, round(pot_total / 3))}）：范围下注、干燥牌面持续下注")
            sections.append(f"  中注（1/2 底池 ≈ ${max(1, round(pot_total / 2))}）：标准价值下注")
            sections.append(f"  大注（2/3 底池 ≈ ${max(1, round(pot_total * 2 / 3))}）：极化范围、保护手牌")
            sections.append(f"  超池（1x+ 底池 = ${pot_total}+）：极端极化")

        return "\n".join(sections)

    @classmethod
    def build_session_context_text(cls, session_context: str) -> str:
        """将会话上下文格式化为 Prompt 可注入的文本。

        Args:
            session_context: ContextManager.get_context_for_prompt() 返回的文本。

        Returns:
            格式化的会话上下文文本（如果为空则返回空字符串）。
        """
        if not session_context:
            return ""
        return f"\n\n{session_context}\n\n请利用以上会话上下文来指导你的决策——根据你的桌面形象和对手倾向进行调整。"

    # ================================================================
    # LangChain PromptTemplate 构建
    # ================================================================

    @classmethod
    def get_decision_prompt_template(cls) -> ChatPromptTemplate:
        """获取决策模式的 ChatPromptTemplate。

        模板变量:
            - game_state: 游戏状态文本（build_game_state_text 的输出）
            - session_context: 会话上下文文本（可选）

        Returns:
            LangChain ChatPromptTemplate，含 SystemMessage + HumanMessage。
        """
        system_prompt = cls.get_system_prompt()

        human_template = (
            "{game_state}"
            "{session_context}"
            "\n\n=== 输出格式 ==="
            "\n请逐步推理，然后回复一个 JSON 对象。"
            "\n先在「分析」字段中分析局势，再给出你的决策。"
            '\n格式: {{"分析": {{"手牌评估": "...", "赔率分析": "...", "对手解读": "...", "策略计划": "..."}}, '
            '"动作": "弃牌|过牌|跟注|下注|加注", "金额": <整数>, "理由": "<简要理由>"}}'
            "\n「金额」仅在下注/加注时需要填写，其他动作填 0。"
            "\n只回复纯 JSON，不要有 markdown 代码块，不要有额外文字。"
        )

        return ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", human_template),
        ])

    @classmethod
    def get_advisor_prompt_template(cls) -> ChatPromptTemplate:
        """获取顾问模式的 ChatPromptTemplate。

        模板变量:
            - game_state: 游戏状态文本
        """
        system_prompt = cls.get_advisor_system_prompt()

        human_template = (
            "{game_state}"
            "\n\n=== 输出格式 ==="
            "\n请提供详细的策略建议："
            '\n{{"建议": "<动作>", "金额": <整数>, "理由": "<详细策略分析>"}}'
            "\n解释为什么这是最佳选择——考虑底池赔率、隐含赔率、位置、对手倾向和博弈论。"
        )

        return ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", human_template),
        ])

    @classmethod
    def build_commentary_prompt(
        cls,
        hand_history: Dict,
    ) -> str:
        """构建解说 Prompt（模式 C）。

        返回纯文本（非 ChatPromptTemplate）——解说不需要结构化输出。

        Args:
            hand_history: 一手牌的历史摘要字典。
        """
        lines = [
            "你是一位富有魅力的扑克解说员。请分析这手牌，",
            "用中文提供一段有趣、有见地的解说（2-5 句话）。",
            "包括：关键决策点、值得注意的诈唬或英雄式跟注、以及最终结果。",
            "",
            f"手牌 #{hand_history.get('hand_id', '?')}",
            f"公共牌: {hand_history.get('community_cards', [])}",
            f"底池: ${hand_history.get('pot_total', 0)}",
            f"赢家: {hand_history.get('winners', {})}",
            f"关键动作: {hand_history.get('actions', [])}",
            "",
            "只回复解说文字，不需要 JSON。",
        ]
        return "\n".join(lines)

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
                result.append("弃牌（FOLD）—— 放弃当前手牌")
            elif action == ActionType.CHECK:
                result.append("过牌（CHECK）—— 不下注，保持底池不变")
            elif action == ActionType.CALL:
                result.append(f"跟注 ${to_call}（CALL）—— 匹配当前下注")
            elif action == ActionType.BET:
                result.append(f"下注 ${min_raise}–${max_bet}（BET）—— 主动下注")
            elif action == ActionType.RAISE:
                result.append(f"加注 ${min_raise}–${max_bet}（RAISE）—— 在已有下注基础上加注")
        return result

    # ================================================================
    # 向后兼容方法
    # ================================================================

    @classmethod
    def build_decision_prompt(
        cls,
        game: GameState,
        player: Player,
        hand_strength: float = 0.0,
        equity_pct: float = 0.0,
        opponent_stats: Optional[Dict[str, Dict[str, float]]] = None,
        session_context: str = "",
    ) -> str:
        """构建完整的决策 Prompt 字符串（向后兼容方法）。

        返回纯文本 Prompt，与旧版 API 兼容。
        新代码建议使用 build_game_state_text() + get_decision_prompt_template() 组合。
        """
        game_state_text = cls.build_game_state_text(
            game=game,
            player=player,
            hand_strength=hand_strength,
            equity_pct=equity_pct,
            opponent_stats=opponent_stats,
        )
        session_text = cls.build_session_context_text(session_context)

        return game_state_text + session_text

    @classmethod
    def build_advisor_prompt(
        cls,
        game: GameState,
        player: Player,
        hand_strength: float = 0.0,
        equity_pct: float = 0.0,
    ) -> str:
        """构建策略顾问 Prompt 字符串（向后兼容方法）。"""
        return cls.build_decision_prompt(game, player, hand_strength, equity_pct)
