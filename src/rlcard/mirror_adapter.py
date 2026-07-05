"""镜像适配器 —— GameState ↔ RLCard observation 单向翻译。

职责：
    1. 将 GameState 翻译为 RLCard observation（含 BB 归一化筹码编码）
    2. 将 RLCard action_id 映射回引擎 Action（含半池/满池/全下金额计算）
    3. 不维护第二份游戏状态（镜像模式）

RLCard NoLimitHoldem 动作抽象：
    0: FOLD
    1: CHECK / CALL
    2: RAISE_HALF_POT  （总投入 = to_call + 0.5 * 行动前底池）
    3: RAISE_POT       （总投入 = to_call + 1.0 * 行动前底池）
    4: ALL_IN

Observation 编码（54 维，见 ``state_encoder``）：
    [0:52)   卡牌 one-hot：底牌 + 公共牌可见位置置 1
    [52]     my_chips / big_blind
    [53]     max(active_chips) / big_blind（与 RLCard env 对齐）
"""

from __future__ import annotations

from typing import List, TYPE_CHECKING

from src.engine.card import Card
from src.engine.game import Action, ActionType, GameState
from src.engine.player import Player
from src.rlcard import state_encoder

if TYPE_CHECKING:
    import numpy as np


# RLCard 动作空间（与 rlcard.envs.nolimitholdem 对齐）
RLCARD_FOLD = 0
RLCARD_CHECK_CALL = 1
RLCARD_RAISE_HALF_POT = 2
RLCARD_RAISE_POT = 3
RLCARD_ALL_IN = 4

# RLCard 全套合法动作 ID（标准 5 动作空间）
ALL_RLCARD_ACTIONS = [RLCARD_FOLD, RLCARD_CHECK_CALL, RLCARD_RAISE_HALF_POT, RLCARD_RAISE_POT, RLCARD_ALL_IN]


class MirrorAdapter:
    """GameState ↔ RLCard observation 镜像翻译器。"""

    # ----------------------------------------------------------------
    # 卡牌索引转换
    # ----------------------------------------------------------------

    @staticmethod
    def card_to_rlcard_index(card: Card) -> int:
        """将引擎 Card 转换为 RLCard 0–51 卡牌索引。"""
        return state_encoder.card_to_rlcard_index(card)

    # ----------------------------------------------------------------
    # Observation 编码
    # ----------------------------------------------------------------

    @staticmethod
    def encode_observation(
        game_state: GameState,
        player: Player,
    ) -> "np.ndarray":  # noqa: F821
        """构建 54 维 observation 向量。

        Returns:
            shape (54,) float32 numpy array.
        """
        return state_encoder.encode_from_game_state(game_state, player)

    # ----------------------------------------------------------------
    # 合法 RLCard 动作枚举（含切断不合法加注层级）
    # ----------------------------------------------------------------

    @staticmethod
    def get_legal_rlcard_actions(
        game_state: GameState, player: Player,
    ) -> List[int]:
        """返回合法的 RLCard action_id 列表。

        规则：
            - FOLD (0) 始终位列第一
            - CHECK/CALL (1) = 引擎 CHECK 或 CALL 之一合法
            - RAISE_HALF_POT (2) 仅当半池加注总投入 ≥ min_raise
            - RAISE_POT (3)   仅当满池加注总投入 ≥ min_raise
            - ALL_IN (4)      仅当全下有实质加注含义

        各加注层级按 pot-size total 公式计算后 clamped 到
        [min_raise, max_bet]，不满足 min_raise 的层级被剔除。
        """
        legal_types = game_state.get_legal_actions(player)
        to_call = game_state.current_bet - player.current_bet
        pot_before = game_state.pot.total
        min_raise = game_state.get_min_raise_amount(player)
        max_bet = game_state.get_max_bet(player)
        max_possible = player.chips + player.current_bet

        def clamped_total(raise_addon: float) -> int:
            total = to_call + int(raise_addon)
            total = max(total, min_raise)
            total = min(total, max_bet, max_possible)
            return total

        result: List[int] = [RLCARD_FOLD]

        # CHECK/CALL
        if ActionType.CHECK in legal_types or ActionType.CALL in legal_types:
            result.append(RLCARD_CHECK_CALL)

        # 加注层级：BET 或 RAISE 之一合法
        can_raise = ActionType.RAISE in legal_types or ActionType.BET in legal_types

        if can_raise:
            half_total = clamped_total(0.5 * pot_before)
            if half_total >= min_raise:
                result.append(RLCARD_RAISE_HALF_POT)

            full_total = clamped_total(1.0 * pot_before)
            if full_total >= min_raise:
                result.append(RLCARD_RAISE_POT)

            if max_possible >= min_raise:
                result.append(RLCARD_ALL_IN)

        # 去重排序
        return sorted(set(result))

    # ----------------------------------------------------------------
    # RLCard action_id → 引擎 Action
    # ----------------------------------------------------------------

    @staticmethod
    def rlcard_action_to_engine(
        game_state: GameState,
        player: Player,
        action_id: int,
    ) -> Action:
        """将 RLCard action_id 映射为引擎 Action（含金额计算）。

        Args:
            game_state: 当前 GameState。
            player: 当前行动玩家。
            action_id: RLCard 动作 ID (0–4)。

        Returns:
            引擎 Action，金额经 min/max clamp 且标记 is_all_in。
        """
        to_call = game_state.current_bet - player.current_bet
        pot_before = game_state.pot.total
        min_raise = game_state.get_min_raise_amount(player)
        max_bet = game_state.get_max_bet(player)
        max_possible = player.chips + player.current_bet

        # --- FOLD ---
        if action_id == RLCARD_FOLD:
            return Action(player.name, ActionType.FOLD)

        # --- CHECK / CALL ---
        if action_id == RLCARD_CHECK_CALL:
            if to_call == 0:
                return Action(player.name, ActionType.CHECK)
            else:
                return Action(player.name, ActionType.CALL)

        # --- RAISE 层级 ---
        if action_id == RLCARD_RAISE_HALF_POT:
            amount = to_call + int(0.5 * pot_before)
        elif action_id == RLCARD_RAISE_POT:
            amount = to_call + int(1.0 * pot_before)
        elif action_id == RLCARD_ALL_IN:
            amount = max_possible
        else:
            # 未知 action_id：降级为 check/call
            if to_call == 0:
                return Action(player.name, ActionType.CHECK)
            else:
                return Action(player.name, ActionType.CALL)

        # Clamp & finalize
        amount = max(amount, min_raise)
        amount = min(amount, max_bet, max_possible)

        is_all_in = amount >= max_possible
        action_type = ActionType.BET if game_state.current_bet == 0 else ActionType.RAISE
        return Action(player.name, action_type, amount=amount, is_all_in=is_all_in)
