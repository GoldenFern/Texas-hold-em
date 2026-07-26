"""引擎规则修复的回归测试 —— 每个历史 bug 一组测试。

对应修复:
- 4.2 min_raise 跨街重置
- 4.3 零筹码玩家置 OUT,无底池资格
- 4.4 盲注即全下时自动结算,不死锁
- 4.5 引擎不接受 ALL_IN 动作类型
- 4.6 未匹配下注退款,弃牌死钱由层内赢家获得
- 4.8 固定限注每街 1 bet + 3 raise 封顶
- 免费弃牌禁止(to_call=0 时无 FOLD)
"""

from __future__ import annotations

import pytest

from src.engine.game import Action, GameState
from src.engine.player import Player
from src.utils.constants import (
    ActionType,
    BettingStructure,
    GamePhase,
    PlayerStatus,
)


def make_game(
    n: int = 3,
    chips: int = 1000,
    structure: BettingStructure = BettingStructure.NO_LIMIT,
    seed: int = 7,
    **kwargs,
) -> GameState:
    """构造标准测试牌局。"""
    players = [Player(name=f"P{i}", chips=chips, seat=i) for i in range(n)]
    return GameState(
        players, small_blind=5, big_blind=10,
        betting_structure=structure, seed=seed, **kwargs,
    )


def current(game: GameState) -> Player:
    return game.players[game.current_player_index]


def act(game: GameState, action_type: ActionType, amount: int = 0) -> bool:
    """以当前玩家身份执行动作。"""
    return game.apply_action(Action(current(game).name, action_type, amount))


def play_until_phase(game: GameState, phase: GamePhase) -> None:
    """全员跟注/过牌推进到指定阶段。"""
    while game.phase != phase:
        p = current(game)
        legal = game.get_legal_actions(p)
        if ActionType.CHECK in legal:
            act(game, ActionType.CHECK)
        else:
            act(game, ActionType.CALL)


class TestMinRaiseResetPerStreet:
    """4.2: 翻前大额加注不得抬高后续街的最小加注。"""

    def test_flop_min_raise_resets_to_big_blind(self) -> None:
        game = make_game(3)
        game.start_new_hand()
        # 翻前:UTG 加注到 200
        act(game, ActionType.RAISE, 200)
        while game.phase == GamePhase.PRE_FLOP:
            p = current(game)
            legal = game.get_legal_actions(p)
            act(game, ActionType.CALL if ActionType.CALL in legal else ActionType.CHECK)

        assert game.phase == GamePhase.FLOP
        assert game.min_raise == game.big_blind
        # 翻牌圈首个下注最小额应为 BB(10),而非翻前的加注增量
        p = current(game)
        assert game.get_min_raise_amount(p) == game.big_blind

    def test_flop_reraise_minimum_uses_flop_bet(self) -> None:
        game = make_game(3)
        game.start_new_hand()
        act(game, ActionType.RAISE, 200)
        while game.phase == GamePhase.PRE_FLOP:
            p = current(game)
            legal = game.get_legal_actions(p)
            act(game, ActionType.CALL if ActionType.CALL in legal else ActionType.CHECK)
        # 翻牌圈:先 BET 20,则最小 re-raise 到 40(20+20),与翻前 200 无关
        act(game, ActionType.BET, 20)
        p = current(game)
        assert game.get_min_raise_amount(p) == 40


class TestBustedPlayersAreOut:
    """4.3: 零筹码且不重购的玩家整手出局。"""

    def test_busted_player_marked_out_and_not_dealt(self) -> None:
        game = make_game(4, auto_rebuy=False)
        game.players[2].chips = 0
        game.start_new_hand()

        busted = game.players[2]
        assert busted.status == PlayerStatus.OUT
        assert busted.hole_cards == []

    def test_busted_player_cannot_win_pot(self) -> None:
        game = make_game(4, auto_rebuy=False)
        game.players[2].chips = 0
        game.start_new_hand()
        play_until_phase(game, GamePhase.FLOP)
        play_until_phase(game, GamePhase.TURN)
        play_until_phase(game, GamePhase.RIVER)
        while game.phase == GamePhase.RIVER:
            act(game, ActionType.CHECK)

        assert game.phase == GamePhase.FINISHED
        assert game.winners
        assert "P2" not in game.winners

    def test_rebuy_restores_player(self) -> None:
        game = make_game(3, auto_rebuy=True, rebuy_amount=500)
        game.players[1].chips = 0
        game.start_new_hand()
        assert game.players[1].chips >= 0
        assert game.players[1].status != PlayerStatus.OUT
        assert game.players[1].rebuy_count == 1


class TestAllInBlindsAutoResolve:
    """4.4: 盲注吃光筹码时牌局自动推进,不再死锁/崩溃。"""

    def test_heads_up_sb_all_in_from_blind(self) -> None:
        """单挑庄家(SB)5 筹码贴盲即全下:BB 行动后自动摊牌。"""
        game = make_game(2, auto_rebuy=False)
        game.players[1].chips = 5  # 将成为庄家/SB
        game.players[0].chips = 1000
        game.start_new_hand()

        if game.phase != GamePhase.FINISHED:
            # 行动指针必须指向 ACTIVE 玩家
            assert current(game).status == PlayerStatus.ACTIVE
            steps = 0
            while game.phase.value < GamePhase.SHOWDOWN.value:
                p = current(game)
                assert p.status == PlayerStatus.ACTIVE
                legal = game.get_legal_actions(p)
                act(game, ActionType.CHECK if ActionType.CHECK in legal
                    else ActionType.CALL)
                steps += 1
                assert steps < 20
        assert game.phase == GamePhase.FINISHED

    def test_both_blinds_all_in_immediate_runout(self) -> None:
        """两人都被盲注吃光:开手即自动发完摊牌。"""
        game = make_game(2, auto_rebuy=False)
        # _move_dealer 后 P1 为庄家/SB(≤5 即贴盲全下),P0 为 BB(≤10)
        game.players[0].chips = 8
        game.players[1].chips = 4
        game.start_new_hand()
        # 无人可行动 → start_new_hand 内直接结算
        assert game.phase == GamePhase.FINISHED
        assert game.winners
        assert sum(p.chips for p in game.players) == 12


class TestAllInActionRejected:
    """4.5: 引擎只接受 FOLD/CHECK/CALL/BET/RAISE。"""

    def test_all_in_action_type_raises(self) -> None:
        game = make_game(3)
        game.start_new_hand()
        with pytest.raises(ValueError):
            act(game, ActionType.ALL_IN, 1000)

    def test_all_in_never_in_legal_actions(self) -> None:
        game = make_game(3)
        game.start_new_hand()
        for p in game.players:
            assert ActionType.ALL_IN not in game.get_legal_actions(p)


class TestUncalledBetRefund:
    """4.6: 未匹配的下注退还;弃牌死钱由层内唯一 eligible 者赢得。"""

    def test_uncalled_raise_refunded_on_fold_out(self) -> None:
        game = make_game(3)
        game.start_new_hand()
        chips_before = {p.name: p.chips + p.total_bet for p in game.players}
        # UTG 大额加注,其余全弃
        raiser = current(game).name
        act(game, ActionType.RAISE, 500)
        act(game, ActionType.FOLD)
        act(game, ActionType.FOLD)

        assert game.phase == GamePhase.FINISHED
        winner = game.players[[p.name for p in game.players].index(raiser)]
        # 赢家净收益 = 盲注死钱(5+10),自己的 500 中未被匹配部分全额退回
        assert winner.chips == chips_before[raiser] + 15

    def test_showdown_dead_money_goes_to_layer_winner(self) -> None:
        """弃牌者死钱留在层内,由该层赢家(可能是唯一 eligible)获得。"""
        game = make_game(3, chips=300, seed=11)
        game.start_new_hand()
        # P 全下 300,下家跟注全下,第三家弃牌
        act(game, ActionType.RAISE, 300)
        act(game, ActionType.CALL)
        act(game, ActionType.FOLD)

        assert game.phase == GamePhase.FINISHED
        # 弃牌者的盲注死钱包含在分配中:总分配 = 全部投入
        total_distributed = sum(game.winners.values())
        total_committed = sum(p.total_bet for p in game.players)
        assert total_distributed == total_committed


class TestFixedLimitCap:
    """4.8: 固定限注每街 1 bet + 3 raise 封顶,加注额固定。"""

    def test_raise_cap_reached(self) -> None:
        game = make_game(3, structure=BettingStructure.FIXED_LIMIT)
        game.start_new_hand()
        # 翻前 current_bet=10(盲注算第 1 次 bet? 按惯例盲注不计,
        # 此处以引擎语义:preflop 已有 current_bet,连续 RAISE 4 次后封顶)
        raises = 0
        while True:
            p = current(game)
            legal = game.get_legal_actions(p)
            if ActionType.RAISE not in legal:
                break
            act(game, ActionType.RAISE, game.get_min_raise_amount(p))
            raises += 1
            assert raises <= 4
        assert raises == 4

    def test_fl_raise_is_fixed_increment(self) -> None:
        game = make_game(3, structure=BettingStructure.FIXED_LIMIT)
        game.start_new_hand()
        p = current(game)
        # 翻前小注单位 = BB:最小=最大=current_bet+10
        assert game.get_min_raise_amount(p) == 20
        assert game.get_max_bet(p) == 20

    def test_fl_big_bet_on_turn(self) -> None:
        game = make_game(3, structure=BettingStructure.FIXED_LIMIT)
        game.start_new_hand()
        play_until_phase(game, GamePhase.FLOP)
        play_until_phase(game, GamePhase.TURN)
        p = current(game)
        # Turn 起大注单位 = 2×BB
        assert game.get_min_raise_amount(p) == 20
        assert game.get_max_bet(p) == 20


class TestNoFreeFold:
    """免费弃牌禁止:to_call=0 时 FOLD 不合法(防无人认领死钱)。"""

    def test_fold_absent_when_check_available(self) -> None:
        game = make_game(3)
        game.start_new_hand()
        play_until_phase(game, GamePhase.FLOP)
        p = current(game)
        legal = game.get_legal_actions(p)
        assert ActionType.CHECK in legal
        assert ActionType.FOLD not in legal

    def test_free_fold_rejected(self) -> None:
        game = make_game(3)
        game.start_new_hand()
        play_until_phase(game, GamePhase.FLOP)
        with pytest.raises(ValueError):
            act(game, ActionType.FOLD)

    def test_fold_available_facing_bet(self) -> None:
        game = make_game(3)
        game.start_new_hand()
        p = current(game)
        legal = game.get_legal_actions(p)
        assert ActionType.FOLD in legal  # 翻前面对大盲必须可弃


class TestSeatIndexInvariant:
    """4.7: players 列表索引必须等于 seat。"""

    def test_mismatched_seat_rejected(self) -> None:
        players = [
            Player(name="A", chips=1000, seat=1),
            Player(name="B", chips=1000, seat=0),
        ]
        with pytest.raises(ValueError):
            GameState(players)
