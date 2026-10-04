"""RLCard observation 编码 —— 训练与推理共享。

与 RLCard ``no-limit-holdem`` 环境 ``_extract_state`` 对齐：
    [0:52)  可见牌 one-hot
    [52]    my_chips（BB 单位）
    [53]    max(all_chips)（BB 单位）

镜像适配器与离线训练脚本均从此模块导入，避免 train/serve 编码漂移。
"""

from __future__ import annotations

from typing import Iterable, List, TYPE_CHECKING

from src.engine.card import Card

if TYPE_CHECKING:
    import numpy as np
    from src.engine.game import GameState
    from src.engine.player import Player

OBS_DIM = 54
CARD_DIM = 52
MY_CHIPS_IDX = 52
MAX_CHIPS_IDX = 53


def card_to_rlcard_index(card: Card) -> int:
    """将引擎 Card 转换为 RLCard 0–51 卡牌索引。

    RLCard 编码规则：
        suit: S=0, H=1, D=2, C=3
        rank: 2→0, 3→1, ..., K→11, A→12
        index = suit * 13 + rank
    """
    rl_suit = 3 - card.suit.value
    rl_rank = card.rank.value - 2
    return rl_suit * 13 + rl_rank


def encode_obs_vector(
    card_indices: Iterable[int],
    my_chips_bb: float,
    max_chips_bb: float,
) -> "np.ndarray":
    """构建 54 维 observation 向量（核心编码逻辑）。"""
    import numpy as np

    obs = np.zeros(OBS_DIM, dtype=np.float32)
    for idx in card_indices:
        obs[idx] = 1.0
    obs[MY_CHIPS_IDX] = float(my_chips_bb)
    obs[MAX_CHIPS_IDX] = float(max_chips_bb)
    return obs


def _active_player_chips_bb(game_state: "GameState", big_blind: float) -> List[float]:
    """返回未弃牌玩家的筹码（BB 单位）。"""
    chips: List[float] = []
    for p in game_state.players:
        if not p.is_folded:
            chips.append(float(p.chips) / big_blind)
    return chips


def encode_from_game_state(
    game_state: "GameState",
    player: "Player",
) -> "np.ndarray":
    """从 GameState 构建与 RLCard 环境兼容的 observation。"""
    bb = float(game_state.big_blind)
    card_indices = [
        card_to_rlcard_index(card) for card in player.hole_cards
    ]
    card_indices.extend(
        card_to_rlcard_index(card) for card in game_state.community_cards
    )

    my_chips_bb = float(player.chips) / bb
    active_chips = _active_player_chips_bb(game_state, bb)
    max_chips_bb = max(active_chips) if active_chips else my_chips_bb

    return encode_obs_vector(card_indices, my_chips_bb, max_chips_bb)


def assert_obs_compatible_with_rlcard() -> None:
    """启动时校验 observation 维度与 RLCard 环境一致。"""
    import rlcard

    env = rlcard.make(
        "no-limit-holdem",
        config={"seed": 42, "game_num_players": 2},
    )
    state_shape = env.state_shape[0]
    if isinstance(state_shape, list):
        dim = state_shape[0]
    else:
        dim = state_shape
    if dim != OBS_DIM:
        raise ValueError(
            f"state_encoder OBS_DIM={OBS_DIM} 与 RLCard env state_shape={dim} 不一致"
        )
