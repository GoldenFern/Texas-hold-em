"""对手建模 —— 将观测统计（VPIP/AF）收缩混合进 Boltzmann 响应参数。

Boltzmann 报告的对手响应模型 F(x) = F_max·(1−e^(−λz)) 中,
F_max 与 λ 原为全局常数。本模块用逐对手观测统计修正它们:

- fold_max: 观测弃牌倾向 (1−VPIP) 与风格基准按手数收缩混合
  (贝叶斯 shrinkage, 伪计数 prior_hands),数据越多越信观测。
- lam: 侵略因子 AF 越高的对手越"粘"(fold equity 随下注尺度
  饱和得越慢),λ 按 AF 线性缩放。
"""

from __future__ import annotations

from typing import Optional

from src.analysis.reporter import HandReporter


def _clip(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


class OpponentModel:
    """基于 HandReporter 统计的逐对手响应参数估计器。

    Attributes:
        reporter: 共享的牌局统计报告器。
        prior_hands: 收缩混合的伪计数（观测不足 prior_hands 手时
            以风格基准为主）。
    """

    def __init__(self, reporter: HandReporter, prior_hands: int = 30) -> None:
        self.reporter = reporter
        self.prior_hands = prior_hands

    def fold_max(self, opponent_name: str, base: float) -> float:
        """估计对手的弃牌率上限 F_max。

        Args:
            opponent_name: 对手名称。
            base: 决策方风格的 F_max 基准值。

        Returns:
            收缩混合后的 F_max, 钳位于 [0.10, 0.95]。
        """
        stats = self.reporter.get_stats(opponent_name)
        if stats is None or stats.hands_played == 0:
            return base

        n = stats.hands_played
        n0 = self.prior_hands
        observed_fold_tendency = 1.0 - stats.vpip
        blended = (n * observed_fold_tendency + n0 * base) / (n + n0)
        return _clip(blended, 0.10, 0.95)

    def lam(self, opponent_name: str, base: float) -> float:
        """估计对手的 fold-equity 饱和速率 λ。

        Args:
            opponent_name: 对手名称。
            base: 决策方风格的 λ 基准值。

        Returns:
            按 AF 缩放后的 λ, 钳位于 [0.5, 5.0]。
        """
        stats = self.reporter.get_stats(opponent_name)
        if stats is None or stats.hands_played == 0:
            return base

        af = min(stats.aggression_factor, 3.0)
        # AF=1 时不变; AF 越高 λ 越小(对手越难被下注赶走)
        scaled = base * (1.2 - 0.2 * af)
        return _clip(scaled, 0.5, 5.0)
