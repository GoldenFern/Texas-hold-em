"""RLCard 驱动的扑克机器人 —— BotBase 子类。

使用镜像适配器将 GameState 单向翻译为 RLCard observation，
查询 RLCard agent 后将 action_id 映射回引擎 Action。

Phase A：RandomAgent（无需训练）。
Phase B：从 ``models/rlcard/`` 加载 DQN / DMC / NFSP 策略工件。

rlcard 是可选依赖；未安装时构造器抛出清晰的 ImportError。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from src.ai.bots import BotBase, BotStyle, BOT_PROFILES
from src.engine.game import Action, ActionType, GameState
from src.engine.player import Player
from src.rlcard.config import RLCardConfig
from src.rlcard.policy_loader import build_agent_state, load_policy_agent
from src.rlcard.state_encoder import OBS_DIM


class RLCardBot(BotBase):
    """RLCard 驱动的扑克机器人。

    继承 BotBase，覆写 decide() 方法接入 RLCard agent 决策。
    rlcard 包是可选依赖。

    Attributes:
        model_path: 训练好的策略工件路径（None 且 agent_type=random 时用 RandomAgent）。
        _agent: RLCard agent 实例（RandomAgent 或加载的模型）。
        _num_actions: RLCard 环境动作空间大小。
    """

    def __init__(
        self,
        name: str,
        model_path: Optional[str] = None,
        seed: int = 42,
        rlcard_config: Optional[RLCardConfig] = None,
    ) -> None:
        profile = BOT_PROFILES[BotStyle.SHARK]
        super().__init__(name, profile, seed)

        if rlcard_config is not None:
            self._agent_type = rlcard_config.agent_type
            if rlcard_config.model_path is not None:
                model_path = rlcard_config.model_path
            self._rlcard_config = rlcard_config
        else:
            self._agent_type = "random"
            self._rlcard_config = None

        self._model_path = model_path
        if self._model_path and self._agent_type == "random":
            self._agent_type = "dqn"
        self._agent: Any = None
        self._num_actions: int = 5
        self._rl_stats: Dict[str, int] = {
            "rl_decisions": 0,
            "illegal_fallbacks": 0,
        }
        self._setup_agent()

    def _setup_agent(self) -> None:
        """初始化 RLCard agent。

        Raises:
            ImportError: rlcard 包未安装。
        """
        try:
            import rlcard  # noqa: F401
        except ModuleNotFoundError:
            raise ImportError(
                "rlcard 包未安装。要使用 RLCardBot，请安装 rlcard：\n"
                "    pip install rlcard[torch]"
            ) from None

        try:
            self._agent, self._agent_type = load_policy_agent(
                self._agent_type,
                self._model_path,
                num_actions=self._num_actions,
                state_shape=OBS_DIM,
            )
        except FileNotFoundError as e:
            raise RuntimeError(str(e)) from e
        except Exception as e:
            raise RuntimeError(
                f"无法加载 RLCard 策略（type={self._agent_type}, "
                f"path={self._model_path}）：{e}"
            ) from e

    # ----------------------------------------------------------------
    # 核心决策
    # ----------------------------------------------------------------

    def decide(self, game_state: GameState, player: Player) -> Action:
        """核心决策：GameState → RLCard obs → agent → 引擎 Action。"""
        self.hands_seen += 1

        legal = game_state.get_legal_actions(player)
        if not legal:
            return Action(player.name, ActionType.FOLD)
        if len(legal) == 1:
            return Action(player.name, legal[0])

        from src.rlcard.mirror_adapter import MirrorAdapter

        obs_array = MirrorAdapter.encode_observation(game_state, player)
        legal_rl = MirrorAdapter.get_legal_rlcard_actions(game_state, player)

        state = build_agent_state(obs_array, legal_rl, self._agent_type)

        action_id, _ = self._agent.eval_step(state)
        self._rl_stats["rl_decisions"] += 1

        engine_action = MirrorAdapter.rlcard_action_to_engine(
            game_state, player, action_id,
        )

        if engine_action.action_type not in legal:
            self._rl_stats["illegal_fallbacks"] += 1
            if ActionType.CHECK in legal:
                return Action(player.name, ActionType.CHECK)
            if ActionType.CALL in legal:
                return Action(player.name, ActionType.CALL)
            return Action(player.name, ActionType.FOLD)

        return engine_action

    # ----------------------------------------------------------------
    # 统计
    # ----------------------------------------------------------------

    @property
    def rl_stats(self) -> Dict[str, int]:
        """返回 RL 决策统计。"""
        return dict(self._rl_stats)

    def reset_stats(self) -> None:
        super().reset_stats()
        self._rl_stats = {"rl_decisions": 0, "illegal_fallbacks": 0}

    def __repr__(self) -> str:
        source = self._model_path or f"{self._agent_type}:default"
        return f"RLCardBot({self.name}, {source})"
