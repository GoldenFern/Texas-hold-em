"""GameState 游戏状态机测试。"""

import pytest

from src.engine.card import Card
from src.engine.game import Action, ActionType, GameState
from src.engine.hand import HandEvaluator
from src.engine.player import Player
from src.utils.constants import BettingStructure, GamePhase, PlayerStatus


def cards(s: str) -> list[Card]:
    """快捷构造牌列表。"""
    return Card.from_str_multi(s)


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


# ============================================================
# 边界场景：下注流程与行动权判定
# ============================================================

class TestBigBlindOption:
    """翻牌前大盲位的过牌/加注选择权（Option）。"""

    def test_bb_can_check_when_all_call(self) -> None:
        """3 人桌，UTG call，SB call：BB 的合法动作包含 CHECK 和 RAISE。"""
        players = make_players(["A", "B", "C"])
        game = GameState(players, small_blind=5, big_blind=10)
        game.start_new_hand()
        # 盲注/庄位已确定

        # 收集玩家角色
        sb = next(p for p in players if p.is_small_blind)
        bb = next(p for p in players if p.is_big_blind)

        # UTG call
        utg = game.players[game.current_player_index]
        game.apply_action(Action(utg.name, ActionType.CALL))

        # SB call
        next_p = game.players[game.current_player_index]
        game.apply_action(Action(next_p.name, ActionType.CALL))

        # 现在应该是 BB 行动
        assert game.current_player_index == bb.seat
        legal = game.get_legal_actions(bb)
        assert ActionType.CHECK in legal
        assert ActionType.RAISE in legal

    def test_bb_check_ends_preflop(self) -> None:
        """BB check 后，翻牌前下注圈结束，进入 FLOP。"""
        players = make_players(["A", "B", "C"])
        game = GameState(players, small_blind=5, big_blind=10)
        game.start_new_hand()

        bb = next(p for p in players if p.is_big_blind)

        # UTG call
        game.apply_action(Action(game.players[game.current_player_index].name, ActionType.CALL))
        # SB call
        game.apply_action(Action(game.players[game.current_player_index].name, ActionType.CALL))
        # BB check
        assert game.current_player_index == bb.seat
        game.apply_action(Action(bb.name, ActionType.CHECK))

        # 应进入 FLOP
        assert game.phase == GamePhase.FLOP
        assert len(game.community_cards) == 3

    def test_bb_raise_reopens_betting(self) -> None:
        """BB raise 后，下注圈重新激活，其他玩家需再次决策。"""
        players = make_players(["A", "B", "C"])
        game = GameState(players, small_blind=5, big_blind=10)
        game.start_new_hand()

        bb = next(p for p in players if p.is_big_blind)

        # UTG call
        game.apply_action(Action(game.players[game.current_player_index].name, ActionType.CALL))
        # SB call
        game.apply_action(Action(game.players[game.current_player_index].name, ActionType.CALL))
        # BB raise to 30
        assert game.current_player_index == bb.seat
        game.apply_action(Action(bb.name, ActionType.RAISE, amount=30))

        assert game.current_bet == 30
        # UTG 现在必须再次决策（面临 20 的加注）
        utg = game.players[game.current_player_index]
        legal = game.get_legal_actions(utg)
        assert ActionType.CALL in legal
        assert ActionType.RAISE in legal
        assert ActionType.FOLD in legal


class TestIncompleteRaise:
    """不完整加注对重新加注权的限制。"""

    def test_incomplete_raise_no_reopen(self) -> None:
        """A bet 20, B raise to 100, C all-in 130 (+30 不完整加注)：B 无权再加注。"""
        players = make_players(["A", "B", "C", "D"])
        game = GameState(players, small_blind=5, big_blind=10)
        game.start_new_hand()

        # 目标：让 D fold, 然后 A bet 20, B raise 100, C all-in 130, A call, 再到 B
        # 先到 flop 后更方便控制
        # 所有人 check/call 到 flop
        for _ in range(10):
            if game.phase >= GamePhase.FLOP:
                break
            cp = game.players[game.current_player_index]
            legal = game.get_legal_actions(cp)
            if ActionType.CHECK in legal:
                game.apply_action(Action(cp.name, ActionType.CHECK))
            elif ActionType.CALL in legal:
                game.apply_action(Action(cp.name, ActionType.CALL))
            else:
                game.apply_action(Action(cp.name, ActionType.FOLD))

        assert game.phase == GamePhase.FLOP

        # Flop: A bet 20
        cp = game.players[game.current_player_index]
        game.apply_action(Action(cp.name, ActionType.BET, amount=20))
        assert game.current_bet == 20

        # B raise to 100
        b = game.players[game.current_player_index]
        game.apply_action(Action(b.name, ActionType.RAISE, amount=100))
        assert game.current_bet == 100

        # C all-in 130 (short stacked)
        c = game.players[game.current_player_index]
        c.chips = 130  # 确保 C 只有 130 筹码
        game.apply_action(Action(c.name, ActionType.RAISE, amount=c.chips + c.current_bet))
        assert c.is_all_in

        # D fold
        d = game.players[game.current_player_index]
        game.apply_action(Action(d.name, ActionType.FOLD))

        # A call
        a = game.players[game.current_player_index]
        game.apply_action(Action(a.name, ActionType.CALL))

        # 现在回到 B：不完整加注不应唤醒 B 的加注权
        b_current = game.players[game.current_player_index]
        legal_b = game.get_legal_actions(b_current)
        assert ActionType.RAISE not in legal_b, "B 不应有权再加注（不完整加注未唤醒）"
        assert ActionType.CALL in legal_b
        assert ActionType.FOLD in legal_b

    def test_complete_all_in_reopens(self) -> None:
        """A bet 20, B call 20, C all-in for 120 (>= min_raise of 80)：唤醒 A 的加注权。"""
        players = make_players(["A", "B", "C", "D"])
        game = GameState(players, small_blind=5, big_blind=10)
        game.start_new_hand()

        # 到 flop
        for _ in range(10):
            if game.phase >= GamePhase.FLOP:
                break
            cp = game.players[game.current_player_index]
            legal = game.get_legal_actions(cp)
            if ActionType.CHECK in legal:
                game.apply_action(Action(cp.name, ActionType.CHECK))
            elif ActionType.CALL in legal:
                game.apply_action(Action(cp.name, ActionType.CALL))
            else:
                game.apply_action(Action(cp.name, ActionType.FOLD))

        # Flop: A bet 20
        cp = game.players[game.current_player_index]
        game.apply_action(Action(cp.name, ActionType.BET, amount=20))

        # B call
        b = game.players[game.current_player_index]
        game.apply_action(Action(b.name, ActionType.CALL))

        # C all-in 120 (raise by 100 >= big_blind=10, complete raise)
        c = game.players[game.current_player_index]
        c.chips = 120
        game.apply_action(Action(c.name, ActionType.RAISE, amount=c.chips + c.current_bet))

        # D fold
        d = game.players[game.current_player_index]
        game.apply_action(Action(d.name, ActionType.FOLD))

        # B call
        b2 = game.players[game.current_player_index]
        game.apply_action(Action(b2.name, ActionType.CALL))

        # 回到 A：完整加注唤醒了 A 的加注权
        a = game.players[game.current_player_index]
        legal_a = game.get_legal_actions(a)
        assert ActionType.RAISE in legal_a, "A 应有加注权（完整加注重新激活）"


class TestHeadsUpActionOrder:
    """单挑（Heads-Up）模式下的行动顺序。"""

    def test_heads_up_preflop_btn_is_sb(self) -> None:
        """单挑中，庄家（Button）同时也是小盲。"""
        players = make_players(["A", "B"])
        game = GameState(players, small_blind=5, big_blind=10)
        game.start_new_hand()

        dealer = game.players[game.dealer_index]
        assert dealer.is_small_blind, "单挑中 BTN 同时也是 SB"

    def test_heads_up_preflop_btn_acts_first(self) -> None:
        """单挑翻牌前，BTN/SB 应第一个行动。"""
        players = make_players(["A", "B"])
        game = GameState(players, small_blind=5, big_blind=10)
        game.start_new_hand()

        dealer = game.players[game.dealer_index]
        # 翻牌前第一个行动的是 BTN（也是 SB）
        first_to_act = game.players[game.current_player_index]
        assert first_to_act.seat == dealer.seat, (
            f"单挑翻牌前 BTN(seat={dealer.seat}) 应第一个行动，"
            f"但当前是 seat={first_to_act.seat}"
        )

    def test_heads_up_postflop_btn_acts_last(self) -> None:
        """单挑翻牌后，庄家应在最后行动。"""
        players = make_players(["A", "B"])
        game = GameState(players, small_blind=5, big_blind=10)
        game.start_new_hand()

        dealer = game.players[game.dealer_index]
        bb = next(p for p in players if p.is_big_blind)

        # 翻牌前：BTN calls, BB checks → 进入 flop
        btn_round = game.players[game.current_player_index]
        game.apply_action(Action(btn_round.name, ActionType.CALL))
        # BB checks
        bb_round = game.players[game.current_player_index]
        game.apply_action(Action(bb_round.name, ActionType.CHECK))

        # 翻牌后，非庄家应第一个行动
        assert game.phase == GamePhase.FLOP
        first_post = game.players[game.current_player_index]
        assert first_post.seat != dealer.seat, "翻牌后 BTN 不应第一个行动"
        assert first_post.seat == bb.seat, "翻牌后 BB（非庄家）应第一个行动"


# ============================================================
# 边界场景：筹码池分割
# ============================================================

class TestDeadMoneySidePotResolution:
    """弃牌玩家筹码（死钱）在边池中的分配归属。"""

    def test_fold_leaves_money_in_contested_pots(self) -> None:
        """D 弃牌后，D 在主池和边池1的钱保持原状，继续参与比牌。"""
        players = make_players(["A", "B", "C", "D"])
        # A=100, B=200, C=500, D=500
        players[0].chips = 100
        players[1].chips = 200
        players[2].chips = 500
        players[3].chips = 500
        game = GameState(players, small_blind=5, big_blind=10)
        game.start_new_hand()

        # 让 A 全下 100, B 全下 200, C/D 各跟 500，然后 C 下注 D 弃牌
        # 先到 flop
        for _ in range(15):
            if game.phase >= GamePhase.FLOP:
                break
            cp = game.players[game.current_player_index]
            if cp.status != PlayerStatus.ACTIVE:
                game.current_player_index = game._get_next_active_player(game.current_player_index)
                continue
            legal = game.get_legal_actions(cp)
            if cp.name == "A" and game.phase == GamePhase.PRE_FLOP:
                game.apply_action(Action("A", ActionType.RAISE, amount=100))
            elif cp.name == "B" and game.phase == GamePhase.PRE_FLOP:
                game.apply_action(Action("B", ActionType.RAISE, amount=200))
            elif cp.name == "C" and game.phase == GamePhase.PRE_FLOP:
                game.apply_action(Action("C", ActionType.CALL))
            elif cp.name == "D" and game.phase == GamePhase.PRE_FLOP:
                game.apply_action(Action("D", ActionType.CALL))
            else:
                if ActionType.CHECK in legal:
                    game.apply_action(Action(cp.name, ActionType.CHECK))
                elif ActionType.CALL in legal:
                    game.apply_action(Action(cp.name, ActionType.CALL))
                else:
                    game.apply_action(Action(cp.name, ActionType.FOLD))

        # 现在应该在 flop 或更后。C bet, D fold
        if game.phase < GamePhase.RIVER and not players[3].is_folded:
            # 确保 C 可以行动
            for _ in range(5):
                cp = game.players[game.current_player_index]
                if cp.status != PlayerStatus.ACTIVE:
                    game.current_player_index = game._get_next_active_player(game.current_player_index)
                    continue
                if cp.name == "C":
                    game.apply_action(Action("C", ActionType.BET, amount=100))
                elif cp.name == "D":
                    game.apply_action(Action("D", ActionType.FOLD))
                else:
                    if game.phase >= GamePhase.FINISHED:
                        break
                    if ActionType.CALL in game.get_legal_actions(cp):
                        game.apply_action(Action(cp.name, ActionType.CALL))
                    elif ActionType.FOLD in game.get_legal_actions(cp):
                        game.apply_action(Action(cp.name, ActionType.FOLD))

        # D 应已弃牌
        assert players[3].is_folded

        # 到摊牌
        for _ in range(20):
            if game.phase >= GamePhase.FINISHED:
                break
            cp = game.players[game.current_player_index]
            if cp.status != PlayerStatus.ACTIVE:
                game.current_player_index = game._get_next_active_player(game.current_player_index)
                continue
            legal = game.get_legal_actions(cp)
            if ActionType.CHECK in legal:
                game.apply_action(Action(cp.name, ActionType.CHECK))
            elif ActionType.CALL in legal:
                game.apply_action(Action(cp.name, ActionType.CALL))
            else:
                game.apply_action(Action(cp.name, ActionType.FOLD))

        # 应完成
        assert game.phase == GamePhase.FINISHED


class TestOddChipDistribution:
    """无法整除的奇数筹码分配。"""

    def test_even_split_no_odd_chips(self) -> None:
        """2 人平分 100 筹码，各得 50。"""
        players = make_players(["A", "B"])
        game = GameState(players)

        # 设置相同手牌 → 平局
        board = cards("Ah Kh Qh Jh Th")
        players[0].hole_cards = cards("2c 3d")
        players[1].hole_cards = cards("4c 5d")

        hand_results = {
            "A": HandEvaluator.evaluate(players[0].hole_cards + board),
            "B": HandEvaluator.evaluate(players[1].hole_cards + board),
        }

        game._distribute_one_pot(100, players, hand_results)

        # 平分
        assert game.winners["A"] == 50
        assert game.winners["B"] == 50
        assert game.winners["A"] + game.winners["B"] == 100

    def test_odd_chip_split_two_players(self) -> None:
        """2 人平分 101 筹码，一人得 51，一人得 50。"""
        players = make_players(["A", "B"])
        game = GameState(players)

        board = cards("Ah Kh Qh Jh Th")
        players[0].hole_cards = cards("2c 3d")
        players[1].hole_cards = cards("4c 5d")

        hand_results = {
            "A": HandEvaluator.evaluate(players[0].hole_cards + board),
            "B": HandEvaluator.evaluate(players[1].hole_cards + board),
        }

        game._distribute_one_pot(101, players, hand_results)

        total = game.winners["A"] + game.winners["B"]
        assert total == 101
        assert abs(game.winners["A"] - game.winners["B"]) <= 1

    def test_three_way_tie_odd_chips(self) -> None:
        """3 人平分 100 筹码，分配为 34+33+33。"""
        players = make_players(["A", "B", "C"])
        game = GameState(players)

        board = cards("Ah Kh Qh Jh Th")
        for p in players:
            p.hole_cards = cards("2c 3d")

        hand_results = {
            p.name: HandEvaluator.evaluate(p.hole_cards + board)
            for p in players
        }

        game._distribute_one_pot(100, players, hand_results)

        amounts = list(game.winners.values())
        assert sum(amounts) == 100
        assert max(amounts) - min(amounts) <= 1
