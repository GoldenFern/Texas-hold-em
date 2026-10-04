"""state_encoder 单元测试 —— 不依赖 rlcard。"""

from __future__ import annotations

import pytest

from src.engine.card import Card
from src.rlcard.state_encoder import (
    MAX_CHIPS_IDX,
    MY_CHIPS_IDX,
    OBS_DIM,
    card_to_rlcard_index,
    encode_from_game_state,
    encode_obs_vector,
)
from tests.test_rlcard_bot import make_heads_up_game, make_heads_up_game_custom


class TestStateEncoderConstants:
    """Observation 常量。"""

    def test_obs_dim(self) -> None:
        assert OBS_DIM == 54
        assert MY_CHIPS_IDX == 52
        assert MAX_CHIPS_IDX == 53


class TestCardIndex:
    """卡牌索引。"""

    def test_ace_of_hearts(self) -> None:
        assert card_to_rlcard_index(Card.from_str("Ah")) == 25

    def test_all_cards_unique(self) -> None:
        from src.utils.constants import Rank, Suit

        indices = [
            card_to_rlcard_index(Card(rank, suit))
            for suit in Suit
            for rank in Rank
        ]
        assert len(indices) == 52
        assert len(set(indices)) == 52


class TestEncodeObsVector:
    """核心向量编码。"""

    def test_shape_and_slots(self) -> None:
        obs = encode_obs_vector([0, 25], my_chips_bb=100.0, max_chips_bb=120.0)
        assert obs.shape == (OBS_DIM,)
        assert obs[0] == 1.0
        assert obs[25] == 1.0
        assert obs[MY_CHIPS_IDX] == pytest.approx(100.0)
        assert obs[MAX_CHIPS_IDX] == pytest.approx(120.0)


class TestEncodeFromGameState:
    """GameState 编码。"""

    def test_max_chips_slot_matches_rlcard_convention(self) -> None:
        game = make_heads_up_game()
        game.start_new_hand()
        hero = game.players[0]
        hero.hole_cards = Card.from_str_multi("Ah Kh")
        hero.chips = 500
        game.players[1].chips = 200

        obs = encode_from_game_state(game, hero)
        assert obs[52] == pytest.approx(50.0, rel=1e-4)
        assert obs[53] == pytest.approx(50.0, rel=1e-4)

    def test_bb_normalization_invariant(self) -> None:
        game_a = make_heads_up_game_custom(1000, 1000, bb=10)
        game_a.start_new_hand()
        hero_a = game_a.players[0]
        hero_a.hole_cards = Card.from_str_multi("Ah Kh")

        game_b = make_heads_up_game_custom(100, 100, bb=1)
        game_b.start_new_hand()
        hero_b = game_b.players[0]
        hero_b.hole_cards = Card.from_str_multi("Ah Kh")

        obs_a = encode_from_game_state(game_a, hero_a)
        obs_b = encode_from_game_state(game_b, hero_b)

        assert (obs_a[:52] == obs_b[:52]).all()
        assert obs_a[52] == pytest.approx(obs_b[52], rel=0.15)
        assert obs_a[53] == pytest.approx(obs_b[53], rel=0.15)
