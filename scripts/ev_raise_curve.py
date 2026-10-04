"""单街 EV-Raise 曲线 —— 对手按底池赔率序贯决策的加注期望模型。

模型(用户提案 + 两处实现澄清):
    信息集 I = (H_self, H_public), p = P(Win | I)(对手手牌均匀随机)。
    底池 P,跟注成本 C,额外加注 R(英雄本次总投入 C+R)。
    英雄加注后按给定顺序逐个处理对手 i(k = 已跟注人数):
        - 对手 i 追加成本 d_i = max(0, C + R - 已投入_i)
        - 跟注后底池 pot_after = pot_before + d_i
        - 对手 i 跟注当且仅当 p_i * pot_after > d_i
        - p_i 为对手仅知道自己手牌与公共牌时、其余手牌均匀随机
          的摊牌权益(不偷看英雄底牌)
    英雄对每个抽样 ω 的 EV:
        EV(ω) = equity(ω, 跟注者集合) * pot_final - (C + R)
    其中 equity 为摊牌权益(平局按人头均分);集合为空时约定 equity=1,
    公式自动退化为 pot_final-(C+R) = P(未匹配加注返还)。

    默认 --opp-invested 全 0、--hero-invested 0,即原文模型(假设所有
    对手都是没投过钱的冷跟注者);给定已有投入后,原下注者只需补 R,
    修正原文对"原下注者也要付 C+R"的高估。

限制:
    - 翻前 runout 组合爆炸,本工具要求公共牌 >= 3 张;
    - 对手仅 Fold/Call,无再加注、无后续街、无筹码/全下限制;
    - p_i 只按手牌强弱估计,未利用英雄加注所暴露的范围信息;
    - p_i 假设其余 n_opp 个未知手牌都会留到摊牌,未随实际跟注人数修正。

用法:
    python scripts/ev_raise_curve.py --hero "Ah Kh" --board "Qh 8h 2c" \
        --pot 100 --to-call 30 --opponents 2 --samples 300
"""

from __future__ import annotations

import argparse
import itertools
import random
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Sequence, Tuple

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
from treys import Evaluator  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.engine.card import Card, Cards  # noqa: E402
from src.utils._card_helpers import ALL_TREYS, treys_ids, treys_pool  # noqa: E402

_EVALUATOR = Evaluator()


@dataclass
class Sample:
    """一个对手手牌抽样下预计算的决策输入。

    Attributes:
        p_opp: 每个对手仅基于自己手牌与公共牌的摊牌权益
            (对手信息集,其余手牌均匀随机)。
        equity: equity[mask] = 英雄对 mask 位对手集合的摊牌权益;
            equity[0] 固定为 1.0(无人跟注时英雄直接赢下底池)。
    """

    p_opp: List[float]
    equity: List[float]


def parse_cards(text: str) -> Cards:
    """解析牌串,支持 "Ah Kh" 或 "AhKh" 两种写法。"""
    tokens = text.replace(",", " ").split()
    if len(tokens) == 1 and len(tokens[0]) % 2 == 0:
        flat = tokens[0]
        tokens = [flat[i:i + 2] for i in range(0, len(flat), 2)]
    return [Card.from_str(t) for t in tokens]


def opponent_field_equity(
    opp_hand: Sequence[int],
    board_ids: Sequence[int],
    field_size: int,
    needed: int,
    rng: random.Random,
    sims: int,
) -> float:
    """对手信息集下的摊牌权益:仅知自己手牌与公共牌。

    其余 field_size 个手牌(英雄 + 其他对手)按均匀随机抽样,
    合并 runout 一次性模拟,平局按人头均分。

    Args:
        opp_hand: 对手的两张牌(Treys 整数)。
        board_ids: 公共牌(Treys 整数)。
        field_size: 对手不知道的其余手牌数量(n_opp)。
        needed: 还需发出的公共牌张数。
        rng: 随机数生成器。
        sims: 模拟次数。

    Returns:
        对手的期望摊牌权益(0-1)。
    """
    excluded = set(opp_hand) | set(board_ids)
    deck = [t for t in ALL_TREYS if t not in excluded]
    share_sum = 0.0
    for _ in range(sims):
        drawn = rng.sample(deck, 2 * field_size + needed)
        full_board = list(board_ids) + drawn[2 * field_size:]
        opp_rank = _EVALUATOR.evaluate(list(opp_hand), full_board)
        best = 10 ** 9
        tied = 0
        for j in range(field_size):
            rank = _EVALUATOR.evaluate(
                drawn[2 * j:2 * j + 2], full_board
            )
            if rank < best:
                best = rank
                tied = 1
            elif rank == best:
                tied += 1
        if opp_rank < best:
            share_sum += 1.0
        elif opp_rank == best:
            share_sum += 1.0 / (tied + 1)
    return share_sum / sims


def build_samples(
    hero: Cards, board: Cards, n_opp: int, samples: int, seed: int,
    p_sims: int = 400,
) -> List[Sample]:
    """对对手手牌抽样,并对每个抽样完全枚举剩余公共牌。

    对每个抽样一次枚举 runout 得到英雄对任意跟注者子集的摊牌权益;
    每个对手的 p_i 按对手信息集(只知道自己手牌+公共牌)用蒙特卡洛
    对随机未知手牌估计,并按手牌缓存。

    Args:
        hero: 英雄底牌。
        board: 公共牌(3-5 张)。
        n_opp: 对手数量。
        samples: 对手手牌抽样数。
        seed: 随机种子。
        p_sims: 对手权益的蒙特卡洛次数。
    """
    hero_ids = treys_ids(hero)
    board_ids = treys_ids(board)
    pool = treys_pool(list(hero) + list(board))
    needed = 5 - len(board_ids)
    n_masks = 1 << n_opp
    rng = random.Random(seed)
    p_rng = random.Random(seed ^ 0x9E3779B9)
    p_cache: dict = {}

    result: List[Sample] = []
    for _ in range(samples):
        drawn = rng.sample(pool, 2 * n_opp)
        drawn_set = set(drawn)
        opp_hands = [drawn[2 * i:2 * i + 2] for i in range(n_opp)]
        deck = [c for c in pool if c not in drawn_set]

        shares = [0.0] * n_masks
        total = 0
        for combo in itertools.combinations(deck, needed):
            full_board = board_ids + list(combo)
            hero_rank = _EVALUATOR.evaluate(hero_ids, full_board)
            ranks = [_EVALUATOR.evaluate(h, full_board) for h in opp_hands]
            total += 1
            for mask in range(1, n_masks):
                best = min(
                    ranks[i] for i in range(n_opp) if mask & (1 << i)
                )
                if hero_rank < best:
                    shares[mask] += 1.0
                elif hero_rank == best:
                    tied = sum(
                        1 for i in range(n_opp)
                        if mask & (1 << i) and ranks[i] == best
                    )
                    shares[mask] += 1.0 / (tied + 1)

        equity = [1.0] + [
            shares[m] / total for m in range(1, n_masks)
        ]
        p_opp: List[float] = []
        for hand in opp_hands:
            key = tuple(sorted(hand))
            if key not in p_cache:
                p_cache[key] = opponent_field_equity(
                    hand, board_ids, n_opp, needed, p_rng, p_sims,
                )
            p_opp.append(p_cache[key])
        result.append(Sample(p_opp=p_opp, equity=equity))
    return result


def ev_raise(
    samples: Sequence[Sample],
    pot: float,
    to_call: float,
    hero_invested: float,
    opp_invested: Sequence[float],
    r: float,
) -> Tuple[float, float]:
    """计算给定加注增量 R 的 EV 与全弃牌概率。

    Args:
        samples: 预计算的对手手牌抽样。
        pot: 当前底池(含本街所有已投入筹码)。
        to_call: 英雄跟注成本 C。
        hero_invested: 英雄本街已投入(默认 0,则当前下注额 = C)。
        opp_invested: 各对手本街已投入。
        r: 额外加注增量 R。

    Returns:
        (EV(R), P(所有对手弃牌))。
    """
    base_bet = to_call + hero_invested
    hero_add = to_call + r
    ev_sum = 0.0
    fold_all = 0
    for sample in samples:
        pot_now = pot + hero_add
        mask = 0
        for i, p_i in enumerate(sample.p_opp):
            d = max(0.0, base_bet + r - opp_invested[i])
            if p_i * (pot_now + d) > d:
                mask |= 1 << i
                pot_now += d
        ev_sum += sample.equity[mask] * pot_now - hero_add
        if mask == 0:
            fold_all += 1
    n = len(samples)
    return ev_sum / n, fold_all / n


def ev_call(samples: Sequence[Sample], pot: float, to_call: float) -> float:
    """跟注 EV = p * (P + C) - C,p 为对全部对手的摊牌权益。"""
    p_all = sum(s.equity[-1] for s in samples) / len(samples)
    return p_all * (pot + to_call) - to_call


def plot_curve(
    rs: Sequence[float],
    evs: Sequence[float],
    call_ev: float,
    pot: float,
    title: str,
    out_path: Path,
) -> int:
    """绘制 EV-R 曲线并保存,返回最优 R 的下标。"""
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial"]
    plt.rcParams["axes.unicode_minus"] = False

    fig, ax = plt.subplots(figsize=(9.5, 5.5))
    ax.plot(rs, evs, "-o", ms=3.5, color="#1f77b4", label="EV(Raise R)")
    ax.axhline(call_ev, color="#d62728", ls="--", label=f"EV(Call)={call_ev:.1f}")
    ax.axhline(0.0, color="#555555", ls=":", label="EV(Fold)=0")

    best = max(range(len(evs)), key=lambda i: evs[i])
    ax.scatter([rs[best]], [evs[best]], color="#ff7f0e", zorder=5)
    ha = "right" if best > len(rs) * 0.75 else "left"
    dx = -10 if ha == "right" else 10
    ax.annotate(
        f"R*={rs[best]:.1f}\nEV*={evs[best]:.1f}",
        (rs[best], evs[best]),
        textcoords="offset points", xytext=(dx, -42), ha=ha,
        color="#ff7f0e",
    )

    ax.set_xlabel("加注增量 R(筹码)")
    ax.set_ylabel("期望收益 EV(筹码)")
    ax.set_title(title)
    ax.grid(alpha=0.3)
    ax.legend(loc="best")

    if pot > 0:
        sec = ax.secondary_xaxis(
            "top", functions=(lambda x: x / pot, lambda z: z * pot)
        )
        sec.set_xlabel("R / 底池")

    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return best


def main() -> int:
    parser = argparse.ArgumentParser(
        description="单街 EV-Raise 曲线(对手按底池赔率序贯跟注)"
    )
    parser.add_argument("--hero", default="Ah Kh", help="英雄底牌,如 'Ah Kh'")
    parser.add_argument("--board", default="Qh 8h 2c", help="公共牌(3-5 张)")
    parser.add_argument("--pot", type=float, default=100.0, help="当前底池")
    parser.add_argument("--to-call", type=float, default=30.0, help="跟注成本 C")
    parser.add_argument("--opponents", type=int, default=2, help="对手数量(1-4)")
    parser.add_argument("--samples", type=int, default=300, help="手牌抽样数")
    parser.add_argument(
        "--p-sims", type=int, default=400,
        help="对手信息集权益的蒙特卡洛次数",
    )
    parser.add_argument("--r-max", type=float, default=None, help="R 上限(默认 2P)")
    parser.add_argument("--r-points", type=int, default=25, help="R 采样点数")
    parser.add_argument("--seed", type=int, default=20261003)
    parser.add_argument("--hero-invested", type=float, default=0.0)
    parser.add_argument(
        "--opp-invested", default="",
        help="各对手本街已投入,逗号分隔;留空表示全 0(原文模型)",
    )
    parser.add_argument("--out", default="", help="输出 PNG 路径")
    args = parser.parse_args()

    hero = parse_cards(args.hero)
    board = parse_cards(args.board)
    if len(hero) != 2:
        parser.error("英雄底牌必须是 2 张")
    if not 3 <= len(board) <= 5:
        parser.error("公共牌必须为 3-5 张(翻前枚举不可行)")
    seen = {c.short_str for c in hero + board}
    if len(seen) != len(hero) + len(board):
        parser.error("存在重复的牌")
    if not 1 <= args.opponents <= 4:
        parser.error("对手数量需在 1-4 之间")
    if args.pot < 0 or args.to_call < 0:
        parser.error("底池与跟注成本不能为负")
    if args.r_points < 2:
        parser.error("R 采样点数至少为 2")

    if args.opp_invested.strip():
        opp_invested = [float(x) for x in args.opp_invested.split(",")]
        if len(opp_invested) != args.opponents:
            parser.error(
                f"--opp-invested 需要 {args.opponents} 个值,"
                f"收到 {len(opp_invested)}"
            )
    else:
        opp_invested = [0.0] * args.opponents

    samples = build_samples(
        hero, board, args.opponents, args.samples, args.seed, args.p_sims,
    )
    r_max = args.r_max if args.r_max is not None else 2.0 * args.pot
    if r_max <= 0:
        parser.error("R 上限必须大于 0")
    rs = [r_max * i / (args.r_points - 1) for i in range(args.r_points)]

    print(
        f"场景: {' '.join(c.short_str for c in hero)} | "
        f"{' '.join(c.short_str for c in board)} | "
        f"P={args.pot:.1f} C={args.to_call:.1f} "
        f"对手={args.opponents} 抽样={args.samples}"
    )
    evs: List[float] = []
    folds: List[float] = []
    for r in rs:
        ev, fold_p = ev_raise(
            samples, args.pot, args.to_call,
            args.hero_invested, opp_invested, r,
        )
        evs.append(ev)
        folds.append(fold_p)

    call_ev = ev_call(samples, args.pot, args.to_call)
    p_all = sum(s.equity[-1] for s in samples) / len(samples)
    print(f"英雄对全部对手权益 p={p_all:.4f}")
    print(f"EV(Call)={call_ev:.2f}  EV(Fold)=0.00")
    print(f"{'R':>8} {'EV(R)':>10} {'P(all fold)':>12}")
    for r, ev, f in zip(rs, evs, folds):
        print(f"{r:8.1f} {ev:10.2f} {f:12.3f}")

    title = (
        f"EV-加注曲线 | {' '.join(c.short_str for c in hero)} on "
        f"{' '.join(c.short_str for c in board)} | "
        f"P={args.pot:.0f} C={args.to_call:.0f} "
        f"对手={args.opponents}"
    )
    if args.out:
        out_path = Path(args.out)
    else:
        out_path = Path.home() / "Desktop" / (
            "ev_raise_" + "".join(c.short_str for c in hero)
            + "_" + "".join(c.short_str for c in board) + ".png"
        )
    best = plot_curve(rs, evs, call_ev, args.pot, title, out_path)
    print(f"最优: R*={rs[best]:.1f}, EV*={evs[best]:.2f}")
    print(f"图片已保存: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
