"""Boltzmann 报告参数对齐测试 —— 按风格参数表、EV 公式、采样防护。"""

from __future__ import annotations

import math

import pytest

from src.ai.bots import BOT_PROFILES, BotFactory, BotStyle, BoltzmannBot
from src.engine.game import GameState
from src.engine.player import Player
from src.utils.constants import ActionType


def make_bot(style: BotStyle = BotStyle.BALANCED, seed: int = 42) -> BoltzmannBot:
    return BotFactory.create(style, seed=seed)


class TestPerStyleParameters:
    """六风格参数表已按报告落地且互不相同。"""

    def test_styles_have_distinct_response_params(self) -> None:
        params = {
            (p.F_max, p.lambda_fold, p.nu, p.q_delta)
            for s, p in BOT_PROFILES.items()
            if s not in (BotStyle.LLM,)
        }
        assert len(params) >= 5  # 六风格中至少 5 组互异(HOT/CHAOS q_delta 相同)

    def test_fold_ceiling_monotonic_with_temperature(self) -> None:
        """温度越高的风格 F_max 越低（越少指望对手弃牌）。"""
        order = [BotStyle.COLD, BotStyle.COOL, BotStyle.BALANCED,
                 BotStyle.WARM, BotStyle.HOT, BotStyle.CHAOS]
        f_values = [BOT_PROFILES[s].F_max for s in order]
        assert f_values == sorted(f_values, reverse=True)

    def test_q_delta_monotonic(self) -> None:
        order = [BotStyle.COLD, BotStyle.COOL, BotStyle.BALANCED,
                 BotStyle.WARM, BotStyle.HOT, BotStyle.CHAOS]
        d_values = [BOT_PROFILES[s].q_delta for s in order]
        assert d_values == sorted(d_values, reverse=True)


class TestEvBet:
    """_ev_bet 的关键性质。"""

    def test_no_opponents_returns_pot(self) -> None:
        """无对手时底池已属于自己（旧公式模型化了不存在的跟注）。"""
        bot = make_bot()
        assert bot._ev_bet(5.0, 10.0, 0.8, [], []) == 10.0

    def test_all_in_opponent_has_zero_fold_equity(self) -> None:
        """对手全下(F=0)时 all_fold=0，EV 完全来自被跟注分支。"""
        bot = make_bot()
        ev_allin_opp = bot._ev_bet(5.0, 10.0, 0.9, [0.0], [1.8])
        ev_foldable = bot._ev_bet(5.0, 10.0, 0.9, [0.68], [1.8])
        assert ev_allin_opp != ev_foldable

    def test_conditional_callers_exact_formula(self) -> None:
        """E[k|k≥1] = Σ(1-F_i)/(1-ΠF_i)：单对手时恒为 1。"""
        bot = make_bot()
        # 单对手: 被跟注时跟注人数必然是 1
        # 验证方式: 手工重算 EV 并与 _ev_bet 一致
        x, pot, w = 5.0, 10.0, 0.6
        fm, lam = 0.68, 1.8
        z = x / pot
        F = fm * (1.0 - math.exp(-lam * z))
        q_inf = max(0.05, w - bot.profile.q_delta)
        q = q_inf + (w - q_inf) * math.exp(-bot.profile.nu * z)
        expected = F * pot + (1 - F) * (q * (pot + 2 * x) - x)
        assert bot._ev_bet(x, pot, w, [fm], [lam]) == pytest.approx(expected)

    def test_nuts_prefers_larger_bet_than_marginal(self) -> None:
        """强牌的最优下注不小于边缘牌（报告 EV 曲线形状）。"""
        bot = make_bot()
        fm, lam = [0.68], [1.8]
        x_nuts, _ = bot._find_optimal_bet(10.0, 0.95, fm, lam, 1.0, 100.0)
        x_marginal, _ = bot._find_optimal_bet(10.0, 0.55, fm, lam, 1.0, 100.0)
        assert x_nuts >= x_marginal


class TestEvRaiseWithToCall:
    """面对下注加注时,EV 必须计入 to_call（Hero 补齐 + 对手匹配）。"""

    def test_manual_formula_with_to_call(self) -> None:
        """x_eff = x + c 代入后与手工公式逐项一致。"""
        bot = make_bot()
        x, pot, w, c = 5.0, 10.0, 0.6, 4.0
        fm, lam = 0.68, 1.8
        x_eff = x + c
        z = x_eff / pot
        F = fm * (1.0 - math.exp(-lam * z))
        q_inf = max(0.05, w - bot.profile.q_delta)
        q = q_inf + (w - q_inf) * math.exp(-bot.profile.nu * z)
        expected = F * pot + (1 - F) * (q * (pot + 2 * x_eff) - x_eff)
        assert bot._ev_bet(x, pot, w, [fm], [lam], to_call=c) == pytest.approx(expected)

    def test_to_call_penalizes_raise_when_behind(self) -> None:
        """落后方面对下注加注:E(V) 因补齐投入被压低(修正旧模型的系统性高估)。

        用全下对手(F_max=0)隔离出被跟注分支:q < 0.5 时,
        补齐 to_call 后的期望必然严格低于旧的无对峙模型。
        """
        bot = make_bot()
        args = (5.0, 10.0, 0.35, [0.0], [1.8])
        ev_pure_model = bot._ev_bet(*args)
        ev_facing = bot._ev_bet(*args, to_call=4.0)
        assert ev_facing < ev_pure_model

    def test_all_fold_branch_ignores_to_call(self) -> None:
        """未被跟注的加注不投入 x_eff（溢出返还）,EV 仍为底池。"""
        bot = make_bot()
        assert bot._ev_bet(5.0, 10.0, 0.9, [], [], to_call=4.0) == 10.0

    def test_zero_to_call_matches_pure_bet_model(self) -> None:
        """BET 路径(c=0)行为与旧模型完全一致(回归安全)。"""
        bot = make_bot()
        args = (5.0, 10.0, 0.6, [0.68], [1.8])
        assert bot._ev_bet(*args) == pytest.approx(bot._ev_bet(*args, to_call=0.0))


class TestFactoryTemperatureOverride:
    def test_custom_temperature_preserves_style_params(self) -> None:
        """自定义温度只覆盖温度,不得丢弃风格的对手响应参数。"""
        base = BOT_PROFILES[BotStyle.HOT]
        bot = BotFactory.create(BotStyle.HOT, temperature=0.11)
        assert bot.temperature == 0.11
        assert bot.profile.F_max == base.F_max
        assert bot.profile.lambda_fold == base.lambda_fold
        assert bot.profile.nu == base.nu
        assert bot.profile.q_delta == base.q_delta


class TestSamplingSafety:
    def test_zero_pot_no_crash(self) -> None:
        """pot=0 时温度下限 1BB 防除零。"""
        players = [Player(name=f"P{i}", chips=1000, seat=i) for i in range(2)]
        game = GameState(players, small_blind=5, big_blind=10, seed=3)
        game.start_new_hand()
        # 人为清空底池制造边界
        game.pot.reset()
        bot = make_bot(BotStyle.CHAOS)
        p = game.players[game.current_player_index]
        action = bot.decide(game, p)
        assert action.action_type in game.get_legal_actions(p)

    def test_decide_returns_legal_action(self) -> None:
        for style in (BotStyle.COLD, BotStyle.BALANCED, BotStyle.CHAOS):
            players = [Player(name=f"P{i}", chips=1000, seat=i) for i in range(3)]
            game = GameState(players, small_blind=5, big_blind=10, seed=9)
            game.start_new_hand()
            bot = make_bot(style)
            for _ in range(10):
                if game.phase.value >= 5:
                    break
                p = game.players[game.current_player_index]
                action = bot.decide(game, p)
                assert action.action_type in game.get_legal_actions(p)
                game.apply_action(action)
