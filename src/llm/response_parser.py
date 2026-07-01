"""LLM 响应解析器 —— 将 LLM 文本输出转换为合法的 Action 对象。

安全设计：
    1. 去除 markdown 代码围栏 (```json ... ```)
    2. JSON 解析 + 容错（允许小写、多余字段）
    3. 动作合法性验证
    4. 金额裁剪到 [min_raise, max_bet]
    5. 任何失败返回 None，触发降级
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

from src.engine.game import Action, ActionType, GameState
from src.engine.player import Player

logger = logging.getLogger(__name__)


class ResponseParser:
    """LLM 响应 → Action 对象解析器。"""

    # 动作名称映射（支持多种写法）
    _ACTION_MAP = {
        "fold": ActionType.FOLD,
        "check": ActionType.CHECK,
        "call": ActionType.CALL,
        "bet": ActionType.BET,
        "raise": ActionType.RAISE,
        "all_in": ActionType.RAISE,  # ALL_IN 映射为加注（金额=总筹码）
        "allin": ActionType.RAISE,
        "all-in": ActionType.RAISE,
    }

    @classmethod
    def parse_action(
        cls,
        raw_response: str,
        player: Player,
        game: GameState,
    ) -> Optional[Action]:
        """将 LLM 原始响应解析为 Action 对象。

        Args:
            raw_response: LLM 返回的原始文本。
            player: 当前行动的玩家。
            game: 当前游戏状态。

        Returns:
            解析并验证后的 Action，如果无法解析则返回 None。
        """
        # 1. 提取 JSON
        json_str = cls._extract_json(raw_response)
        if json_str is None:
            logger.warning("无法从 LLM 响应中提取 JSON: %s", raw_response[:100])
            return None

        # 2. JSON 解析
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.warning("JSON 解析失败: %s — %s", e, json_str[:100])
            return None

        if not isinstance(data, dict):
            logger.warning("JSON 顶层不是对象: %s", type(data))
            return None

        # 3. 提取动作类型
        action_str = str(data.get("action", "")).strip().lower().replace(" ", "_")
        if action_str not in cls._ACTION_MAP:
            logger.warning("未知的动作类型: %s", action_str)
            return None
        action_type = cls._ACTION_MAP[action_str]

        # 4. 提取金额
        amount = 0
        if action_type in (ActionType.BET, ActionType.RAISE):
            raw_amount = data.get("amount", 0)
            try:
                amount = int(raw_amount)
            except (ValueError, TypeError):
                logger.warning("无效的金额: %s", raw_amount)
                return None

        # 5. 处理 ALL_IN 语义
        if action_str in ("all_in", "allin", "all-in"):
            amount = player.chips + player.current_bet

        # 6. 合法性验证
        legal_actions = game.get_legal_actions(player)
        if action_type not in legal_actions:
            # 特殊处理：LLM 返回 RAISE 但仅 BET 合法（current_bet == 0）
            if action_type == ActionType.RAISE and ActionType.BET in legal_actions:
                action_type = ActionType.BET
            else:
                logger.warning(
                    "非法动作: %s 不在合法列表 %s 中",
                    action_type.name,
                    [a.name for a in legal_actions],
                )
                return None

        # 7. 金额裁剪
        if action_type in (ActionType.BET, ActionType.RAISE):
            min_raise = game.get_min_raise_amount(player)
            max_bet = game.get_max_bet(player)

            # 裁剪到合法范围
            amount = max(min_raise, min(amount, max_bet))
            amount = min(amount, player.chips + player.current_bet)

            # 检测全下
            is_all_in = amount >= player.chips + player.current_bet
            if amount <= 0:
                logger.warning("金额无效: %d", amount)
                return None
        else:
            is_all_in = amount >= player.chips + player.current_bet if amount > 0 else False

        # 8. 构造 Action
        is_all_in_flag = is_all_in or amount >= player.chips + player.current_bet
        return Action(
            player_name=player.name,
            action_type=action_type,
            amount=amount,
            is_all_in=is_all_in_flag,
        )

    @classmethod
    def _extract_json(cls, text: str) -> Optional[str]:
        """从文本中提取 JSON 字符串。

        处理常见的 LLM 输出格式：
        - 纯 JSON: {"action": ...}
        - Markdown 代码块: ```json\n{...}\n```
        - 带前缀文本: Here is my decision: {...}
        """
        if not text or not text.strip():
            return None

        text = text.strip()

        # 尝试直接解析（纯 JSON）
        if text.startswith("{") and text.endswith("}"):
            return text

        # 尝试从 markdown 代码块提取
        # 模式: ```json ... ```
        md_pattern = r"```(?:json)?\s*\n?([\s\S]*?)\n?```"
        match = re.search(md_pattern, text)
        if match:
            candidate = match.group(1).strip()
            if candidate.startswith("{") and candidate.endswith("}"):
                return candidate

        # 尝试提取第一个完整的 JSON 对象
        brace_start = text.find("{")
        if brace_start >= 0:
            brace_count = 0
            for i in range(brace_start, len(text)):
                if text[i] == "{":
                    brace_count += 1
                elif text[i] == "}":
                    brace_count -= 1
                    if brace_count == 0:
                        return text[brace_start : i + 1]

        return None

    @classmethod
    def extract_reasoning(cls, raw_response: str) -> str:
        """从 LLM 响应中提取推理文本（用于日志/显示）。"""
        json_str = cls._extract_json(raw_response)
        if json_str is None:
            return raw_response[:200]
        try:
            data = json.loads(json_str)
            return str(data.get("reasoning", ""))
        except json.JSONDecodeError:
            return raw_response[:200]
