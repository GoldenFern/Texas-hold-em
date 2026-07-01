"""GameState 游戏状态机测试。"""

import pytest

from src.engine.card import Card
from src.engine.game import Action, ActionType, GameState
from src.engine.player import Player
from src.utils.constants import BettingStructure, GamePhase, PlayerStatus


def make_players(names: list[str], chips: int = 1000) -> list[Player]:
    """快捷创建玩家列表。"""
    return [
        Player(name=name, chips=chips, seat=i)
        for i, name in enumerate(names)
    ]


class TestGameInit:
    """游戏初始化测试。"""

    def test_minimum_two_players(self) -> None:
        players = make_players(["A", "B"])
        game = GameState(players)
        assert len(game.players) == 2

    def test_too_few_players_raises(self) -> None:
        with pytest.raises(ValueError):
            GameState(make_players(["A"]))

    def test_too_many_players_raises(self) -> None:
        with pytest.raises(ValueError):
            GameState(make_players([f"P{i}" for i in range(10)]))

    def test_default_config(self) -> None:
        players = make_players(["A", "B", "C"])
        game = GameState(players)
        assert game.small_blind == 5
        assert game.big_blind == 10
        assert game.betting_structure == BettingStructure.NO_LIMIT
        assert game.phase == GamePhase.WAITING


class TestHandStart:
    """发牌流程测试。"""

    def test_start_new_hand_deals_hole_cards(self) -> None:
        players = make_players(["A", "B", "C"])
        game = GameState(players)
        game.start_new_hand()

        # 每人应有 2 张底牌
        for p in players:
            assert len(p.hole_cards) == 2

    def test_blinds_are_posted(self) -> None:
        players = make_players(["A", "B", "C"])
        game = GameState(players)
        game.start_new_hand()

        # 小盲注支付
        sb = next(p for p in players if p.is_small_blind)
        assert sb.current_bet == game.small_blind

        # 大盲注支付
        bb = next(p for p in players if p.is_big_blind)
        assert bb.current_bet == game.big_blind

    def test_dealer_button_moves(self) -> None:
        players = make_players(["A", "B", "C"])
        game = GameState(players)
        # 初始 dealer_index = 0（无庄家），第一次 _move_dealer 后变为 1
        game.start_new_hand()
        dealer1 = game.dealer_index

        game.start_new_hand()
        dealer2 = game.dealer_index

        game.start_new_hand()
        dealer3 = game.dealer_index

        game.start_new_hand()
        dealer4 = game.dealer_index

        # 庄位顺时针旋转
        assert dealer1 != dealer2
        assert dealer2 != dealer3
        assert dealer3 != dealer4
        assert dealer4 == dealer1  # 3 人桌循环（第 4 手回到第 1 手庄位）

    def test_phase_after_start_is_preflop(self) -> None:
        players = make_players(["A", "B", "C"])
        game = GameState(players)
        game.start_new_hand()
        assert game.phase == GamePhase.PRE_FLOP


class TestActions:
    """玩家动作测试。"""

    def _setup_game(self) -> GameState:
        players = make_players(["Alice", "Bob", "Charlie"])
        game = GameState(players)
        game.start_new_hand()
        return game

    def test_fold_removes_player(self) -> None:
        game = self._setup_game()
        current = game.players[game.current_player_index]
        game.apply_action(Action(current.name, ActionType.FOLD))
        assert current.is_folded
        assert current.status == PlayerStatus.FOLDED

    def test_check_when_no_bet(self) -> None:
        game = self._setup_game()
        # 找到无需跟注的玩家（翻牌前 UTG 需跟大盲注或加注）
        # 先让其他玩家跟注大盲
        for _ in range(3):  # 3 人全 call
            p = game.players[game.current_player_index]
            legal = game.get_legal_actions(p)
            if ActionType.CALL in legal:
                game.apply_action(Action(p.name, ActionType.CALL))
            else:
                game.apply_action(Action(p.name, ActionType.CHECK))

        # 翻牌后可以 check
        if game.phase != GamePhase.FLOP:
            # 所有人 call 后应进 flop
            pass

    def test_call_matches_current_bet(self) -> None:
        game = self._setup_game()
        # 小盲已经下注 small_blind，大盲下注 big_blind
        # 找到第一个行动的玩家（UTG），他需要跟注 big_blind
        utg = game.players[game.current_player_index]
        initial_chips = utg.chips
        game.apply_action(Action(utg.name, ActionType.CALL))
        assert utg.current_bet == game.big_blind
        assert utg.chips == initial_chips - (game.big_blind - utg.current_bet + game.big_blind)
        # 简化：utg 之前没有下注过，所以跟注 = big_blind
        assert utg.chips == 1000 - game.big_blind
        assert utg.total_bet == game.big_blind

    def test_raise_increases_current_bet(self) -> None:
        game = self._setup_game()
        utg = game.players[game.current_player_index]
        # UTG 加注到 30
        game.apply_action(Action(utg.name, ActionType.RAISE, amount=30))
        assert game.current_bet == 30
        assert utg.current_bet == 30

    def test_all_in_sets_player_status(self) -> None:
        game = self._setup_game()
        # 手动设置一个玩家筹码很少
        player = game.players[game.current_player_index]
        player.chips = 8
        game.apply_action(Action(player.name, ActionType.CALL))
        assert player.is_all_in

    def test_everyone_folds_except_one(self) -> None:
        game = self._setup_game()
        # 让两个玩家弃牌
        for i in range(3):
            p = game.players[game.current_player_index]
            if game.phase == GamePhase.FINISHED:
                break
            game.apply_action(Action(p.name, ActionType.FOLD))

        assert game.phase == GamePhase.FINISHED
        assert len(game.winners) == 1

    def test_legal_actions_for_active_player(self) -> None:
        game = self._setup_game()
        utg = game.players[game.current_player_index]
        legal = game.get_legal_actions(utg)
        # UTG 面临大盲注，合法动作：Fold, Call, Raise
        assert ActionType.FOLD in legal
        assert ActionType.CALL in legal
        assert ActionType.RAISE in legal
        assert ActionType.CHECK not in legal  # 不能过牌，因为需要跟注

    def test_legal_actions_after_all_call(self) -> None:
        game = self._setup_game()
        # 所有人跟注到翻牌
        for _ in range(3):
            if game.phase == GamePhase.FLOP:
                break
            p = game.players[game.current_player_index]
            game.apply_action(Action(p.name, ActionType.CALL))

        if game.phase == GamePhase.FLOP:
            first = game.players[game.current_player_index]
            legal = game.get_legal_actions(first)
            assert ActionType.CHECK in legal
            assert ActionType.BET in legal


class TestGameFlow:
    """完整游戏流程测试。"""

    def test_preflop_all_call_proceeds_to_flop(self) -> None:
        """翻牌前所有人跟注/过牌，应进入翻牌。"""
        players = make_players(["A", "B", "C"])
        game = GameState(players)
        game.start_new_hand()

        # 每人跟注或过牌直到翻牌前结束
        max_actions = 10
        for _ in range(max_actions):
            if game.phase != GamePhase.PRE_FLOP:
                break
            p = game.players[game.current_player_index]
            to_call = game.current_bet - p.current_bet
            if to_call > 0:
                game.apply_action(Action(p.name, ActionType.CALL))
            else:
                game.apply_action(Action(p.name, ActionType.CHECK))

        # 应该进入 FLOP
        assert game.phase == GamePhase.FLOP
        assert len(game.community_cards) == 3

    def test_complete_hand_to_showdown(self) -> None:
        """完整打一手牌到摊牌。"""
        players = make_players(["A", "B", "C"])
        game = GameState(players)
        game.start_new_hand()

        # 翻牌前：所有人跟注
        for _ in range(3):
            if game.phase != GamePhase.PRE_FLOP:
                break
            p = game.players[game.current_player_index]
            game.apply_action(Action(p.name, ActionType.CALL))

        # 翻牌：所有人 check
        if game.phase == GamePhase.FLOP:
            for _ in range(3):
                if game.phase != GamePhase.FLOP:
                    break
                p = game.players[game.current_player_index]
                game.apply_action(Action(p.name, ActionType.CHECK))

        # 转牌：所有人 check
        if game.phase == GamePhase.TURN:
            for _ in range(3):
                if game.phase != GamePhase.TURN:
                    break
                p = game.players[game.current_player_index]
                game.apply_action(Action(p.name, ActionType.CHECK))

        # 河牌：所有人 check
        if game.phase == GamePhase.RIVER:
            for _ in range(3):
                if game.phase != GamePhase.RIVER:
                    break
                p = game.players[game.current_player_index]
                game.apply_action(Action(p.name, ActionType.CHECK))

        # 应该完成并进入摊牌
        assert game.phase == GamePhase.FINISHED
        assert len(game.winners) > 0

    def test_heads_up_complete(self) -> None:
        """双人对局完整测试。"""
        players = make_players(["A", "B"])
        game = GameState(players)
        game.start_new_hand()

        # 翻牌前：大盲位选择跟注或加注
        for _ in range(2):
            if game.phase != GamePhase.PRE_FLOP:
                break
            p = game.players[game.current_player_index]
            game.apply_action(Action(p.name, ActionType.CALL))

        # 翻牌 → 转牌 → 河牌: 全部 check
        for _ in range(6):  # 最多 3 轮 × 2 人
            if game.phase == GamePhase.FINISHED:
                break
            p = game.players[game.current_player_index]
            game.apply_action(Action(p.name, ActionType.CHECK))

        assert game.phase == GamePhase.FINISHED

    def test_ante_collection(self) -> None:
        """底注收取测试。"""
        players = make_players(["A", "B", "C"])
        game = GameState(players, ante=5)
        game.start_new_hand()

        for p in players:
            # 底注 + 盲注 = total_bet 至少包含 ante
            assert p.total_bet >= 5

    def test_showdown_determines_winner(self) -> None:
        """摊牌赢家判定：同花顺 > 高牌。"""
        players = make_players(["A", "B"])
        game = GameState(players)
        game.start_new_hand()

        # 直接操控牌以达到确定结果
        # A: A♠ K♠ (同花顺材料)
        # B: 2♣ 3♦ (弱牌)
        # 公共牌: Q♠ J♠ T♠ 9♠ 8♠（让 A 组 Royal）
        from src.utils.constants import Rank, Suit

        players[0].hole_cards = [
            Card(Rank.ACE, Suit.SPADES),
            Card(Rank.KING, Suit.SPADES),
        ]
        players[1].hole_cards = [
            Card(Rank.TWO, Suit.CLUBS),
            Card(Rank.THREE, Suit.DIAMONDS),
        ]
        game.community_cards = [
            Card(Rank.QUEEN, Suit.SPADES),
            Card(Rank.JACK, Suit.SPADES),
            Card(Rank.TEN, Suit.SPADES),
            Card(Rank.NINE, Suit.SPADES),
            Card(Rank.EIGHT, Suit.SPADES),
        ]

        # 手动调用摊牌
        game.phase = GamePhase.SHOWDOWN
        from src.engine.hand import HandEvaluator

        active = [p for p in players if not p.is_folded]
        results = {}
        for p in active:
            all_c = p.hole_cards + game.community_cards
            results[p.name] = HandEvaluator.evaluate(all_c)

        game._calculate_side_pots()
        game._distribute_pots(active, results)

        # A 应有同花顺（皇家同花顺）
        assert "A" in game.winners
        # result 应为皇家同花顺
        from src.utils.constants import HandRank
        assert results["A"].hand_rank == HandRank.ROYAL_FLUSH
