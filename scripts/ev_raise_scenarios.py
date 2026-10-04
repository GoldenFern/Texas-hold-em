"""四类典型场景的 EV-加注曲线批量分析(复用 ev_raise_curve 模型)。

模型与 scripts/ev_raise_curve.py 完全一致:英雄全知对手底牌求权益,
对手仅知自己手牌与公共牌,按底池赔率阈值序贯跟注。

统一基线参数(可用 CLI 覆盖):
    P=100(底池,含本街已投入)、C=30(跟注成本)、对手 2 人、
    R ∈ [0, 2P]、手牌抽样 300、对手权益 MC 400 次;
    翻场景 runout 用 MC 400 次,翻后场景精确枚举。

场景:
    1a 翻前 7c2d(异色垃圾牌)
    1b 翻前 AhKh(AK 同色)
    2  AhKh 翻牌 9d6c2s(完全错过,无对无听)
    3  6h5h 翻牌 8h7h2c(两头顺+同花听牌,约 15 outs)
    4a AhKh 河牌 Qh8h3h5d9s(A 高同花坚果)
    4b AhKh 河牌 Qd8c3c5s9d(仅 A 高牌)

输出:tmp/ev_raise_curves/ 下每个场景一张 PNG + combined.png 汇总图,
并打印权益、EV(Call)、最优 R*、弃牌率等汇总表。

用法:
    python scripts/ev_raise_scenarios.py
    python scripts/ev_raise_scenarios.py --workers 4 --samples 200
"""

from __future__ import annotations

import argparse
import sys
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import List, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402

from scripts.ev_raise_curve import (  # noqa: E402
    build_samples,
    ev_call,
    ev_raise,
    parse_cards,
    plot_curve,
)

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Scenario:
    """单个分析场景定义。"""

    key: str
    label: str
    hero: str
    board: str
    runout_sims: int = 0
    note: str = ""


SCENARIOS: List[Scenario] = [
    Scenario(
        "preflop_72o", "翻前 72o", "7c 2d", "", runout_sims=400,
        note="垃圾牌,无摊牌价值,只剩弃牌收益",
    ),
    Scenario(
        "preflop_AKs", "翻前 AKs", "Ah Kh", "", runout_sims=400,
        note="顶级起手牌,价值加注场景",
    ),
    Scenario(
        "flop_AKs_miss", "翻牌 AKs 全错过", "Ah Kh", "9d 6c 2s",
        note="无对无听,仅两张大牌",
    ),
    Scenario(
        "flop_65s_oesd", "翻牌 65s 强听牌", "6h 5h", "8h 7h 2c",
        note="两头顺+同花听牌(约 15 outs)",
    ),
    Scenario(
        "river_nuts", "河牌 A 高同花坚果", "Ah Kh", "Qh 8h 3h 5d 9s",
        note="A 高同花为坚果,对任意跟注者权益=1",
    ),
    Scenario(
        "river_air", "河牌仅 A 高牌", "Ah Kh", "Qd 8c 3c 5s 9d",
        note="无同花可能,A 高牌,纯诈唬",
    ),
]


@dataclass(frozen=True)
class RunParams:
    """跨场景共享的模型参数(可 pickle 传给子进程)。"""

    pot: float
    to_call: float
    opponents: int
    samples: int
    p_sims: int
    rs: Tuple[float, ...]


@dataclass
class Result:
    """单个场景的计算结果。"""

    key: str
    label: str
    note: str
    p_all: float
    call_ev: float
    best: int
    fold_at_best: float
    rs: List[float]
    evs: List[float]
    folds: List[float]
    out_path: str


def run_scenario(sc: Scenario, params: RunParams, out_dir: str) -> Result:
    """构建抽样、扫描 R 网格、保存单场景图片,返回结果。"""
    hero = parse_cards(sc.hero)
    board = parse_cards(sc.board)
    samples = build_samples(
        hero, board, params.opponents, params.samples,
        20261003, params.p_sims, sc.runout_sims,
    )
    evs: List[float] = []
    folds: List[float] = []
    for r in params.rs:
        ev, fold_p = ev_raise(
            samples, params.pot, params.to_call, 0.0,
            [0.0] * params.opponents, r,
        )
        evs.append(ev)
        folds.append(fold_p)

    call_ev = ev_call(samples, params.pot, params.to_call)
    p_all = sum(s.equity[-1] for s in samples) / len(samples)
    best = max(range(len(evs)), key=lambda i: evs[i])

    board_txt = " ".join(c.short_str for c in board) if board else "翻前"
    title = (
        f"{sc.label} | {' '.join(c.short_str for c in hero)} | {board_txt}\n"
        f"P={params.pot:.0f} C={params.to_call:.0f} "
        f"对手={params.opponents} | {sc.note}"
    )
    out_path = Path(out_dir) / f"{sc.key}.png"
    plot_curve(list(params.rs), evs, call_ev, params.pot, title, out_path)
    return Result(
        key=sc.key, label=sc.label, note=sc.note,
        p_all=p_all, call_ev=call_ev, best=best,
        fold_at_best=folds[best],
        rs=list(params.rs), evs=evs, folds=folds,
        out_path=str(out_path),
    )


def plot_combined(results: Sequence[Result], pot: float, out_path: Path) -> None:
    """把所有场景画进 3x2 汇总图。"""
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial"]
    plt.rcParams["axes.unicode_minus"] = False

    fig, axes = plt.subplots(3, 2, figsize=(13.5, 14.0))
    for ax, res in zip(axes.flat, results):
        ax.plot(res.rs, res.evs, "-o", ms=3, color="#1f77b4", label="EV(R)")
        ax.axhline(res.call_ev, color="#d62728", ls="--", label="EV(Call)")
        ax.axhline(0.0, color="#555555", ls=":", label="EV(Fold)")
        ax.scatter(
            [res.rs[res.best]], [res.evs[res.best]],
            color="#ff7f0e", zorder=5, label="R*",
        )
        ax.set_title(
            f"{res.label}   (p={res.p_all:.3f}, R*={res.rs[res.best]:.0f}, "
            f"EV*={res.evs[res.best]:.1f}, 弃牌率={res.fold_at_best:.2f})",
            fontsize=10,
        )
        ax.set_xlabel("加注增量 R(筹码)")
        ax.set_ylabel("期望收益 EV(筹码)")
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8, loc="best")
    fig.suptitle(
        f"EV-加注曲线场景汇总 | P={pot:.0f} | 对手=2 | 曲线均值单位:筹码",
        fontsize=13,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.98))
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(description="批量场景 EV-加注曲线")
    parser.add_argument("--pot", type=float, default=100.0)
    parser.add_argument("--to-call", type=float, default=30.0)
    parser.add_argument("--opponents", type=int, default=2)
    parser.add_argument("--samples", type=int, default=300)
    parser.add_argument("--p-sims", type=int, default=400)
    parser.add_argument("--r-points", type=int, default=25)
    parser.add_argument("--r-max", type=float, default=None)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--out-dir", default="")
    parser.add_argument(
        "--only", default="",
        help="仅运行指定场景 key(逗号分隔),默认全部",
    )
    args = parser.parse_args()

    r_max = args.r_max if args.r_max is not None else 2.0 * args.pot
    rs = tuple(r_max * i / (args.r_points - 1) for i in range(args.r_points))
    params = RunParams(
        pot=args.pot, to_call=args.to_call, opponents=args.opponents,
        samples=args.samples, p_sims=args.p_sims, rs=rs,
    )
    out_dir = Path(args.out_dir) if args.out_dir else ROOT / "tmp" / "ev_raise_curves"
    out_dir.mkdir(parents=True, exist_ok=True)

    wanted = {k for k in args.only.split(",") if k} if args.only else None
    todo = [s for s in SCENARIOS if wanted is None or s.key in wanted]
    if not todo:
        parser.error(f"--only 未匹配任何场景: {args.only}")

    print(f"参数: P={args.pot} C={args.to_call} 对手={args.opponents} "
          f"抽样={args.samples} p_sims={args.p_sims} "
          f"R∈[0,{r_max:.0f}]/{args.r_points}点 场景数={len(todo)}")

    with ProcessPoolExecutor(max_workers=min(args.workers, len(todo))) as pool:
        results = list(pool.map(
            run_scenario, todo,
            [params] * len(todo), [str(out_dir)] * len(todo),
        ))

    print()
    header = (
        f"{'场景':<18} {'权益p':>8} {'EV(Call)':>10} {'R*':>7} "
        f"{'EV*':>9} {'弃牌率*':>8} {'EV(0)':>9} {'EV(2P)':>9}"
    )
    print(header)
    print("-" * len(header))
    for res in results:
        print(
            f"{res.key:<18} {res.p_all:>8.4f} {res.call_ev:>10.2f} "
            f"{res.rs[res.best]:>7.1f} {res.evs[res.best]:>9.2f} "
            f"{res.fold_at_best:>8.3f} {res.evs[0]:>9.2f} "
            f"{res.evs[-1]:>9.2f}"
        )

    combined = out_dir / "combined.png"
    plot_combined(results, args.pot, combined)
    print(f"\n单场景图片目录: {out_dir}")
    print(f"汇总图: {combined}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
