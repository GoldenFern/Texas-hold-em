"""底池赔率与期望值计算器。"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

from src.engine.card import Cards
from src.engine.game import GameState
from src.engine.player import Player
from src.analysis.equity import EquityCalculator


class OddsCalculator:
    """底池赔率与决策辅助计算器。

    提供：底池赔率、隐含赔率、期望值分析。
    """

    def __init__(self, equity_calculator: Optional[EquityCalculator] = None) -> None:
        self.equity = equity_calculator or EquityCalculator()

    def pot_odds(self, game: GameState, player: Player) -> Dict[str, float]:
        """计算当前跟注的底池赔率。

        Returns:
            {
                "to_call": 需要跟注的金额,
                "pot_total": 底池总额,
                "pot_odds_ratio": 底池赔率比（如 2.5:1）,
                "required_equity": 跟注所需最低胜率,
            }
        """
        to_call = game.current_bet - player.current_bet
        pot_after_call = game.pot.total + to_call

        if to_call <= 0:
            return {
                "to_call": 0,
                "pot_total": game.pot.total,
                "pot_odds_ratio": 0,
                "required_equity": 0.0,
            }

        ratio = pot_after_call / to_call
        required_equity = to_call / pot_after_call

        return {
            "to_call": to_call,
            "pot_total": game.pot.total,
            "pot_odds_ratio": round(ratio, 2),
            "required_equity": round(required_equity, 4),
        }

    def implied_odds(
        self,
        game: GameState,
        player: Player,
        estimated_future_bets: int = 0,
    ) -> Dict[str, float]:
        """计算隐含赔率（考虑未来可能的下注）。

        Args:
            game: 当前游戏状态。
            player: 当前玩家。
            estimated_future_bets: 估计未来可获取的额外筹码。
        """
        to_call = game.current_bet - player.current_bet
        total_potential = game.pot.total + to_call + estimated_future_bets

        if to_call <= 0:
            return {"implied_odds_ratio": 0, "required_equity": 0.0}

        return {
            "to_call": to_call,
            "pot_now": game.pot.total,
            "estimated_future": estimated_future_bets,
            "implied_odds_ratio": round(total_potential / to_call, 2),
            "required_equity": round(to_call / total_potential, 4),
        }

    def expected_value(
        self,
        game: GameState,
        player: Player,
        opponent_count: int,
    ) -> Dict[str, float]:
        """估算当前决策的期望值。

        简化模型：假设跟注后以当前胜率进行摊牌。
        """
        to_call = game.current_bet - player.current_bet
        if to_call <= 0:
            win_amount = game.pot.total * 0.01
            return {
                "action": "check/free",
                "ev": win_amount,
                "pot_share": win_amount,
            }

        # 估算胜率（简化）
        all_cards = player.hole_cards + game.community_cards
        if len(all_cards) >= 5:
            from src.engine.hand import HandEvaluator
            result = HandEvaluator.evaluate(all_cards)
            hand_rank = result.hand_rank.value
            est_equity = hand_rank / 9.0 / (opponent_count + 1)
        else:
            from src.ai.strategy import preflop_hand_strength
            strength = preflop_hand_strength(player.hole_cards)
            est_equity = (strength / 100.0) / (opponent_count + 1)

        ev_win = est_equity * game.pot.total
        ev_lose = (1 - est_equity) * to_call
        ev = ev_win - ev_lose

        return {
            "action": "call",
            "estimated_equity": round(est_equity, 4),
            "ev_call": round(ev, 2),
            "pot_total": game.pot.total,
            "to_call": to_call,
        }
