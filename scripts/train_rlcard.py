#!/usr/bin/env python
"""离线 RLCard 自博弈训练 —— Phase B。

在 RLCard ``no-limit-holdem`` 沙箱内训练 DQN 或 DMC 策略，
将工件写入 ``models/rlcard/``。训练不使用镜像适配器；
启动时通过 ``state_encoder`` 校验 observation 维度一致。

用法::

    pip install rlcard[torch]
    python scripts/train_rlcard.py --algorithm dqn --num-episodes 500
    python scripts/train_rlcard.py --algorithm dmc --total-frames 50000

产出默认保存为 ``models/rlcard/nlh_dqn.pth`` 或 ``models/rlcard/nlh_dmc.tar``。
游戏中将 ``config/rlcard_config.json`` 的 ``agent_type`` / ``model_path`` 指向该文件，
或设置 ``THP_RLCARD_MODEL_PATH``。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.rlcard.config import load_rlcard_config
from src.rlcard.state_encoder import assert_obs_compatible_with_rlcard

if TYPE_CHECKING:
    from src.rlcard.config import RLCardConfig


def _default_output(algorithm: str) -> Path:
    if algorithm == "dmc":
        return PROJECT_ROOT / "models" / "rlcard" / "nlh_dmc.tar"
    return PROJECT_ROOT / "models" / "rlcard" / "nlh_dqn.pth"


def _require_training_deps() -> None:
    """确保 rlcard[torch] 已安装。"""
    try:
        import rlcard  # noqa: F401
        import torch  # noqa: F401
    except ModuleNotFoundError as e:
        print(
            "需要 rlcard 与 torch。请安装：\n"
            "    pip install -r requirements-rlcard.txt",
            file=sys.stderr,
        )
        raise SystemExit(1) from e


def train_dqn(args: argparse.Namespace, rlcard_config: "RLCardConfig") -> Path:
    import torch
    import rlcard
    from rlcard.agents import DQNAgent, RandomAgent
    from rlcard.utils import get_device, reorganize, set_seed

    device = get_device()
    set_seed(args.seed)

    env = rlcard.make(
        "no-limit-holdem",
        config={
            "seed": args.seed,
            "game_num_players": 2,
            "chips_for_each": rlcard_config.effective_stack_depth,
        },
    )

    hp = rlcard_config.hyperparameters
    agent = DQNAgent(
        num_actions=env.num_actions,
        state_shape=env.state_shape[0],
        mlp_layers=[64, 64],
        learning_rate=hp.learning_rate,
        batch_size=hp.batch_size,
        replay_memory_size=hp.buffer_size,
        train_every=hp.train_every,
        update_target_estimator_every=hp.update_target_every,
        device=device,
    )

    agents = [agent]
    for _ in range(1, env.num_players):
        agents.append(RandomAgent(num_actions=env.num_actions))
    env.set_agents(agents)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    for episode in range(args.num_episodes):
        trajectories, payoffs = env.run(is_training=True)
        trajectories = reorganize(trajectories, payoffs)
        for ts in trajectories[0]:
            agent.feed(ts)

        if (episode + 1) % max(1, args.log_every) == 0:
            print(f"episode {episode + 1}/{args.num_episodes} payoff={payoffs[0]:.2f}")

    checkpoint = agent.checkpoint_attributes()
    torch.save(checkpoint, output_path)
    print(f"DQN checkpoint saved: {output_path}")
    return output_path


def train_dmc(args: argparse.Namespace, rlcard_config: "RLCardConfig") -> Path:
    import rlcard
    from rlcard.agents.dmc_agent import DMCTrainer

    output_path = Path(args.output)
    savedir = str(output_path.parent)
    xpid = output_path.stem

    env = rlcard.make(
        "no-limit-holdem",
        config={
            "seed": args.seed,
            "game_num_players": 2,
            "chips_for_each": rlcard_config.effective_stack_depth,
        },
    )

    trainer = DMCTrainer(
        env,
        cuda=args.cuda,
        xpid=xpid,
        savedir=savedir,
        save_interval=max(1, args.save_interval_minutes),
        num_actor_devices=1,
        num_actors=max(1, args.num_actors),
        training_device=args.training_device,
        total_frames=args.total_frames,
        batch_size=rlcard_config.hyperparameters.batch_size,
        learning_rate=rlcard_config.hyperparameters.learning_rate,
    )

    print(
        f"Starting DMC training: total_frames={args.total_frames}, "
        f"savedir={savedir}, xpid={xpid}"
    )
    trainer.start()

    checkpoint_src = Path(savedir) / xpid / "model.tar"
    if not checkpoint_src.is_file():
        raise FileNotFoundError(f"DMC 训练未生成 checkpoint: {checkpoint_src}")

    if checkpoint_src.resolve() != output_path.resolve():
        import shutil
        shutil.copy2(checkpoint_src, output_path)

    print(f"DMC checkpoint saved: {output_path}")
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="RLCard NLHE offline training (Phase B)")
    parser.add_argument(
        "--algorithm",
        choices=["dqn", "dmc"],
        default="dqn",
        help="Training algorithm (default: dqn)",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Output artifact path (default: models/rlcard/nlh_<algo>.pth|.tar)",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--config",
        default="",
        help="Path to rlcard_config.json (default: config/rlcard_config.json)",
    )
    parser.add_argument(
        "--num-episodes",
        type=int,
        default=500,
        help="DQN training episodes (default: 500)",
    )
    parser.add_argument(
        "--total-frames",
        type=int,
        default=50_000,
        help="DMC total environment frames (default: 50000)",
    )
    parser.add_argument("--log-every", type=int, default=50)
    parser.add_argument("--cuda", default="", help="CUDA device ids for DMC actors")
    parser.add_argument("--training-device", default="cpu", help="DMC learner device")
    parser.add_argument("--num-actors", type=int, default=2)
    parser.add_argument("--save-interval-minutes", type=int, default=1)
    return parser.parse_args()


def main() -> None:
    _require_training_deps()

    args = parse_args()
    if not args.output:
        args.output = str(_default_output(args.algorithm))

    config_path = args.config or None
    rlcard_config = load_rlcard_config(config_path=config_path)

    assert_obs_compatible_with_rlcard()
    print("state_encoder: observation dimension verified against RLCard env")

    if args.algorithm == "dqn":
        train_dqn(args, rlcard_config)
    else:
        os.environ.setdefault("CUDA_VISIBLE_DEVICES", args.cuda)
        train_dmc(args, rlcard_config)


if __name__ == "__main__":
    main()
