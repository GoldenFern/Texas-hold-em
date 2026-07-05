"""RLCard Bot 测试 — 镜像适配器 + RLCardBot 决策。

所有 RLCard 相关测试使用 pytest.importorskip("rlcard") 守护；
核心测试套件在未安装 rlcard 时也能正常运行。
"""

from __future__ import annotations

import pytest

from src.engine.card import Card
from src.engine.game import Action, ActionType, GameState
from src.engine.player import Player
from src.ai.bots import BotFactory, BotProfile, BotStyle
from src.utils.constants import GamePhase


# ================================================================
# 辅助工具
# ================================================================

def make_heads_up_game() -> GameState:
    """构建一个标准的 2 人桌 GameState（1000 筹码，5/10 盲注）。"""
    players = [
        Player(name="Hero", chips=1000, seat=0),
        Player(name="Villain", chips=1000, seat=1),
    ]
    return GameState(players, small_blind=5, big_blind=10)


def make_heads_up_game_custom(chips_a: int, chips_b: int, bb: int = 10) -> GameState:
    """自定义筹码量构建 2 人桌。"""
    players = [
        Player(name="Hero", chips=chips_a, seat=0),
        Player(name="Villain", chips=chips_b, seat=1),
    ]
    return GameState(players, small_blind=bb // 2, big_blind=bb)


# ================================================================
# BotFactory 测试（无需 rlcard）
# ================================================================

class TestBotFactoryRLCard:
    """BotFactory RLCARD 创建测试。"""

    def test_rlcard_style_registered(self) -> None:
        """验证 RLCARD 已注册为 BotStyle 成员。"""
        assert BotStyle.RLCARD.value == "RLCARD"

    def test_rlcard_profile_exists(self) -> None:
        """验证 RLCARD 在 BOT_PROFILES 中有条目。"""
        from src.ai.bots import BOT_PROFILES
        assert BotStyle.RLCARD in BOT_PROFILES
        profile = BOT_PROFILES[BotStyle.RLCARD]
        assert profile.style == BotStyle.RLCARD
        assert profile.display_name == "算无遗策"

    def test_rlcard_not_in_list_styles(self) -> None:
        """验证 RLCARD（和 LLM）不在 list_styles() 中。"""
        profiles = BotFactory.list_styles()
        styles = {p.style for p in profiles}
        assert BotStyle.RLCARD not in styles
        assert BotStyle.LLM not in styles
        assert len(profiles) == 6  # 仅 6 种规则 Bot

    def test_rlcard_not_in_create_all_styles(self) -> None:
        """验证 RLCARD 不在 create_all_styles() 中。"""
        bots = BotFactory.create_all_styles()
        assert len(bots) == 6
        for bot in bots:
            assert bot.style != BotStyle.RLCARD

    def test_factory_raises_clear_error_without_rlcard(self) -> None:
        """未安装 rlcard 时，BotFactory.create(RLCARD) 应抛出清晰的错误。"""
        try:
            import rlcard  # noqa: F401
            _rl_installed = True
        except ModuleNotFoundError:
            _rl_installed = False

        if _rl_installed:
            bot = BotFactory.create(BotStyle.RLCARD, name="TestRL", seed=42)
            assert bot.style == BotStyle.SHARK
            assert bot.name == "TestRL"
        else:
            with pytest.raises(Exception):
                BotFactory.create(BotStyle.RLCARD)


# ================================================================
# MirrorAdapter 卡牌编码测试（无需 rlcard）
# ================================================================

class TestMirrorAdapterCardEncoding:
    """MirrorAdapter 卡牌索引转换测试。"""

    def test_card_index_range(self) -> None:
        """所有 52 张牌映射到 0–51。"""
        from src.rlcard.mirror_adapter import MirrorAdapter
        from src.utils.constants import Rank, Suit

        indices = set()
        for suit in Suit:
            for rank in Rank:
                card = Card(rank, suit)
                idx = MirrorAdapter.card_to_rlcard_index(card)
                assert 0 <= idx <= 51
                indices.add(idx)

        assert len(indices) == 52  # 双射

    def test_specific_card_mapping(self) -> None:
        """验证几张已知牌的索引。"""
        from src.rlcard.mirror_adapter import MirrorAdapter

        # Ah (Ace of Hearts) = suit H(2)→1, rank A(14)→12 → 1*13+12 = 25
        ah = Card.from_str("Ah")
        assert MirrorAdapter.card_to_rlcard_index(ah) == 25

        # 2c (2 of Clubs) = suit C(0)→3, rank 2(2)→0 → 3*13+0 = 39
        two_c = Card.from_str("2c")
        assert MirrorAdapter.card_to_rlcard_index(two_c) == 39

        # Ks (King of Spades) = suit S(3)→0, rank K(13)→11 → 0*13+11 = 11
        ks = Card.from_str("Ks")
        assert MirrorAdapter.card_to_rlcard_index(ks) == 11

    def test_mapping_never_collides(self) -> None:
        """不同牌不会映射到同一索引。"""
        from src.rlcard.mirror_adapter import MirrorAdapter

        all_cards = []
        for suit_str in ["c", "d", "h", "s"]:
            for rank_str in ["A", "K", "Q", "J", "T", "9", "8", "7", "6", "5", "4", "3", "2"]:
                all_cards.append(Card.from_str(rank_str + suit_str))

        indices = [MirrorAdapter.card_to_rlcard_index(c) for c in all_cards]
        assert len(set(indices)) == 52


# ================================================================
# MirrorAdapter observation 编码测试
# ================================================================

class TestMirrorAdapterObservation:
    """Observation 编码测试。"""

    def test_obs_shape(self) -> None:
        """Observation 应为 54 维。"""
        from src.rlcard.mirror_adapter import MirrorAdapter

        game = make_heads_up_game()
        game.start_new_hand()
        hero = game.players[0]
        hero.hole_cards = Card.from_str_multi("Ah Kh")

        obs = MirrorAdapter.encode_observation(game, hero)
        assert obs.shape == (54,)
        assert obs.dtype.name == "float32"

    def test_hole_cards_encoded(self) -> None:
        """底牌在 one-hot 中正确置 1。"""
        from src.rlcard.mirror_adapter import MirrorAdapter

        game = make_heads_up_game()
        game.start_new_hand()
        hero = game.players[0]
        hero.hole_cards = Card.from_str_multi("Ah Kh")

        obs = MirrorAdapter.encode_observation(game, hero)

        ah_idx = MirrorAdapter.card_to_rlcard_index(Card.from_str("Ah"))
        kh_idx = MirrorAdapter.card_to_rlcard_index(Card.from_str("Kh"))

        assert obs[ah_idx] == 1.0
        assert obs[kh_idx] == 1.0

    def test_community_cards_encoded(self) -> None:
        """公共牌在 one-hot 中正确置 1。"""
        from src.rlcard.mirror_adapter import MirrorAdapter

        game = make_heads_up_game()
        game.phase = GamePhase.FLOP
        game.community_cards = Card.from_str_multi("Ad 7s 2c")
        hero = game.players[0]
        hero.hole_cards = Card.from_str_multi("5h 9s")

        obs = MirrorAdapter.encode_observation(game, hero)

        ad_idx = MirrorAdapter.card_to_rlcard_index(Card.from_str("Ad"))
        s7_idx = MirrorAdapter.card_to_rlcard_index(Card.from_str("7s"))
        c2_idx = MirrorAdapter.card_to_rlcard_index(Card.from_str("2c"))

        assert obs[ad_idx] == 1.0
        assert obs[s7_idx] == 1.0
        assert obs[c2_idx] == 1.0

    def test_bb_normalization(self) -> None:
        """筹码以 BB 为单位归一化。"""
        from src.rlcard.mirror_adapter import MirrorAdapter

        game = make_heads_up_game()
        game.start_new_hand()
        hero = game.players[0]
        hero.hole_cards = Card.from_str_multi("Ah Kh")
        # 盲注已扣，调整筹码
        hero.chips = 500  # 50 BB
        game.players[1].chips = 200  # 20 BB

        obs = MirrorAdapter.encode_observation(game, hero)
        assert obs[52] == pytest.approx(50.0, rel=1e-4)
        assert obs[53] == pytest.approx(20.0, rel=1e-4)

    def test_bb_normalization_invariant(self) -> None:
        """BB 归一化不变量：1000/10 ≡ 100/1。"""
        from src.rlcard.mirror_adapter import MirrorAdapter

        # 场景 A：1000 筹码，BB=10
        game_a = make_heads_up_game_custom(1000, 1000, bb=10)
        game_a.start_new_hand()
        hero_a = game_a.players[0]
        hero_a.hole_cards = Card.from_str_multi("Ah Kh")

        obs_a = MirrorAdapter.encode_observation(game_a, hero_a)

        # 场景 B：100 筹码，BB=1（等效深度）
        game_b = make_heads_up_game_custom(100, 100, bb=1)
        game_b.start_new_hand()
        hero_b = game_b.players[0]
        hero_b.hole_cards = Card.from_str_multi("Ah Kh")

        obs_b = MirrorAdapter.encode_observation(game_b, hero_b)

        # 卡牌部分应完全相同
        assert (obs_a[:52] == obs_b[:52]).all()
        # 筹码归一化后应相等
        assert obs_a[52] == pytest.approx(obs_b[52], rel=0.15)
        assert obs_a[53] == pytest.approx(obs_b[53], rel=0.15)


# ================================================================
# MirrorAdapter 合法动作测试
# ================================================================

class TestMirrorAdapterLegalActions:
    """合法 RLCard 动作枚举测试。"""

    def test_preflop_no_raise_facing_bet(self) -> None:
        """翻牌前面对下注，合法动作应包含 FOLD + CHECK/CALL。"""
        from src.rlcard.mirror_adapter import MirrorAdapter

        game = make_heads_up_game()
        game.start_new_hand()
        hero = game.players[0]
        hero.current_bet = 0
        game.current_bet = 30
        game.pot._main_pot = 15
        game.pot._total = 15

        legal = MirrorAdapter.get_legal_rlcard_actions(game, hero)
        assert 0 in legal  # FOLD
        assert 1 in legal  # CHECK/CALL

    def test_can_check_has_check_call(self) -> None:
        """可以 Check 时 CHECK/CALL 应存在。"""
        from src.rlcard.mirror_adapter import MirrorAdapter

        game = make_heads_up_game()
        game.start_new_hand()
        hero = game.players[0]
        hero.current_bet = game.current_bet

        legal = MirrorAdapter.get_legal_rlcard_actions(game, hero)
        assert 1 in legal  # CHECK/CALL

    def test_raise_tiers_present_with_sufficient_chips(self) -> None:
        """筹码充足时加注层级应存在。"""
        from src.rlcard.mirror_adapter import MirrorAdapter

        game = make_heads_up_game()
        game.start_new_hand()
        hero = game.players[0]
        hero.chips = 1000
        game.current_bet = 100
        game.pot._main_pot = 200
        game.pot._total = 200
        hero.current_bet = 0

        legal = MirrorAdapter.get_legal_rlcard_actions(game, hero)
        assert 0 in legal  # FOLD
        assert 1 in legal  # CALL
        # 加注层级应有至少一项
        has_raise = any(rid in legal for rid in (2, 3, 4))
        assert has_raise, f"应存在加注层级, legal={legal}"


# ================================================================
# MirrorAdapter 动作映射测试
# ================================================================

class TestMirrorAdapterActionMapping:
    """RLCard action_id → 引擎 Action 映射测试。"""

    def test_fold_maps_to_fold(self) -> None:
        """RLCard FOLD → 引擎 FOLD。"""
        from src.rlcard.mirror_adapter import MirrorAdapter, RLCARD_FOLD

        game = make_heads_up_game()
        game.start_new_hand()
        hero = game.players[0]

        action = MirrorAdapter.rlcard_action_to_engine(game, hero, RLCARD_FOLD)
        assert action.action_type == ActionType.FOLD
        assert action.amount == 0

    def test_check_call_when_to_call_zero(self) -> None:
        """RLCard CHECK/CALL + to_call=0 → 引擎 CHECK。"""
        from src.rlcard.mirror_adapter import MirrorAdapter, RLCARD_CHECK_CALL

        game = make_heads_up_game()
        game.start_new_hand()
        hero = game.players[0]
        hero.current_bet = game.current_bet  # 平齐

        action = MirrorAdapter.rlcard_action_to_engine(game, hero, RLCARD_CHECK_CALL)
        assert action.action_type == ActionType.CHECK

    def test_check_call_when_to_call_positive(self) -> None:
        """RLCard CHECK/CALL + to_call>0 → 引擎 CALL。"""
        from src.rlcard.mirror_adapter import MirrorAdapter, RLCARD_CHECK_CALL

        game = make_heads_up_game()
        game.start_new_hand()
        hero = game.players[0]
        hero.current_bet = 0
        game.current_bet = 50

        action = MirrorAdapter.rlcard_action_to_engine(game, hero, RLCARD_CHECK_CALL)
        assert action.action_type == ActionType.CALL

    def test_half_pot_raise_formula(self) -> None:
        """半池加注总额 = to_call + 0.5 * 行动前底池。"""
        from src.rlcard.mirror_adapter import MirrorAdapter, RLCARD_RAISE_HALF_POT

        game = make_heads_up_game()
        game.start_new_hand()
        hero = game.players[0]
        hero.chips = 1000
        hero.current_bet = 0
        game.current_bet = 20
        game.pot._main_pot = 35
        game.pot._total = 35

        action = MirrorAdapter.rlcard_action_to_engine(game, hero, RLCARD_RAISE_HALF_POT)
        assert action.action_type == ActionType.RAISE
        assert action.amount >= 20  # 至少跟注
        assert action.amount <= hero.chips + hero.current_bet

    def test_full_pot_raise_formula(self) -> None:
        """满池加注总额 = to_call + 1.0 * 行动前底池。"""
        from src.rlcard.mirror_adapter import MirrorAdapter, RLCARD_RAISE_POT

        game = make_heads_up_game()
        game.start_new_hand()
        hero = game.players[0]
        hero.chips = 1000
        hero.current_bet = 0
        game.current_bet = 20
        game.pot._main_pot = 35
        game.pot._total = 35

        action = MirrorAdapter.rlcard_action_to_engine(game, hero, RLCARD_RAISE_POT)
        expected_total = 20 + 35  # to_call + pot_before
        assert action.action_type == ActionType.RAISE
        assert action.amount == max(expected_total, game.get_min_raise_amount(hero))

    def test_all_in_maps_correctly(self) -> None:
        """全下动作映射为引擎全下。"""
        from src.rlcard.mirror_adapter import MirrorAdapter, RLCARD_ALL_IN

        game = make_heads_up_game()
        game.start_new_hand()
        hero = game.players[0]
        hero.chips = 500

        action = MirrorAdapter.rlcard_action_to_engine(game, hero, RLCARD_ALL_IN)
        assert action.is_all_in
        assert action.amount == hero.chips + hero.current_bet

    def test_action_amount_clamped_to_max(self) -> None:
        """动作金额不超过 max_bet。"""
        from src.rlcard.mirror_adapter import MirrorAdapter, RLCARD_RAISE_POT

        game = make_heads_up_game()
        game.start_new_hand()
        hero = game.players[0]
        hero.chips = 30
        game.current_bet = 50
        game.pot._main_pot = 100
        game.pot._total = 100

        action = MirrorAdapter.rlcard_action_to_engine(game, hero, RLCARD_RAISE_POT)
        max_possible = hero.chips + hero.current_bet
        assert action.amount <= max_possible

    def test_bet_vs_raise_distinction(self) -> None:
        """当前下注为 0 时使用 BET；否则使用 RAISE。"""
        from src.rlcard.mirror_adapter import MirrorAdapter, RLCARD_RAISE_HALF_POT

        # 场景 1: current_bet=0 → BET
        game1 = make_heads_up_game()
        game1.start_new_hand()
        hero1 = game1.players[0]
        hero1.current_bet = 0
        game1.current_bet = 0
        hero1.chips = 1000
        game1.pot._main_pot = 15
        game1.pot._total = 15
        action1 = MirrorAdapter.rlcard_action_to_engine(game1, hero1, RLCARD_RAISE_HALF_POT)
        assert action1.action_type == ActionType.BET

        # 场景 2: current_bet>0 → RAISE
        game2 = make_heads_up_game()
        game2.start_new_hand()
        hero2 = game2.players[0]
        hero2.current_bet = 0
        game2.current_bet = 20
        hero2.chips = 1000
        game2.pot._main_pot = 35
        game2.pot._total = 35
        action2 = MirrorAdapter.rlcard_action_to_engine(game2, hero2, RLCARD_RAISE_HALF_POT)
        assert action2.action_type == ActionType.RAISE


# ================================================================
# RLCardBot 决策测试（需要 rlcard）
# ================================================================


def _require_rlcard():
    """若 rlcard 未安装则跳过当前测试。"""
    pytest.importorskip("rlcard", reason="rlcard 未安装，跳过 RLCardBot 决策测试")


class TestRLCardBotCreation:
    """RLCardBot 创建测试。"""

    def test_bot_created_with_random_agent(self) -> None:
        """默认创建使用 RandomAgent。"""
        _require_rlcard()
        from src.rlcard.rlcard_bot import RLCardBot

        bot = RLCardBot("TestRL", seed=42)
        assert bot.name == "TestRL"
        assert bot._agent is not None
        assert bot._num_actions == 5

    def test_bot_through_factory(self) -> None:
        """通过 BotFactory 创建 RLCardBot。"""
        _require_rlcard()
        from src.rlcard.rlcard_bot import RLCardBot

        bot = BotFactory.create(BotStyle.RLCARD, name="FactoryRL", seed=42)
        assert bot.name == "FactoryRL"
        assert isinstance(bot, RLCardBot)


class TestRLCardBotDecide:
    """RLCardBot.decide() 测试。"""

    def test_returns_legal_action_preflop(self) -> None:
        """翻牌前决策必须合法。"""
        _require_rlcard()
        from src.rlcard.rlcard_bot import RLCardBot

        game = make_heads_up_game()
        game.start_new_hand()
        bot = RLCardBot("TestRL", seed=42)
        hero = game.players[0]
        hero.hole_cards = Card.from_str_multi("Ah Kh")

        for _ in range(10):
            action = bot.decide(game, hero)
            legal = game.get_legal_actions(hero)
            assert action.action_type in legal, (
                f"非法动作 {action.action_type.name}，"
                f"合法: {[a.name for a in legal]}"
            )

    def test_never_returns_illegal_action_multiple_phases(self) -> None:
        """多个阶段决策均合法。"""
        _require_rlcard()
        from src.rlcard.rlcard_bot import RLCardBot

        for seed in range(5):
            game = make_heads_up_game()
            game.start_new_hand()
            bot = RLCardBot("TestRL", seed=seed * 42)
            hero = game.players[0]
            hero.hole_cards = Card.from_str_multi("Ah Kh")

            action = bot.decide(game, hero)
            legal = game.get_legal_actions(hero)
            assert action.action_type in legal

            # 进入翻牌
            game.community_cards = Card.from_str_multi("Ad 7s 2c")
            game.phase = GamePhase.FLOP
            game.current_bet = 0
            hero.current_bet = 0
            action = bot.decide(game, hero)
            legal = game.get_legal_actions(hero)
            assert action.action_type in legal

    def test_weak_hand_can_fold(self) -> None:
        """弱牌面对大加注可以弃牌。"""
        _require_rlcard()
        from src.rlcard.rlcard_bot import RLCardBot

        game = make_heads_up_game()
        game.start_new_hand()
        bot = RLCardBot("TestRL", seed=42)
        hero = game.players[0]
        hero.hole_cards = Card.from_str_multi("2c 7d")
        hero.current_bet = 0
        game.current_bet = 200

        action = bot.decide(game, hero)
        legal = game.get_legal_actions(hero)
        assert action.action_type in legal

    def test_all_in_respected(self) -> None:
        """筹码极少时决策合法。"""
        _require_rlcard()
        from src.rlcard.rlcard_bot import RLCardBot

        game = make_heads_up_game()
        game.start_new_hand()
        bot = RLCardBot("TestRL", seed=42)
        hero = game.players[0]
        hero.hole_cards = Card.from_str_multi("7c 2d")
        hero.chips = 50
        game.current_bet = 500

        action = bot.decide(game, hero)
        legal = game.get_legal_actions(hero)
        assert action.action_type in legal


class TestRLCardBotIntegration:
    """RLCardBot 集成测试。"""

    def test_heads_up_hand_completes(self) -> None:
        """RLCardBot + 规则 Bot 完整一手牌测试。"""
        _require_rlcard()
        from src.rlcard.rlcard_bot import RLCardBot

        rl_bot = RLCardBot("RL", seed=42)
        rule_bot = BotFactory.create(BotStyle.SHARK, name="Shark", seed=99)

        bots = [rl_bot, rule_bot]
        players = [
            Player(name=bot.name, chips=1000, seat=i)
            for i, bot in enumerate(bots)
        ]

        game = GameState(players, small_blind=5, big_blind=10)
        game.start_new_hand()

        for _ in range(100):
            if game.phase.value >= 6:
                break
            cp = game.players[game.current_player_index]
            bot = bots[cp.seat]
            action = bot.decide(game, cp)

            legal = game.get_legal_actions(cp)
            if action.action_type not in legal:
                if ActionType.CHECK in legal:
                    action = Action(cp.name, ActionType.CHECK)
                elif ActionType.CALL in legal:
                    action = Action(cp.name, ActionType.CALL)
                else:
                    action = Action(cp.name, ActionType.FOLD)

            if action.action_type in (ActionType.BET, ActionType.RAISE):
                if action.amount > cp.chips + cp.current_bet:
                    action.amount = cp.chips + cp.current_bet
                    action.is_all_in = True
                min_raise = game.get_min_raise_amount(cp)
                if action.amount < min_raise:
                    action.amount = min_raise

            game.apply_action(action)

        assert game.phase == GamePhase.FINISHED

    def test_multiple_hands_with_rlcard_bot(self) -> None:
        """RLCardBot 连续多手牌测试。"""
        _require_rlcard()
        from src.rlcard.rlcard_bot import RLCardBot

        rl_bot = RLCardBot("RL", seed=42)
        rule_bot = BotFactory.create(BotStyle.SHARK, name="Shark", seed=99)
        bots = [rl_bot, rule_bot]
        players = [
            Player(name=bot.name, chips=1000, seat=i)
            for i, bot in enumerate(bots)
        ]

        game = GameState(players, small_blind=5, big_blind=10)

        hands_completed = 0
        for _ in range(3):
            game.start_new_hand()

            active = [p for p in players if p.chips > 0]
            if len(active) < 2:
                break

            for _ in range(100):
                if game.phase.value >= 6:
                    break
                cp = game.players[game.current_player_index]
                bot = bots[cp.seat]
                action = bot.decide(game, cp)

                legal = game.get_legal_actions(cp)
                if action.action_type not in legal:
                    if ActionType.CHECK in legal:
                        action = Action(cp.name, ActionType.CHECK)
                    elif ActionType.CALL in legal:
                        action = Action(cp.name, ActionType.CALL)
                    else:
                        action = Action(cp.name, ActionType.FOLD)

                if action.action_type in (ActionType.BET, ActionType.RAISE):
                    if action.amount > cp.chips + cp.current_bet:
                        action.amount = cp.chips + cp.current_bet
                        action.is_all_in = True

                game.apply_action(action)

            if game.phase == GamePhase.FINISHED:
                hands_completed += 1

            for p in players:
                if p.chips <= 0:
                    p.chips = 200
                p.reset_for_new_hand()

        assert hands_completed >= 1, "至少应完成一手牌"
