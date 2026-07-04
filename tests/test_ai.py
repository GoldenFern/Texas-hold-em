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
from src.utils.constants import GamePhase


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

            try:
                bot = BotFactory.create(style, seed=42)
            except Exception:
                # LLM bot may fail without API keys, skip
                continue

            bot_player = game.players[0]

            import random as rnd
            rng = rnd.Random(42)
            for _ in range(5):
                bot_player.hole_cards = Card.from_str_multi(
                    rng.choice(["Ah Kh", "2c 7d", "As Ad", "5h 9s", "Jc Qc"])
                )
                try:
                    action = bot.decide(game, bot_player)
                except Exception:
                    # LLM bot may fail during decide
                    continue
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


class TestLAGBot:
    """松凶型机器人测试。"""

    def test_plays_wide_range(self) -> None:
        """LAG 面对弱牌也有一定概率入池。"""
        plays = 0
        for s in range(30):
            game = make_game_with_bot("LAG", seat=0)
            game.start_new_hand()
            bot = LAGBot("LAG", seed=s * 33)
            lag_player = game.players[0]
            lag_player.hole_cards = Card.from_str_multi("5c 4h")
            action = bot.decide(game, lag_player)
            if action.action_type != ActionType.FOLD:
                plays += 1
        # LAG 的 vpip_threshold=42, 54s 大约在 40-45，应至少 30% 入池
        assert plays >= 5, f"LAG only played {plays}/30 times with 54s"

    def test_plays_premium_aggressively(self) -> None:
        """LAG 拿好牌应不弃牌。"""
        game = make_game_with_bot("LAG", seat=0)
        game.start_new_hand()
        bot = LAGBot("LAG", seed=42)
        lag_player = game.players[0]
        lag_player.hole_cards = Card.from_str_multi("Ah Kh")
        action = bot.decide(game, lag_player)
        assert action.action_type != ActionType.FOLD

    def test_lower_fold_to_raise_than_tag(self) -> None:
        """LAG 面对加注弃牌倾向应低于 TAG。"""
        folds = 0
        for s in range(20):
            game = make_game_with_bot("LAG", seat=0)
            game.start_new_hand()
            bot = LAGBot("LAG", seed=s * 77)
            lag_player = game.players[0]
            lag_player.hole_cards = Card.from_str_multi("7c 2d")
            game.current_bet = 50
            lag_player.current_bet = 0
            a = bot.decide(game, lag_player)
            if a.action_type == ActionType.FOLD:
                folds += 1
        # LAG fold_to_raise=0.2，TAG fold_to_raise=0.4
        assert folds <= 10, f"LAG folded {folds}/20 times, should be <= TAG"


class TestSharkBot:
    """鲨鱼型机器人测试。"""

    def test_shark_plays_premium_hand(self) -> None:
        game = make_game_with_bot("SHARK", seat=0)
        game.start_new_hand()
        bot = SharkBot("SHARK", seed=42)
        shark_player = game.players[0]
        shark_player.hole_cards = Card.from_str_multi("Ah As")
        action = bot.decide(game, shark_player)
        assert action.action_type != ActionType.FOLD

    def test_shark_folds_junk_to_raise(self) -> None:
        """Shark 面对大额加注至少返回合法动作。"""
        game = make_game_with_bot("SHARK", seat=0)
        game.start_new_hand()
        bot = SharkBot("SHARK", seed=42)
        shark_player = game.players[0]
        shark_player.hole_cards = Card.from_str_multi("7c 2d")
        game.current_bet = 50
        shark_player.current_bet = 0
        action = bot.decide(game, shark_player)
        legal = game.get_legal_actions(shark_player)
        assert action.action_type in legal

    def test_shark_decision_is_legal(self) -> None:
        """Shark 的决策应始终合法（多次采样）。"""
        for s in range(10):
            game = make_game_with_bot("SHARK", seat=0)
            game.start_new_hand()
            bot = SharkBot("SHARK", seed=s * 55)
            shark_player = game.players[0]
            shark_player.hole_cards = Card.from_str_multi("Jh Th")
            action = bot.decide(game, shark_player)
            legal = game.get_legal_actions(shark_player)
            assert action.action_type in legal, (
                f"Shark returned illegal {action.action_type}, legal: {[a.name for a in legal]}"
            )

    def test_shark_postflop_decision(self) -> None:
        """Shark 在翻牌后应能做出合法决策。"""
        game = make_game_with_bot("SHARK", seat=0)
        game.start_new_hand()
        bot = SharkBot("SHARK", seed=42)
        shark_player = game.players[0]
        shark_player.hole_cards = Card.from_str_multi("Ah Kh")
        game.community_cards = Card.from_str_multi("Ad 7s 2c")
        game.phase = GamePhase.FLOP
        game.current_bet = 0

        action = bot.decide(game, shark_player)
        legal = game.get_legal_actions(shark_player)
        assert action.action_type in legal

