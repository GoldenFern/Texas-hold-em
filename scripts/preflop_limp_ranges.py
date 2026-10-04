"""翻前无加注(limp)树下的位置 Call 门槛与手牌范围。

模型(承接讨论:Call 用简单公式,不产生弃牌权):
    EV(Call | 位置) = p · (P + C) - C
    p 为 169 手牌多人胜率表(src/ai/preflop_equity.json)中的 equity share,
    P 为该位置行动时的当前底池,C 为跟注成本,全部以 BB 计。

位置差异来自 limp 顺序(两种口径,用 --field 选择):
    current: 只把"当前已进池"的对手算入 p,后面的人视作弃牌;
             P = 1.5 + k(前面 limp 的人数),对手数 = k + 2。
    full:    假设全桌都会进池,对手数 = 桌人数-1;
             P 仍只算当前底池(保守口径)。
    两种口径下,越靠后的位置面对越大底池/越多已入池筹码,门槛
    p* = C/(P+C) 越低。

对照(null)模型:若同时把"全桌都会进池"和"全桌的跟注都计入底池",
则所有位置 EV 完全相同 —— 说明位置效应全部来自上述口径选择,
而不是摊牌牌力本身。

用法:
    python scripts/preflop_limp_ranges.py --table-size 6 --field current
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List, Tuple

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.colors import ListedColormap  # noqa: E402

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_TABLE_PATH = _PROJECT_ROOT / "src" / "ai" / "preflop_equity.json"

_RANKS = list(range(14, 1, -1))  # A..2, 行/列顺序
_RANK_INDEX = {v: i for i, v in enumerate(_RANKS)}
_RANK_NAMES = "AKQJT98765432"

# 6-max 非盲注位置(前面 limp 人数递增)
_SEAT_NAMES = ["UTG", "HJ", "CO", "BTN"]


def load_table() -> Dict[Tuple[int, int, bool], List[float]]:
    """加载 169 手牌表,equity 转为 0-1。"""
    with open(_TABLE_PATH, "r", encoding="utf-8") as f:
        raw = json.load(f)
    table: Dict[Tuple[int, int, bool], List[float]] = {}
    for key, values in raw["table"].items():
        high, low, suited = key.split(",")
        table[(int(high), int(low), suited == "1")] = [
            v / 100.0 for v in values
        ]
    return table


def hand_label(high: int, low: int, suited: bool) -> str:
    if high == low:
        return _RANK_NAMES[14 - high] * 2
    return (
        _RANK_NAMES[14 - high] + _RANK_NAMES[14 - low]
        + ("s" if suited else "o")
    )


def _all_hand_classes(
    table: Dict[Tuple[int, int, bool], List[float]],
) -> List[Tuple[int, int, bool]]:
    classes = []
    for high in _RANKS:
        for low in _RANKS:
            if low > high:
                continue
            if high == low:
                classes.append((high, low, False))
            else:
                classes.append((high, low, True))
                classes.append((high, low, False))
    return classes


def seat_configs(table_size: int, field: str) -> List[dict]:
    """构造每个座位的 (P, C, n_opp);盲注位含完整跟注/过牌口径。"""
    n_non_blind = table_size - 2
    seats: List[dict] = []
    for k, name in enumerate(_SEAT_NAMES[:n_non_blind]):
        n_opp = (k + 2) if field == "current" else (table_size - 1)
        seats.append(dict(name=name, pot=1.5 + k, cost=1.0, n_opp=n_opp))
    k = n_non_blind
    n_opp = (k + 1) if field == "current" else (table_size - 1)
    seats.append(dict(
        name="SB", pot=1.5 + k, cost=0.5, n_opp=n_opp,
    ))
    seats.append(dict(
        name="BB", pot=1.5 + k + 0.5, cost=0.0, n_opp=n_opp,
    ))
    return seats


def evaluate(
    table: Dict[Tuple[int, int, bool], List[float]],
    classes: List[Tuple[int, int, bool]],
    pot: float,
    cost: float,
    n_opp: int,
) -> Dict[Tuple[int, int, bool], float]:
    """返回每个手牌类的 EV(Call)(BB 单位)。"""
    result: Dict[Tuple[int, int, bool], float] = {}
    for cls in classes:
        p = table[cls][max(0, min(7, n_opp - 1))]
        result[cls] = p * (pot + cost) - cost
    return result


def plot_seat_grid(
    ax,
    ev_map: Dict[Tuple[int, int, bool], float],
    title: str,
) -> None:
    """画 13x13 手牌矩阵,+EV 绿色、-EV 灰色,并标注 EV。"""
    grid = np.zeros((13, 13))
    callable_count = 0
    for (high, low, suited), ev in ev_map.items():
        if high == low:
            row = col = _RANK_INDEX[high]
        elif suited:
            row, col = _RANK_INDEX[high], _RANK_INDEX[low]
        else:
            row, col = _RANK_INDEX[low], _RANK_INDEX[high]
        grid[row, col] = 1.0 if ev > 0 else 0.0
        callable_count += 1 if ev > 0 else 0

    ax.imshow(grid, cmap=ListedColormap(["#e6e6e6", "#5cb85c"]), vmin=0, vmax=1)
    for (high, low, suited), ev in ev_map.items():
        if high == low:
            row = col = _RANK_INDEX[high]
        elif suited:
            row, col = _RANK_INDEX[high], _RANK_INDEX[low]
        else:
            row, col = _RANK_INDEX[low], _RANK_INDEX[high]
        ax.text(
            col, row, hand_label(high, low, suited),
            ha="center", va="center", fontsize=5.2,
            color="#0b3d0b" if ev > 0 else "#666666",
        )
    ax.set_xticks(range(13))
    ax.set_yticks(range(13))
    ax.set_xticklabels(_RANK_NAMES, fontsize=7)
    ax.set_yticklabels(_RANK_NAMES, fontsize=7)
    ax.set_title(
        f"{title}  (+EV {callable_count}/169 = {callable_count / 169:.0%})",
        fontsize=9,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="翻前 limp 树位置 Call 范围")
    parser.add_argument("--table-size", type=int, default=6)
    parser.add_argument(
        "--field", choices=["current", "full"], default="current",
        help="对手数口径:current=只算已进池,full=全桌进池",
    )
    parser.add_argument("--out", default="", help="输出 PNG 路径")
    args = parser.parse_args()

    table = load_table()
    classes = _all_hand_classes(table)

    seats = seat_configs(args.table_size, args.field)
    evs = {}
    print(
        f"桌人数={args.table_size} 对手数口径={args.field} "
        f"公式: EV = p*(P+C) - C"
    )
    print(f"{'位置':>4} {'P(BB)':>6} {'C(BB)':>6} {'对手数':>5} "
          f"{'门槛p*':>7} {'+EV手牌':>8} {'范围':>6}")
    for seat in seats:
        ev = evaluate(table, classes, seat["pot"], seat["cost"], seat["n_opp"])
        evs[seat["name"]] = (seat, ev)
        n_pos = sum(1 for v in ev.values() if v > 0)
        threshold = (
            seat["cost"] / (seat["pot"] + seat["cost"])
            if seat["cost"] > 0 else 0.0
        )
        print(
            f"{seat['name']:>4} {seat['pot']:6.1f} {seat['cost']:6.1f} "
            f"{seat['n_opp']:5d} {threshold:7.1%} {n_pos:8d} "
            f"{n_pos / len(classes):6.0%}"
        )

    # 若干代表手牌的 EV 表
    samples = ["AA", "KK", "QQ", "JJ", "TT", "AKs", "AQs", "KQs",
               "22", "54s", "76s", "A5s", "K7o", "72o", "JTo"]
    label_map = {}
    for cls in classes:
        label_map[hand_label(*cls)] = cls
    print("\n代表手牌 EV(Call) (BB):")
    header = "手牌  " + "".join(f"{s['name']:>7}" for s in seats)
    print(header)
    for label in samples:
        cls = label_map[label]
        row = "".join(
            f"{evs[s['name']][1][cls]:7.2f}" for s in seats
        )
        print(f"{label:<6}{row}")

    # 绘图:取非盲注座位(current 口径);full 口径并列对比
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial"]
    plt.rcParams["axes.unicode_minus"] = False
    non_blind = [s["name"] for s in seat_configs(args.table_size, "current")
                 if s["name"] in _SEAT_NAMES[: args.table_size - 2]]
    field_modes = ["current", "full"]
    fig, axes = plt.subplots(
        len(field_modes), len(non_blind),
        figsize=(3.6 * len(non_blind), 7.6),
    )
    if len(non_blind) == 1:
        axes = axes.reshape(len(field_modes), 1)
    for r, mode in enumerate(field_modes):
        mode_seats = seat_configs(args.table_size, mode)
        for c, name in enumerate(non_blind):
            seat = next(s for s in mode_seats if s["name"] == name)
            ev = evaluate(
                table, classes, seat["pot"], seat["cost"], seat["n_opp"]
            )
            plot_seat_grid(
                axes[r][c], ev,
                f"{name} [{mode}] P={seat['pot']:.1f} "
                f"opp={seat['n_opp']}",
            )
    fig.suptitle(
        f"{args.table_size}-max 翻前无加注:各位置 Call 范围"
        f"(绿=+EV)  上排 current(只算已进池)/ 下排 full(全桌进池)",
        fontsize=11,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    out_path = Path(args.out) if args.out else (
        Path.home() / "Desktop" / "preflop_limp_ranges_6max.png"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"\n图片已保存: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
