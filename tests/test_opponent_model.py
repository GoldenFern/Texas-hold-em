"""OpponentModel 收缩混合估计的单元测试。"""

from __future__ import annotations

import pytest

from src.ai.opponent_model import OpponentModel
from src.analysis.reporter import HandReporter, PlayerStats


def make_model(stats: PlayerStats | None, prior_hands: int = 30) -> OpponentModel:
    reporter = HandReporter()
    if stats is not None:
        reporter.player_stats[stats.name] = stats
    return OpponentModel(reporter, prior_hands=prior_hands)


class TestFoldMax:
    def test_no_data_returns_base(self) -> None:
        model = make_model(None)
        assert model.fold_max("unknown", 0.68) == 0.68

    def test_zero_hands_returns_base(self) -> None:
        model = make_model(PlayerStats(name="X"))
        assert model.fold_max("X", 0.68) == 0.68

    def test_shrinkage_blends_toward_observation(self) -> None:
        """手数越多越信观测：紧对手(低 VPIP)的 fold_max 高于基准。"""
        tight = PlayerStats(name="T", hands_played=90, vpip_count=9)  # VPIP=0.1
        model = make_model(tight, prior_hands=30)
        # blended = (90*0.9 + 30*0.68) / 120 = 0.845
        assert model.fold_max("T", 0.68) == pytest.approx(0.845)

    def test_few_hands_stays_near_base(self) -> None:
        loose = PlayerStats(name="L", hands_played=3, vpip_count=3)  # VPIP=1.0
        model = make_model(loose, prior_hands=30)
        # blended = (3*0.0 + 30*0.68) / 33 ≈ 0.618 — 数据少, 基准主导
        assert model.fold_max("L", 0.68) == pytest.approx(0.618, abs=0.01)

    def test_clipped_to_bounds(self) -> None:
        nit = PlayerStats(name="N", hands_played=10000, vpip_count=0)
        model = make_model(nit)
        assert model.fold_max("N", 0.68) <= 0.95

        station = PlayerStats(name="S", hands_played=10000, vpip_count=10000)
        model2 = make_model(station)
        assert model2.fold_max("S", 0.68) >= 0.10


class TestLam:
    def test_no_data_returns_base(self) -> None:
        model = make_model(None)
        assert model.lam("unknown", 1.8) == 1.8

    def test_aggressive_opponent_lowers_lambda(self) -> None:
        """高 AF 对手更粘, λ 变小(fold equity 饱和更慢)。"""
        aggro = PlayerStats(
            name="A", hands_played=50, raise_count=30, call_count=10,
        )  # AF = 3.0
        model = make_model(aggro)
        # 1.8 * (1.2 - 0.2*3) = 1.08
        assert model.lam("A", 1.8) == pytest.approx(1.08)

    def test_passive_opponent_raises_lambda(self) -> None:
        passive = PlayerStats(
            name="P", hands_played=50, raise_count=0, call_count=40,
        )  # AF = 0
        model = make_model(passive)
        # 1.8 * 1.2 = 2.16
        assert model.lam("P", 1.8) == pytest.approx(2.16)

    def test_clipped(self) -> None:
        passive = PlayerStats(
            name="P", hands_played=50, raise_count=0, call_count=40,
        )
        model = make_model(passive)
        assert 0.5 <= model.lam("P", 4.5) <= 5.0
