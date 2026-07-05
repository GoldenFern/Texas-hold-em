"""AI Boltzmann-EV Bot 决策测试。"""

import pytest

from src.engine.card import Card
from src.engine.game import Action, ActionType, GameState
from src.engine.player import Player
from src.ai.bots import BoltzmannBot, BotFactory, BotProfile, BotStyle
from src.utils.constants import GamePhase


def make_game_with_bot(bot_name: str, seat: int = 0, num: int = 3) -> GameState:
    names = []
    for i in range(num):
        names.append(bot_name if i == seat else f"Opponent_{i}")
    return GameState([Player(name=n, chips=1000, seat=i) for i, n in enumerate(names)])


class TestBotCreation:
    def test_factory_creates_all_styles(self) -> None:
        for style in (BotStyle.NIT, BotStyle.TAG, BotStyle.SHARK,
                       BotStyle.LAG, BotStyle.CALLING_STATION, BotStyle.MANIAC):
            bot = BotFactory.create(style, seed=42)
            assert bot.style == style
            assert isinstance(bot, BoltzmannBot)

    def test_factory_unknown_style_raises(self) -> None:
        with pytest.raises(Exception):
            BotFactory.create("UNKNOWN")  # type: ignore[arg-type]

    def test_create_all_styles(self) -> None:
        bots = BotFactory.create_all_styles()
        assert len(bots) == 6

    def test_bot_has_unique_name(self) -> None:
        bots = BotFactory.create_all_styles()
        names = {b.name for b in bots}
        assert len(names) == 6

    def test_custom_temperature(self) -> None:
        bot = BotFactory.create(BotStyle.SHARK, temperature=3.5, seed=42)
        assert bot.temperature == 3.5


class TestBoltzmannBotFolding:
    """翻牌前弱牌面对加注时的行为。"""

    def test_nit_folds_weak_hand(self) -> None:
        """NIT (T=0.5) 面对加注应弃弱牌。"""
        game = make_game_with_bot("Nit", seat=0)
        game.start_new_hand()
        bot = BoltzmannBot("Nit", BotFactory.list_styles()[0], seed=42)
        p = game.players[0]
        p.hole_cards = Card.from_str_multi("7c 2d")
        game.current_bet = 50
        p.current_bet = 0
        # Only Fold/Call legal (no CHECK):
        # EV(Fold)=0, EV(Call)=0.25*(15+50)-50=-28.75
        # T=0.5 => P(Fold) >> P(Call)
        action = bot.decide(game, p)
        assert action.action_type == ActionType.FOLD

    def test_cs_often_calls(self) -> None:
        """Calling Station (T=8.0) 面对下注大概率跟注。"""
        calls = 0
        for s in range(20):
            game = make_game_with_bot("CS", seat=0)
            game.start_new_hand()
            bot = BoltzmannBot("CS", BotProfile(BotStyle.CALLING_STATION, 8.0), seed=s*50)
            p = game.players[0]
            p.hole_cards = Card.from_str_multi("7c 2d")
            p.current_bet = 0
            game.current_bet = 20
            a = bot.decide(game, p)
            if a.action_type == ActionType.CALL:
                calls += 1
        # T=8.0: EV(Fold)=0, EV(Call)=-3.75. P(Call)/P(Fold)=exp(-3.75/8)~63%
        assert calls >= 8


class TestBoltzmannBotPremium:
    """好牌行为。"""

    def test_nit_plays_aa(self) -> None:
        """NIT 拿到 AA 不应弃牌。"""
        game = make_game_with_bot("Nit", seat=0)
        game.start_new_hand()
        bot = BoltzmannBot("Nit", BotProfile(BotStyle.NIT, 0.5), seed=42)
        p = game.players[0]
        p.hole_cards = Card.from_str_multi("Ah As")
        action = bot.decide(game, p)
        assert action.action_type != ActionType.FOLD

    def test_all_bots_play_aa(self) -> None:
        """所有风格拿到 AA 都不应弃牌（EV 巨大）。"""
        for profile in BotFactory.list_styles():
            game = make_game_with_bot(profile.style.value, seat=0)
            game.start_new_hand()
            bot = BoltzmannBot(profile.style.value, profile, seed=42)
            p = game.players[0]
            p.hole_cards = Card.from_str_multi("Ah As")
            action = bot.decide(game, p)
            assert action.action_type != ActionType.FOLD, f"{profile.style} folded AA!"


class TestBoltzmannBotCheckRule:
    """Check 存在时禁止 Fold。"""

    def test_check_available_no_fold_possible(self) -> None:
        """可以 Check 时，Fold 不在候选集中。"""
        game = make_game_with_bot("Bot", seat=0, num=2)
        game.start_new_hand()
        bot = BoltzmannBot("Bot", BotProfile(BotStyle.SHARK, 2.0), seed=42)
        p = game.players[0]
        p.hole_cards = Card.from_str_multi("7c 2d")
        p.current_bet = 0
        game.current_bet = 0  # 可以 Check
        # 多次采样，确保不会出现 Fold
        for s in range(20):
            bot.rng = __import__('random').Random(s * 100)
            action = bot.decide(game, p)
            assert action.action_type != ActionType.FOLD

    def test_must_call_when_no_check(self) -> None:
        """不能 Check 时 Fold 仍然可选。"""
        game = make_game_with_bot("Bot", seat=0, num=2)
        game.start_new_hand()
        bot = BoltzmannBot("Bot", BotProfile(BotStyle.NIT, 0.5), seed=42)
        p = game.players[0]
        p.hole_cards = Card.from_str_multi("7c 2d")
        p.current_bet = 0
        game.current_bet = 50  # 需要跟注
        action = bot.decide(game, p)
        # NIT 应该弃牌
        assert action.action_type == ActionType.FOLD


class TestBoltzmannBotDecide:
    def test_never_returns_illegal_action(self) -> None:
        """所有风格在所有局面下返回合法动作。"""
        import random as rnd
        rng = rnd.Random(42)
        for profile in BotFactory.list_styles():
            for s in range(5):
                game = make_game_with_bot(profile.style.value, seat=0)
                game.start_new_hand()
                bot = BoltzmannBot(profile.style.value, profile, seed=s * 99)
                p = game.players[0]
                p.hole_cards = Card.from_str_multi(
                    rng.choice(["Ah Kh", "2c 7d", "As Ad", "5h 9s", "Jc Qc"])
                )
                if rng.random() < 0.3:
                    game.current_bet = rng.choice([0, 10, 30, 100])
                action = bot.decide(game, p)
                legal = game.get_legal_actions(p)
                assert action.action_type in legal, (
                    f"{profile.style} illegal action {action.action_type}, "
                    f"legal: {[a.name for a in legal]}"
                )

    def test_postflop_decision(self) -> None:
        """翻牌后决策合法。"""
        for profile in BotFactory.list_styles():
            game = make_game_with_bot(profile.style.value, seat=0)
            game.start_new_hand()
            bot = BoltzmannBot(profile.style.value, profile, seed=42)
            p = game.players[0]
            p.hole_cards = Card.from_str_multi("Ah Kh")
            game.community_cards = Card.from_str_multi("Ad 7s 2c")
            game.phase = GamePhase.FLOP
            game.current_bet = 0
            action = bot.decide(game, p)
            legal = game.get_legal_actions(p)
            assert action.action_type in legal

    def test_respects_all_in(self) -> None:
        bot = BoltzmannBot("TAG", BotProfile(BotStyle.TAG, 1.0), seed=42)
        game = make_game_with_bot("TAG", seat=0)
        game.start_new_hand()
        p = game.players[0]
        p.hole_cards = Card.from_str_multi("7c 2d")
        p.chips = 50
        game.current_bet = 500
        action = bot.decide(game, p)
        legal = game.get_legal_actions(p)
        assert action.action_type in legal


class TestBoltzmannTemperatures:
    """温度行为验证。"""

    def test_maniac_rarely_folds(self) -> None:
        """Maniac (T=16) 面对下注也不太弃牌。"""
        folds = 0
        for s in range(30):
            game = make_game_with_bot("Maniac", seat=0)
            game.start_new_hand()
            bot = BoltzmannBot("Maniac", BotProfile(BotStyle.MANIAC, 16.0), seed=s*10)
            p = game.players[0]
            p.hole_cards = Card.from_str_multi("2c 7d")
            p.current_bet = 0
            game.current_bet = 20
            action = bot.decide(game, p)
            if action.action_type == ActionType.FOLD:
                folds += 1
        # EV(Call) = -3.75, P(Fold)/P(Call) = exp(3.75/16) ≈ 1.26
        # P(Fold) ≈ 56%, P(Call) ≈ 44%. 30 samples: folds ~ 15-18
        assert folds <= 25, f"Maniac folded {folds}/30"

    def test_lag_plays_medium_hands(self) -> None:
        """LAG (T=4) 对中等牌有较高入池率。"""
        plays = 0
        for s in range(30):
            game = make_game_with_bot("LAG", seat=0)
            game.start_new_hand()
            bot = BoltzmannBot("LAG", BotProfile(BotStyle.LAG, 4.0), seed=s*33)
            p = game.players[0]
            p.hole_cards = Card.from_str_multi("5c 4h")
            action = bot.decide(game, p)
            if action.action_type != ActionType.FOLD:
                plays += 1
        # LAG T=4: 54s strength~39, EV(check)=15.6. 
        # 翻牌前 BB 未加注 -> CHECK always (no fold option)
        # But wait: check is always available preflop for BB. So plays should be 30.
        assert plays >= 10, f"LAG only played {plays}/30"
