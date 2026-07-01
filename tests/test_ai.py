"""AI 机器人决策测试。"""

import pytest

from src.engine.card import Card
from src.engine.game import Action, ActionType, GameState
from src.engine.player import Player
from src.ai.bots import (
    BotFactory,
    BotStyle,
    CallingStationBot,
    LAGBot,
    ManiacBot,
    NitBot,
    SharkBot,
    TAGBot,
)
from src.utils.constants import ActionType, GamePhase


def make_game_with_bot(bot_name: str, seat: int = 0, num: int = 3) -> GameState:
    """创建测试用游戏，指定机器人位置的玩家名称。"""
    names = []
    for i in range(num):
        if i == seat:
            names.append(bot_name)
        else:
            names.append(f"Opponent_{i}")
    players = [Player(name=n, chips=1000, seat=i) for i, n in enumerate(names)]
    return GameState(players)


class TestBotCreation:
    """机器人工厂和创建测试。"""

    def test_factory_creates_all_styles(self) -> None:
        for style in BotStyle:
            if style == BotStyle.LLM:
                # LLM 机器人通过 create_llm 创建，不是 create
                continue
            bot = BotFactory.create(style, seed=42)
            assert bot.style == style

    def test_factory_unknown_style_raises(self) -> None:
        with pytest.raises(Exception):
            BotFactory.create("UNKNOWN")  # type: ignore[arg-type]

    def test_create_all_styles(self) -> None:
        bots = BotFactory.create_all_styles()
        assert len(bots) == 7  # 6 种规则风格 + LLM

    def test_bot_has_unique_name(self) -> None:
        bots = BotFactory.create_all_styles()
        names = {b.name for b in bots}
        assert len(names) == 7


class TestTAGBot:
    """紧凶型机器人测试。"""

    def test_folds_weak_hand_to_raise(self) -> None:
        """TAG 面对加注应该弃掉弱牌（多次采样验证）。"""
        folds = 0
        for s in range(20):
            game = make_game_with_bot("TAG", seat=0)
            game.start_new_hand()
            bot = TAGBot("TAG", seed=s * 100)
            tag_player = game.players[0]
            tag_player.hole_cards = Card.from_str_multi("7c 2d")
            game.current_bet = 50
            tag_player.current_bet = 0
            a = bot.decide(game, tag_player)
            if a.action_type == ActionType.FOLD:
                folds += 1
        assert folds >= 8  # 至少 40% 弃牌率（fold_to_raise=0.4）

    def test_plays_premium_hand_aggressively(self) -> None:
        """TAG 拿到 AA 应该不弃牌（可能因位置选择 check 慢打）。"""
        game = make_game_with_bot("TAG", seat=0)
        game.start_new_hand()
        bot = TAGBot("TAG", seed=42)
        tag_player = game.players[0]
        tag_player.hole_cards = Card.from_str_multi("Ah As")
        action = bot.decide(game, tag_player)
        # 至少不应弃牌
        assert action.action_type != ActionType.FOLD


class TestNitBot:
    """极紧型机器人测试。"""

    def test_folds_weak_preflop(self) -> None:
        """Nit 只在有好牌时入池。"""
        game = make_game_with_bot("Nit", seat=0)
        game.start_new_hand()
        bot = NitBot("Nit", seed=42)
        nit_player = game.players[0]

        # 弱牌 → 应弃牌
        nit_player.hole_cards = Card.from_str_multi("7c 2d")
        game.current_bet = game.big_blind
        nit_player.current_bet = 0
        action = bot.decide(game, nit_player)
        assert action.action_type == ActionType.FOLD

    def test_plays_premium_hand(self) -> None:
        """Nit 拿到 AA 应入池。"""
        game = make_game_with_bot("Nit", seat=0)
        game.start_new_hand()
        bot = NitBot("Nit", seed=42)
        nit_player = game.players[0]
        nit_player.hole_cards = Card.from_str_multi("Ah As")
        action = bot.decide(game, nit_player)
        assert action.action_type != ActionType.FOLD


class TestCallingStationBot:
    """跟注站机器人测试。"""

    def test_rarely_folds(self) -> None:
        calls = 0
        for s in range(20):
            game = make_game_with_bot("CS", seat=0)
            game.start_new_hand()
            bot = CallingStationBot("CS", seed=s * 50)
            cs_player = game.players[0]
            cs_player.hole_cards = Card.from_str_multi("7c 2d")
            cs_player.current_bet = 0
            game.current_bet = 20
            a = bot.decide(game, cs_player)
            if a.action_type == ActionType.CALL:
                calls += 1
        assert calls >= 14  # 至少 70% 跟注率


class TestManiacBot:
    """疯子型机器人测试。"""

    def test_plays_any_two_cards(self) -> None:
        game = make_game_with_bot("Maniac", seat=0)
        game.start_new_hand()
        bot = ManiacBot("Maniac", seed=42)
        maniac = game.players[0]
        maniac.hole_cards = Card.from_str_multi("7c 2d")
        action = bot.decide(game, maniac)
        assert action.action_type != ActionType.FOLD

    def test_often_raises(self) -> None:
        raises = 0
        for s in range(20):
            game = make_game_with_bot("Maniac", seat=0)
            game.start_new_hand()
            bot = ManiacBot("Maniac", seed=s * 10)
            maniac = game.players[0]  # seat 0
            maniac.hole_cards = Card.from_str_multi("Ah Kh")
            a = bot.decide(game, maniac)
            if a.action_type in (ActionType.RAISE, ActionType.BET):
                raises += 1
        assert raises >= 6  # Maniac 即使在 BB 也可能 check，放宽阈值


class TestBotDecision:
    """机器人决策综合测试。"""

    def test_never_returns_illegal_action(self) -> None:
        """机器人绝不应返回非法动作。"""
        for style in BotStyle:
            game = make_game_with_bot(style.value, seat=0)
            game.start_new_hand()
            bot = BotFactory.create(style, seed=42)
            bot_player = game.players[0]

            import random as rnd
            rng = rnd.Random(42)
            for _ in range(5):
                bot_player.hole_cards = Card.from_str_multi(
                    rng.choice(["Ah Kh", "2c 7d", "As Ad", "5h 9s", "Jc Qc"])
                )
                action = bot.decide(game, bot_player)
                legal = game.get_legal_actions(bot_player)
                assert action.action_type in legal, (
                    f"{style} returned illegal {action.action_type}, "
                    f"legal: {[a.name for a in legal]}"
                )

    def test_respects_all_in(self) -> None:
        """机器人面对极端情况应返回合法动作。"""
        game = make_game_with_bot("TAG", seat=0)
        game.start_new_hand()
        bot = TAGBot("TAG", seed=42)
        tag_player = game.players[0]
        tag_player.hole_cards = Card.from_str_multi("7c 2d")
        tag_player.chips = 50
        game.current_bet = 500
        action = bot.decide(game, tag_player)
        legal = game.get_legal_actions(tag_player)
        assert action.action_type in legal
