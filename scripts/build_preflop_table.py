"""离线生成高精度翻前胜率表 —— 169 起手牌 × vs 1..8 对手。

用法:
    python scripts/build_preflop_table.py

- equity share 平局约定(与 BattleAnalyzer 一致)
- n<=2 对手 100k 次/格, n>=3 对手 50k 次/格 (SE < 0.25pp)
- 固定种子(zlib.crc32), 多进程并行
- 输出 src/ai/preflop_equity.json: {"meta": ..., "table": {"h,l,s": [w1..w8]}}
"""

from __future__ import annotations

import json
import multiprocessing as mp
import os
import random
import sys
import time
import zlib
from typing import Dict, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from treys import Card as TreysCard
from treys import Evaluator as TreysEvaluator

MAX_OPPONENTS = 8
SIMS_LOW_N = 100_000   # n<=2
SIMS_HIGH_N = 50_000   # n>=3

_RANK_CHARS = "23456789TJQKA"  # 值 2..14
_OUT_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "src", "ai", "preflop_equity.json",
)


def _canonical_hands() -> List[Tuple[int, int, bool]]:
    """169 种 canonical 起手牌 (high, low, suited)。"""
    hands: List[Tuple[int, int, bool]] = []
    for hi in range(2, 15):
        for lo in range(2, hi + 1):
            hands.append((hi, lo, False))
            if hi != lo:
                hands.append((hi, lo, True))
    return hands


def _hand_equities(key: Tuple[int, int, bool]) -> Tuple[str, List[float]]:
    """计算一种起手牌 vs 1..MAX_OPPONENTS 对手的 equity share(%)。"""
    high, low, suited = key
    evaluator = TreysEvaluator()

    hi_char = _RANK_CHARS[high - 2]
    lo_char = _RANK_CHARS[low - 2]
    if suited:
        hero_strs = [f"{hi_char}s", f"{lo_char}s"]
    else:
        hero_strs = [f"{hi_char}s", f"{lo_char}h"]
    hero = [TreysCard.new(s) for s in hero_strs]

    full_deck = [
        TreysCard.new(f"{r}{s}")
        for r in _RANK_CHARS
        for s in "shdc"
    ]
    pool = [c for c in full_deck if c not in hero]

    evaluate = evaluator.evaluate
    equities: List[float] = []

    for n_opp in range(1, MAX_OPPONENTS + 1):
        num_sims = SIMS_LOW_N if n_opp <= 2 else SIMS_HIGH_N
        rng = random.Random(zlib.crc32(f"{key}|{n_opp}".encode()))
        draw_count = 2 * n_opp + 5

        equity_sum = 0.0
        for _ in range(num_sims):
            drawn = rng.sample(pool, draw_count)
            board = drawn[2 * n_opp:]
            hero_score = evaluate(hero, board)
            better = 0
            tied = 0
            for i in range(n_opp):
                opp_score = evaluate(drawn[2 * i:2 * i + 2], board)
                if opp_score < hero_score:
                    better += 1
                    break  # 已确定 equity=0, 提前退出
                if opp_score == hero_score:
                    tied += 1
            if better == 0:
                equity_sum += 1.0 / (1.0 + tied)

        equities.append(round(equity_sum / num_sims * 100.0, 2))

    return f"{high},{low},{'1' if suited else '0'}", equities


def main() -> None:
    hands = _canonical_hands()
    n_workers = max(1, (os.cpu_count() or 4) - 2)
    print(f"生成翻前胜率表: {len(hands)} 手牌 × vs 1..{MAX_OPPONENTS} 对手, "
          f"{n_workers} 进程")
    t0 = time.perf_counter()

    with mp.Pool(n_workers) as pool_proc:
        results = pool_proc.map(_hand_equities, hands)

    table: Dict[str, List[float]] = dict(results)
    payload = {
        "meta": {
            "version": 2,
            "convention": "equity_share",
            "opponents": list(range(1, MAX_OPPONENTS + 1)),
            "sims": {"n<=2": SIMS_LOW_N, "n>=3": SIMS_HIGH_N},
        },
        "table": table,
    }
    with open(_OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)

    elapsed = time.perf_counter() - t0
    print(f"完成: {len(table)} 手牌, {elapsed:.0f}s -> {_OUT_FILE}")

    # 质检: 同花 > 非同花, AA 最强
    bad = 0
    for hi in range(2, 15):
        for lo in range(2, hi):
            s_key = f"{hi},{lo},1"
            o_key = f"{hi},{lo},0"
            if table[s_key][0] <= table[o_key][0]:
                print(f"  倒挂: {s_key}={table[s_key][0]} <= {o_key}={table[o_key][0]}")
                bad += 1
    print(f"同花>非同花检查: {'全部通过' if bad == 0 else f'{bad} 处倒挂'}")


if __name__ == "__main__":
    main()
