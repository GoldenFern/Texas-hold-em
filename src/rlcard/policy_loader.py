"""RLCard 策略工件加载 —— 按 agent_type 恢复推理 agent。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.rlcard.state_encoder import OBS_DIM


def _resolve_model_path(model_path: str) -> Path:
    path = Path(model_path)
    if not path.is_file():
        raise FileNotFoundError(f"策略工件不存在: {model_path}")
    return path


def load_policy_agent(
    agent_type: str,
    model_path: Optional[str] = None,
    *,
    num_actions: int = 5,
    state_shape: int = OBS_DIM,
    player_position: int = 0,
    device: Optional[Any] = None,
) -> Tuple[Any, str]:
    """按配置加载 RLCard 推理 agent。

    Args:
        agent_type: ``random`` | ``dqn`` | ``dmc`` | ``nfsp``
        model_path: 训练产出的工件路径（random 可省略）
        num_actions: 动作空间大小
        state_shape: observation 维度
        player_position: DMC 多玩家工件中的座位索引
        device: PyTorch device（默认 CPU）

    Returns:
        (agent, resolved_agent_type)
    """
    normalized = agent_type.lower().strip()

    if normalized == "random":
        from rlcard.agents import RandomAgent
        return RandomAgent(num_actions=num_actions), "random"

    if model_path is None:
        raise ValueError(f"agent_type={agent_type!r} 需要 model_path")

    path = _resolve_model_path(model_path)

    if normalized == "dqn":
        import torch
        from rlcard.agents import DQNAgent

        checkpoint = torch.load(str(path), map_location="cpu", weights_only=False)
        if isinstance(checkpoint, DQNAgent):
            return checkpoint, "dqn"
        return DQNAgent.from_checkpoint(checkpoint=checkpoint), "dqn"

    if normalized == "nfsp":
        import torch
        from rlcard.agents import NFSPAgent

        checkpoint = torch.load(str(path), map_location="cpu", weights_only=False)
        if isinstance(checkpoint, NFSPAgent):
            return checkpoint, "nfsp"
        return NFSPAgent.from_checkpoint(checkpoint=checkpoint), "nfsp"

    if normalized == "dmc":
        import torch
        from rlcard.agents.dmc_agent.model import DMCAgent

        checkpoint = torch.load(str(path), map_location="cpu", weights_only=False)
        if isinstance(checkpoint, DMCAgent):
            agent = checkpoint
        else:
            agent = DMCAgent(
                state_shape=[state_shape],
                action_shape=[num_actions],
                device="cpu",
            )
            if isinstance(checkpoint, dict) and "model_state_dict" in checkpoint:
                state_dicts = checkpoint["model_state_dict"]
                if not isinstance(state_dicts, list):
                    raise ValueError("DMC checkpoint 缺少 model_state_dict 列表")
                if player_position >= len(state_dicts):
                    raise ValueError(
                        f"DMC player_position={player_position} 超出 checkpoint 范围"
                    )
                agent.load_state_dict(state_dicts[player_position])
            else:
                agent.load_state_dict(checkpoint)
        if device is not None:
            agent.set_device(str(device))
        agent.eval()
        return agent, "dmc"

    raise ValueError(
        f"不支持的 agent_type: {agent_type!r}；"
        "可选: random, dqn, dmc, nfsp"
    )


def build_agent_state(
    obs_array: Any,
    legal_action_ids: List[int],
    agent_type: str,
) -> Dict[str, Any]:
    """按 agent 类型构建 eval_step 所需的 state 字典。"""
    normalized = agent_type.lower().strip()

    if normalized == "dmc":
        from collections import OrderedDict
        return {
            "obs": obs_array,
            "legal_actions": OrderedDict((action_id, None) for action_id in legal_action_ids),
            "raw_legal_actions": legal_action_ids,
        }

    return {
        "obs": obs_array,
        "legal_actions": legal_action_ids,
    }
