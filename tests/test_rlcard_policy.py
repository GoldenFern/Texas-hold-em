"""RLCard 策略加载与训练工件测试。

需要 rlcard + torch 的用例使用 ``pytest.importorskip`` 守护。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.engine.card import Card
from src.rlcard.policy_loader import build_agent_state, load_policy_agent
from src.rlcard.state_encoder import OBS_DIM
from tests.test_rlcard_bot import make_heads_up_game


def _require_rlcard_torch() -> None:
    pytest.importorskip("rlcard", reason="rlcard 未安装")
    pytest.importorskip("torch", reason="torch 未安装")


class TestBuildAgentState:
    """eval_step state 字典格式。"""

    def test_dqn_uses_list_legal_actions(self) -> None:
        import numpy as np

        obs = np.zeros(OBS_DIM, dtype=np.float32)
        state = build_agent_state(obs, [0, 1, 4], "dqn")
        assert state["legal_actions"] == [0, 1, 4]

    def test_dmc_uses_ordered_dict_legal_actions(self) -> None:
        import numpy as np

        obs = np.zeros(OBS_DIM, dtype=np.float32)
        state = build_agent_state(obs, [0, 1, 4], "dmc")
        assert list(state["legal_actions"].keys()) == [0, 1, 4]


class TestLoadPolicyAgent:
    """策略工件加载。"""

    def test_random_agent_without_model(self) -> None:
        _require_rlcard_torch()
        agent, resolved = load_policy_agent("random")
        assert resolved == "random"
        assert agent is not None

    def test_dqn_checkpoint_roundtrip_and_decide(self, tmp_path: Path) -> None:
        _require_rlcard_torch()
        import numpy as np
        import torch
        import rlcard
        from rlcard.agents import DQNAgent

        env = rlcard.make(
            "no-limit-holdem",
            config={"seed": 1, "game_num_players": 2, "chips_for_each": 100},
        )
        agent = DQNAgent(
            num_actions=env.num_actions,
            state_shape=env.state_shape[0],
            mlp_layers=[64, 64],
        )

        ckpt_path = tmp_path / "test_dqn.pth"
        torch.save(agent.checkpoint_attributes(), ckpt_path)

        loaded, resolved = load_policy_agent("dqn", str(ckpt_path))
        assert resolved == "dqn"

        obs = np.zeros(OBS_DIM, dtype=np.float32)
        state = build_agent_state(obs, [0, 1, 2, 3, 4], "dqn")
        action_id, _ = loaded.eval_step(state)
        assert action_id in [0, 1, 2, 3, 4]

    def test_rlcard_bot_loads_dqn_from_config(self, tmp_path: Path) -> None:
        _require_rlcard_torch()
        import torch
        import rlcard
        from rlcard.agents import DQNAgent
        from src.rlcard.config import RLCardConfig
        from src.rlcard.rlcard_bot import RLCardBot

        env = rlcard.make(
            "no-limit-holdem",
            config={"seed": 2, "game_num_players": 2},
        )
        agent = DQNAgent(
            num_actions=env.num_actions,
            state_shape=env.state_shape[0],
            mlp_layers=[64, 64],
        )
        ckpt_path = tmp_path / "bot_dqn.pth"
        torch.save(agent.checkpoint_attributes(), ckpt_path)

        cfg = RLCardConfig(agent_type="dqn", model_path=str(ckpt_path))
        bot = RLCardBot("Trained", rlcard_config=cfg)

        game = make_heads_up_game()
        game.start_new_hand()
        hero = game.players[0]
        hero.hole_cards = Card.from_str_multi("Ah Kh")

        action = bot.decide(game, hero)
        legal = game.get_legal_actions(hero)
        assert action.action_type in legal

    def test_missing_model_raises(self) -> None:
        _require_rlcard_torch()
        with pytest.raises(FileNotFoundError):
            load_policy_agent("dqn", "models/rlcard/does_not_exist.pth")
