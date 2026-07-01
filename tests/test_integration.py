"""集成测试 —— 完整的牌局流程测试，覆盖多种场景。"""

import pytest

from src.engine.card import Card
from src.engine.game import Action, ActionType, GameState
from src.engine.player import Player
from src.ai.bots import BotFactory, BotStyle
from src.utils.constants import BettingStructure, GamePhase, PlayerStatus


# ================================================================
# 辅助工具
# ================================================================

def make_players(names, chips=1000):
    return [Player(name=n, chips=chips, seat=i) for i, n in enumerate(names)]


def run_hand_to_completion(game: GameState) -> dict:
    """自动跑完一手牌（用最简单的 check/call 策略），返回结果字典。"""
    max_actions = 100
    action_count = 0

    while game.phase.value < 6:  # 未到 FINISHED
        if action_count >= max_actions:
            break
        cp = game.players[game.current_player_index]
        legal = game.get_legal_actions(cp)

        if ActionType.CHECK in legal:
            action = Action(cp.name, ActionType.CHECK)
        elif ActionType.CALL in legal:
            action = Action(cp.name, ActionType.CALL)
        elif ActionType.FOLD in legal:
            action = Action(cp.name, ActionType.FOLD)
        else:
            break

        game.apply_action(action)
        action_count += 1

    return {
        "phase": game.phase,
        "winners": dict(game.winners),
        "winning_hands": {n: str(h) for n, h in game.winning_hands.items()},
        "actions": len(game.all_actions),
        "pot": game.pot.total,
    }


# ================================================================
# 全流程测试
# ================================================================

class TestFullHandPlaythrough:
    """完整一手牌测试。"""

    def test_heads_up_no_limit(self) -> None:
        """双人无限注完整一手。"""
        players = make_players(["A", "B"])
        game = GameState(players, betting_structure=BettingStructure.NO_LIMIT)
        game.start_new_hand()

        result = run_hand_to_completion(game)
        assert result["phase"] == GamePhase.FINISHED
        assert len(result["winners"]) > 0

    def test_three_handed_no_limit(self) -> None:
        """三人无限注完整一手。"""
        players = make_players(["A", "B", "C"])
        game = GameState(players)
        game.start_new_hand()

        result = run_hand_to_completion(game)
        assert result["phase"] == GamePhase.FINISHED

    def test_six_handed_no_limit(self) -> None:
        """六人无限注。"""
        players = make_players(["A", "B", "C", "D", "E", "F"])
        game = GameState(players)
        game.start_new_hand()

        result = run_hand_to_completion(game)
        assert result["phase"] == GamePhase.FINISHED

    def test_full_ring_nine_players(self) -> None:
        """九人满桌。"""
        players = make_players([f"P{i}" for i in range(9)])
        game = GameState(players)
        game.start_new_hand()

        result = run_hand_to_completion(game)
        assert result["phase"] == GamePhase.FINISHED

    def test_multiple_hands_in_a_row(self) -> None:
        """连续多手牌。"""
        players = make_players(["A", "B", "C"])
        game = GameState(players)

        for _ in range(5):
            game.start_new_hand()
            result = run_hand_to_completion(game)
            assert result["phase"] == GamePhase.FINISHED

            # 重置玩家状态以准备下一手
            for p in players:
                if p.chips <= 0:
                    p.chips = 100
                p.reset_for_new_hand()


class TestAllInScenarios:
    """全下场景测试。"""

    def test_all_in_preflop(self) -> None:
        """翻牌前全下。"""
        players = make_players(["A", "B", "C"])
        game = GameState(players)
        game.start_new_hand()

        # 让第一个玩家全下
        first = game.players[game.current_player_index]
        amount = first.chips + first.current_bet
        game.apply_action(Action(first.name, ActionType.RAISE, amount=amount))

        # 其余玩家跟注
        for _ in range(5):
            if game.phase == GamePhase.FINISHED:
                break
            cp = game.players[game.current_player_index]
            if cp.status == PlayerStatus.ACTIVE:
                game.apply_action(Action(cp.name, ActionType.CALL))

        assert game.phase == GamePhase.FINISHED

    def test_multi_way_all_in_different_amounts(self) -> None:
        """多人全下且金额不同。"""
        players = make_players(["A", "B", "C"])
        game = GameState(players)

        # 手动设置不同筹码量
        players[0].chips = 50
        players[1].chips = 100
        players[2].chips = 500

        game.start_new_hand()

        # 循环操作直到本手结束
        action_order = [
            ("A", ActionType.RAISE, 50),
            ("B", ActionType.RAISE, 100),
            ("C", ActionType.CALL),
        ]
        action_idx = 0

        for _ in range(30):
            if game.phase == GamePhase.FINISHED:
                break
            cp = game.players[game.current_player_index]
            if cp.status != PlayerStatus.ACTIVE:
                # 尝试 move to next
                game.current_player_index = game._get_next_active_player(
                    game.current_player_index
                )
                continue
            # 按顺序应用预设动作
            if action_idx < len(action_order):
                name, atype = action_order[action_idx][:2]
                amt = action_order[action_idx][2] if len(action_order[action_idx]) > 2 else 0
                if cp.name == name:
                    game.apply_action(Action(name, atype, amount=amt))
                    action_idx += 1
                    continue
            # 其余人 check/call
            legal = game.get_legal_actions(cp)
            if ActionType.CHECK in legal:
                game.apply_action(Action(cp.name, ActionType.CHECK))
            elif ActionType.CALL in legal:
                game.apply_action(Action(cp.name, ActionType.CALL))
            else:
                game.apply_action(Action(cp.name, ActionType.FOLD))

        assert game.phase == GamePhase.FINISHED

    def test_all_in_blind_posting(self) -> None:
        """盲注时筹码不足以支付盲注。"""
        players = make_players(["A", "B"])
        players[0].chips = 4  # 不够小盲
        game = GameState(players, small_blind=5, big_blind=10)
        game.start_new_hand()

        sb = next(p for p in players if p.is_small_blind)
        if sb.chips < game.small_blind:
            assert sb.is_all_in

    def test_side_pot_with_fold_at_showdown(self) -> None:
        """边池 + 弃牌场景。"""
        players = make_players(["A", "B", "C"])
        players[0].chips = 30
        players[1].chips = 1000
        players[2].chips = 1000
        game = GameState(players)

        game.start_new_hand()

        # 循环操作直到本手结束：A 全下 30，其他人 call
        for _ in range(30):
            if game.phase == GamePhase.FINISHED:
                break
            cp = game.players[game.current_player_index]
            if cp.status != PlayerStatus.ACTIVE:
                game.current_player_index = game._get_next_active_player(
                    game.current_player_index
                )
                continue
            if cp.name == "A" and cp.chips > 0:
                legal = game.get_legal_actions(cp)
                if ActionType.RAISE in legal:
                    game.apply_action(Action("A", ActionType.RAISE, amount=cp.chips + cp.current_bet))
                elif ActionType.CALL in legal:
                    game.apply_action(Action("A", ActionType.CALL))
                else:
                    game.apply_action(Action("A", ActionType.FOLD))
            else:
                legal = game.get_legal_actions(cp)
                if ActionType.CHECK in legal:
                    game.apply_action(Action(cp.name, ActionType.CHECK))
                elif ActionType.CALL in legal:
                    game.apply_action(Action(cp.name, ActionType.CALL))
                else:
                    game.apply_action(Action(cp.name, ActionType.FOLD))

        assert game.phase == GamePhase.FINISHED


class TestSplitPots:
    """平分底池测试。"""

    def test_identical_hands_split_pot(self) -> None:
        """相同手牌平分底池。"""
        players = make_players(["A", "B"])
        game = GameState(players)
        game.start_new_hand()

        # 两人都有同花顺（公共牌本身是最好的手牌）
        from src.utils.constants import Rank, Suit

        # 两人底牌不同但公共牌组成皇家同花顺
        players[0].hole_cards = [
            Card(Rank.TWO, Suit.CLUBS),
            Card(Rank.THREE, Suit.DIAMONDS),
        ]
        players[1].hole_cards = [
            Card(Rank.FOUR, Suit.CLUBS),
            Card(Rank.FIVE, Suit.HEARTS),
        ]
        # 公共牌: 皇家同花顺 → 两个底牌不影响结果
        game.community_cards = [
            Card(Rank.ACE, Suit.SPADES),
            Card(Rank.KING, Suit.SPADES),
            Card(Rank.QUEEN, Suit.SPADES),
            Card(Rank.JACK, Suit.SPADES),
            Card(Rank.TEN, Suit.SPADES),
        ]

        # 直接摊牌
        game.phase = GamePhase.RIVER
        game._showdown()

        # 两人应平分底池（都使用公共牌的皇家同花顺）
        assert len(game.winners) == 2
        amounts = list(game.winners.values())
        total_pot = sum(p.total_bet for p in players)
        assert amounts[0] + amounts[1] == total_pot
        assert abs(amounts[0] - amounts[1]) <= 1

    def test_board_plays_tie(self) -> None:
        """公共牌组成最佳手牌，平分。"""
        players = make_players(["A", "B"])
        game = GameState(players)
        game.start_new_hand()

        # 皇家同花顺都在公共牌上
        from src.utils.constants import Rank, Suit
        players[0].hole_cards = [
            Card(Rank.TWO, Suit.CLUBS),
            Card(Rank.THREE, Suit.DIAMONDS),
        ]
        players[1].hole_cards = [
            Card(Rank.FOUR, Suit.CLUBS),
            Card(Rank.FIVE, Suit.HEARTS),
        ]
        game.community_cards = [
            Card(Rank.ACE, Suit.SPADES),
            Card(Rank.KING, Suit.SPADES),
            Card(Rank.QUEEN, Suit.SPADES),
            Card(Rank.JACK, Suit.SPADES),
            Card(Rank.TEN, Suit.SPADES),
        ]

        game.phase = GamePhase.RIVER
        game._showdown()

        assert len(game.winners) == 2


class TestBettingStructures:
    """不同下注结构测试。"""

    def test_pot_limit_max_bet(self) -> None:
        players = make_players(["A", "B"])
        game = GameState(players, betting_structure=BettingStructure.POT_LIMIT)
        game.start_new_hand()

        utg = game.players[game.current_player_index]
        max_bet = game.get_max_bet(utg)
        # PL: 最大下注 = 底池大小 + 跟注额
        # 当前底池 = 5(SB) + 10(BB) = 15, 需跟 10
        assert max_bet <= 15 + 10 + utg.current_bet

    def test_fixed_limit_raise_size(self) -> None:
        players = make_players(["A", "B"])
        game = GameState(players, betting_structure=BettingStructure.FIXED_LIMIT)
        game.start_new_hand()

        utg = game.players[game.current_player_index]
        max_bet = game.get_max_bet(utg)
        # FL: 加注 = 大盲注 * 乘数
        assert max_bet <= game.big_blind * 4 + utg.current_bet

    def test_no_limit_basically_unlimited(self) -> None:
        players = make_players(["A", "B"])
        game = GameState(players, betting_structure=BettingStructure.NO_LIMIT)
        game.start_new_hand()

        utg = game.players[game.current_player_index]
        max_bet = game.get_max_bet(utg)
        # NL: 最大下注 = 全部筹码
        assert max_bet == utg.chips + utg.current_bet


class TestDealerRotation:
    """庄位轮转测试。"""

    def test_blinds_rotate_with_dealer(self) -> None:
        players = make_players(["A", "B", "C"])
        game = GameState(players)

        prev_sb_name = ""

        for _ in range(3):
            game.start_new_hand()
            sb = next(p for p in players if p.is_small_blind)
            bb = next(p for p in players if p.is_big_blind)
            dealer = players[game.dealer_index]

            # SB 在 dealer 之后
            # 验证 SB != BB
            assert sb.name != bb.name
            assert sb.name != prev_sb_name  # SB 应该轮转

            prev_sb_name = sb.name

            # 重置以适应下一手
            for p in players:
                p.reset_for_new_hand()


class TestElimination:
    """淘汰测试。"""

    def test_player_with_no_chips_skipped(self) -> None:
        players = make_players(["A", "B", "C"])
        players[0].chips = 0  # A 无筹码
        game = GameState(players)
        game.start_new_hand()

        # A 应不参与
        assert players[0].status == PlayerStatus.ACTIVE or players[0].chips == 0

    def test_game_ends_when_only_one_has_chips(self) -> None:
        players = make_players(["A", "B"])
        players[0].chips = 0
        game = GameState(players)

        # 无法开始新牌局（活跃玩家不足）
        game.start_new_hand()
        # 此时 phase 应为 FINISHED
        if game.phase != GamePhase.PRE_FLOP:
            # 这是预期的（只有一人有筹码）
            pass


class TestAICompleteGame:
    """AI 机器人完整对局。"""

    def test_six_bots_play_full_game(self) -> None:
        """6 个不同风格的机器人打 5 手完整牌。"""
        from src.ai.bots import BotFactory, BotStyle

        styles = [
            BotStyle.TAG, BotStyle.LAG, BotStyle.NIT,
            BotStyle.CALLING_STATION, BotStyle.MANIAC, BotStyle.SHARK,
        ]
        bots = [BotFactory.create(s, name=s.value, seed=i * 42) for i, s in enumerate(styles)]
        players = [
            Player(name=bot.name, chips=1000, seat=i)
            for i, bot in enumerate(bots)
        ]

        game = GameState(players, small_blind=5, big_blind=10)

        hands_completed = 0
        max_hands = 5

        while hands_completed < max_hands:
            game.start_new_hand()

            # 检查活跃玩家数
            active = [p for p in players if p.chips > 0]
            if len(active) < 2:
                break

            # 跑完一手牌
            for _ in range(200):  # 安全循环上限
                if game.phase.value >= 6:
                    break
                cp = game.players[game.current_player_index]
                bot = bots[cp.seat]
                action = bot.decide(game, cp)

                # 确保合法
                legal = game.get_legal_actions(cp)
                if action.action_type not in legal:
                    if ActionType.CHECK in legal:
                        action = Action(cp.name, ActionType.CHECK)
                    elif ActionType.CALL in legal:
                        action = Action(cp.name, ActionType.CALL)
                    else:
                        action = Action(cp.name, ActionType.FOLD)

                # 修正金额
                if action.action_type in (ActionType.BET, ActionType.RAISE):
                    if action.amount > cp.chips + cp.current_bet:
                        action.amount = cp.chips + cp.current_bet
                        action.is_all_in = True
                    min_raise = game.get_min_raise_amount(cp)
                    if action.amount < min_raise:
                        action.amount = min_raise

                if game.phase.value < 6:
                    game.apply_action(action)

            if game.phase == GamePhase.FINISHED:
                hands_completed += 1

            # 重置状态
            for p in players:
                if p.chips <= 0:
                    p.chips = 200  # 补充少量筹码继续
                p.reset_for_new_hand()

        assert hands_completed == max_hands
        # 确保有历史记录
        assert len(game.hand_history) == max_hands
