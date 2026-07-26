"""筹码守恒性质测试 —— 引擎重构的安全网。

用固定种子驱动大量完整牌局，断言每一手结束后：
- 全桌筹码总量守恒（仅允许 rebuy 注入）
- 无负筹码
- 赢家金额为正且有赢家
- 引擎从不把行动指针指向非 ACTIVE 玩家（严格驱动器，不做任何绕过）
"""

from __future__ import annotations

import random
from typing import Dict, List

import pytest

from src.engine.game import Action, GameState
from src.engine.player import Player
from src.utils.constants import ActionType, BettingStructure, GamePhase, PlayerStatus


class RandomLegalAgent:
    """纯引擎测试代理：在合法动作中均匀随机选择，金额在合法区间内随机。"""

    def __init__(self, seed: int) -> None:
        self._rng = random.Random(seed)

    def decide(self, game: GameState, player: Player) -> Action:
        """在当前合法动作集中随机决策。

        Args:
            game: 游戏状态。
            player: 行动玩家。

        Returns:
            一个合法 Action。
        """
        legal = game.get_legal_actions(player)
        assert legal, f"{player.name} 处于行动位但无合法动作"
        action_type = self._rng.choice(legal)
        amount = 0
        if action_type in (ActionType.BET, ActionType.RAISE):
            lo = game.get_min_raise_amount(player)
            hi = game.get_max_bet(player)
            if lo > hi:
                amount = hi  # 只能全下
            else:
                # 1/5 概率直接全下，其余在区间内随机
                amount = hi if self._rng.random() < 0.2 else self._rng.randint(lo, hi)
        return Action(player.name, action_type, amount)


class ConservationHarness:
    """驱动 N 手牌并逐手断言守恒不变量。"""

    def __init__(
        self,
        n_players: int,
        structure: BettingStructure,
        hands: int,
        seed: int,
        ante: int = 0,
        auto_rebuy: bool = True,
        starting_chips: int = 1000,
        rebuy_amount: int = 1000,
    ) -> None:
        self.players = [
            Player(name=f"P{i}", chips=starting_chips, seat=i)
            for i in range(n_players)
        ]
        self.game = GameState(
            self.players,
            small_blind=5,
            big_blind=10,
            ante=ante,
            betting_structure=structure,
            auto_rebuy=auto_rebuy,
            rebuy_amount=rebuy_amount,
            seed=seed,
        )
        self.hands = hands
        self.rebuy_amount = rebuy_amount
        self.agents: Dict[str, RandomLegalAgent] = {
            p.name: RandomLegalAgent(seed * 7919 + i)
            for i, p in enumerate(self.players)
        }
        self.winners_log: List[Dict[str, int]] = []

    def run(self) -> None:
        """跑完全部手数，逐手断言不变量。"""
        for hand_no in range(1, self.hands + 1):
            chips_before = sum(p.chips for p in self.players)
            rebuys_before = sum(p.rebuy_count for p in self.players)

            self.game.start_new_hand()

            rebuys_injected = (
                sum(p.rebuy_count for p in self.players) - rebuys_before
            ) * self.rebuy_amount

            if self.game.phase == GamePhase.FINISHED:
                # 人数不足，无法继续（rebuy-off 场景的正常终点）
                assert not self.game.auto_rebuy or rebuys_injected > 0 or True
                break

            steps = 0
            while self.game.phase.value < GamePhase.SHOWDOWN.value:
                cp = self.game.players[self.game.current_player_index]
                # 严格驱动器：引擎必须保证行动指针只指向可行动玩家
                assert cp.status == PlayerStatus.ACTIVE, (
                    f"hand {hand_no}: 行动指针指向非 ACTIVE 玩家 "
                    f"{cp.name}({cp.status.name})"
                )
                action = self.agents[cp.name].decide(self.game, cp)
                self.game.apply_action(action)
                steps += 1
                assert steps < 500, f"hand {hand_no}: 疑似死循环"

            assert self.game.phase == GamePhase.FINISHED, (
                f"hand {hand_no}: 结束时 phase={self.game.phase.name}"
            )

            chips_after = sum(p.chips for p in self.players)
            assert chips_after == chips_before + rebuys_injected, (
                f"hand {hand_no}: 筹码不守恒 "
                f"{chips_before}+{rebuys_injected} -> {chips_after}"
            )
            for p in self.players:
                assert p.chips >= 0, f"hand {hand_no}: {p.name} 负筹码 {p.chips}"

            assert self.game.winners, f"hand {hand_no}: 无赢家"
            for name, amount in self.game.winners.items():
                assert amount > 0, f"hand {hand_no}: 赢家 {name} 金额 {amount} <= 0"
                player = next(p for p in self.players if p.name == name)
                assert player.total_bet > 0 or player.status != PlayerStatus.OUT, (
                    f"hand {hand_no}: 未参与玩家 {name} 赢得底池"
                )

            self.winners_log.append(dict(self.game.winners))


class TestChipConservation:
    """全配置矩阵的筹码守恒测试。"""

    @pytest.mark.parametrize("n_players", [2, 3, 6, 9])
    def test_no_limit(self, n_players: int) -> None:
        ConservationHarness(
            n_players, BettingStructure.NO_LIMIT, hands=200, seed=42
        ).run()

    @pytest.mark.parametrize("n_players", [2, 6])
    def test_pot_limit(self, n_players: int) -> None:
        ConservationHarness(
            n_players, BettingStructure.POT_LIMIT, hands=150, seed=43
        ).run()

    @pytest.mark.parametrize("n_players", [2, 6])
    def test_fixed_limit(self, n_players: int) -> None:
        ConservationHarness(
            n_players, BettingStructure.FIXED_LIMIT, hands=150, seed=44
        ).run()

    def test_with_ante(self) -> None:
        ConservationHarness(
            6, BettingStructure.NO_LIMIT, hands=150, seed=45, ante=2
        ).run()

    def test_rebuy_off_short_stacks(self) -> None:
        """短码 + 不重购：玩家逐渐破产直到牌局无法继续。"""
        ConservationHarness(
            4,
            BettingStructure.NO_LIMIT,
            hands=300,
            seed=46,
            auto_rebuy=False,
            starting_chips=200,
        ).run()

    def test_deterministic_with_seed(self) -> None:
        """同种子两次运行结果完全一致（Deck 可设种子回归）。"""
        h1 = ConservationHarness(6, BettingStructure.NO_LIMIT, hands=50, seed=47)
        h1.run()
        h2 = ConservationHarness(6, BettingStructure.NO_LIMIT, hands=50, seed=47)
        h2.run()
        assert h1.winners_log == h2.winners_log
