"""扑克数学工具 —— 底池赔率等基础公式的唯一实现。"""

from __future__ import annotations

import math


def pot_odds(call_amount: float, pot_total: float) -> float:
    """跟注所需的最低胜率（0.0–1.0）。

    Args:
        call_amount: 需要跟注的额度。
        pot_total: 当前底池总额（不含本次跟注）。

    Returns:
        call / (pot + call)；无需跟注时为 0。
    """
    if call_amount <= 0 or pot_total + call_amount <= 0:
        return 0.0
    return call_amount / (pot_total + call_amount)


def mc_ci95(p: float, n: int) -> float:
    """蒙特卡洛比例估计的 95% 置信半径（百分点）。

    Args:
        p: 估计比例（0.0–1.0）。
        n: 模拟次数。

    Returns:
        1.96 × SE × 100；n<=0 时为 0。
    """
    if n <= 0:
        return 0.0
    se = math.sqrt(max(p * (1.0 - p), 0.0) / n)
    return round(1.96 * se * 100.0, 1)
