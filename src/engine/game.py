"""德州扑克游戏状态机 —— 完整的牌局流程管理。

支持：
- NL / PL / FL 三种下注结构
- 2–9 人桌
- 盲注、底注
- 全下边池
- 摊牌与赢家判定
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from src.engine.card import Cards
from src.engine.deck import Deck
from src.engine.hand import HandEvaluator, HandResult
from src.engine.player import Player
from src.engine.pot import Pot
from src.utils.constants import (
    ActionType,
    BettingStructure,
    GamePhase,
    PlayerStatus,
)


@dataclass
class Action:
    """玩家的一个动作。"""

    player_name: str
    action_type: ActionType
    amount: int = 0  # 下注/加注金额（对于 fold/check 为 0）
    is_all_in: bool = False
    phase: "GamePhase | None" = None  # 该动作发生时的游戏阶段

    def __repr__(self) -> str:
        parts = [f"{self.player_name}: {self.action_type.name}"]
        if self.amount > 0:
            parts.append(f"${self.amount}")
        if self.is_all_in:
            parts.append("[ALL-IN]")
        return " ".join(parts)


@dataclass
class HandHistory:
    """一局牌的历史记录。"""

    hand_id: int
    players: List[str]
    hole_cards: Dict[str, Cards]
    community_cards: Cards
    actions: List[Action]
    winners: Dict[str, int]  # player_name → amount_won
    winning_hands: Dict[str, HandResult]
    pot_total: int
    step_snapshots: List[dict] = field(default_factory=list)  # 每一步的中间状态快照


class GameState:
    """德州扑克游戏状态机。

    管理完整的一局牌：从发牌到摊牌。
    """

    def __init__(
        self,
        players: List[Player],
        small_blind: int = 5,
        big_blind: int = 10,
        ante: int = 0,
        betting_structure: BettingStructure = BettingStructure.NO_LIMIT,
        auto_rebuy: bool = True,
        rebuy_amount: int = 1000,
        seed: Optional[int] = None,
    ) -> None:
        if len(players) < 2:
            raise ValueError("至少需要 2 名玩家")
        if len(players) > 9:
            raise ValueError("最多支持 9 名玩家")
        # 不变量：players 列表索引即座位号（引擎内部所有轮转逻辑依赖此约定）
        for i, p in enumerate(players):
            if p.seat != i:
                raise ValueError(
                    f"玩家 {p.name} 的 seat ({p.seat}) 必须等于列表索引 ({i})"
                )

        self.players = players
        self.small_blind = small_blind
        self.big_blind = big_blind
        self.ante = ante
        self.betting_structure = betting_structure
        self.auto_rebuy = auto_rebuy
        self.rebuy_amount = rebuy_amount

        self.deck = Deck(seed)
        self.pot = Pot()
        self.community_cards: Cards = []
        self.phase = GamePhase.WAITING
        self.dealer_index: int = 0
        self.current_player_index: int = 0
        self.hand_id: int = 0
        self.current_bet: int = 0  # 本轮当前需要跟注的金额
        self.last_raise: int = 0  # 最后一次加注的增量
        self.min_raise: int = big_blind  # 最小加注额
        self.actions_this_round: List[Action] = []
        self.all_actions: List[Action] = []
        self.raises_this_round: int = 0  # 本街已发生的 bet/raise 次数（FL 封顶用）
        self._last_raise_was_incomplete: bool = False  # 不完整加注标记
        self._step_snapshots: List[dict] = []  # 回放用：每步的中间状态
        self.hand_history: List[HandHistory] = []
        self.winners: Dict[str, int] = {}
        self.winning_hands: Dict[str, HandResult] = {}

        # 事件回调（供前端使用）
        self._event_callbacks: Dict[str, List[Callable[..., None]]] = {}

    # ================================================================
    # 事件系统
    # ================================================================

    def on(self, event: str, callback: Callable[..., None]) -> None:
        """注册事件回调。"""
        self._event_callbacks.setdefault(event, []).append(callback)

    def _emit(self, event: str, *args: Any, **kwargs: Any) -> None:
        """触发事件。"""
        for cb in self._event_callbacks.get(event, []):
            cb(*args, **kwargs)

    # ================================================================
    # 牌局流程
    # ================================================================

    def start_new_hand(self) -> None:
        """开始新一局。"""
        self.hand_id += 1
        self.deck.reset()
        self.deck.shuffle()
        self.pot.reset()
        self.community_cards = []
        self.current_bet = 0
        self.last_raise = 0
        self.min_raise = self.big_blind
        self.actions_this_round = []
        self.all_actions = []
        self.raises_this_round = 0
        self._last_raise_was_incomplete = False
        self._step_snapshots = []  # 回放快照重置
        self.winners = {}
        self.winning_hands = {}

        # 重置玩家手牌状态
        for p in self.players:
            p.reset_for_new_hand()

        # 自动重购：本金输光的玩家重新获得 rebuy_amount 筹码
        if self.auto_rebuy:
            for p in self.players:
                if p.chips == 0:
                    p.rebuy(self.rebuy_amount)

        # 无筹码且未重购的玩家本手出局：不发牌、无任何底池资格
        for p in self.players:
            if p.chips == 0:
                p.status = PlayerStatus.OUT

        # 有效玩家不足则牌局无法继续
        active_players = [p for p in self.players if p.chips > 0]
        if len(active_players) < 2:
            self.phase = GamePhase.FINISHED
            return

        # 记录初始快照（盲注/底注之前，step 0）
        self._step_snapshots.append(self._capture_snapshot())

        # 移动庄位
        self._move_dealer()

        # 收底注
        if self.ante > 0:
            self._collect_antes()

        # 收盲注
        self._post_blinds()

        # 发底牌
        self._deal_hole_cards()

        self.phase = GamePhase.PRE_FLOP
        self._emit("hand_started", self.hand_id)
        self._emit("phase_changed", self.phase)

        # 盲注/底注即全下可能导致无人需要行动：直接结算（自动 runout）
        if self._is_round_complete():
            self._finish_round()
            return

        # 确定第一个行动的玩家（UTG）；若其已全下则顺延到下一位可行动者
        first = self._get_first_to_act()
        if self.players[first].status != PlayerStatus.ACTIVE:
            first = self._get_next_active_player(first)
        self.current_player_index = first

    def _move_dealer(self) -> None:
        """庄位顺时针移动。"""
        active_players = [p for p in self.players if p.chips > 0]
        if not active_players:
            return

        # 找到当前庄家
        for p in self.players:
            p.is_dealer = False

        self.dealer_index = (self.dealer_index + 1) % len(self.players)
        while self.players[self.dealer_index].chips == 0:
            self.dealer_index = (self.dealer_index + 1) % len(self.players)

        self.players[self.dealer_index].is_dealer = True

    def _collect_antes(self) -> None:
        """收取所有玩家的底注。"""
        for p in self.players:
            if p.chips > 0:
                actual = min(self.ante, p.chips)
                p.chips -= actual
                p.total_bet += actual
                self.pot.add_bet(actual)
                if p.chips == 0:
                    p.status = PlayerStatus.ALL_IN

    def _post_blinds(self) -> None:
        """收取小盲和大盲。单挑时庄家（Button）同时也是小盲。"""
        active_count = sum(1 for p in self.players if p.chips > 0)
        if active_count == 2:
            # 单挑规则：庄家同时是小盲
            sb_player = self.players[self.dealer_index]
            bb_player = self._get_player_after(self.dealer_index)
        else:
            sb_player = self._get_player_after(self.dealer_index)
            bb_player = self._get_player_after(sb_player.seat)

        # 小盲
        sb_player.is_small_blind = True
        sb_player.post_blind(self.small_blind)
        self.pot.add_bet(sb_player.current_bet)

        # 大盲
        bb_player.is_big_blind = True
        bb_player.post_blind(self.big_blind)
        self.pot.add_bet(bb_player.current_bet)

        self.current_bet = self.big_blind

    def _deal_hole_cards(self) -> None:
        """给每位未弃牌/未淘汰的玩家发两张底牌。"""
        for p in self.players:
            if p.status not in (PlayerStatus.FOLDED, PlayerStatus.OUT):
                p.hole_cards = self.deck.deal(2)

    def _get_first_to_act(self) -> int:
        """确定翻牌前第一个行动的玩家（UTG）。"""
        active_count = sum(1 for p in self.players if p.chips > 0)
        if active_count == 2:
            # 单挑：庄家（同时也是小盲）先行动
            return self.dealer_index
        # 翻牌前：大盲注之后第一位
        bb_idx = self._get_player_after(
            self._get_player_after(self.dealer_index).seat
        ).seat
        utg = self._get_player_after(bb_idx)
        return utg.seat

    # ================================================================
    # 下注轮管理
    # ================================================================

    def advance_phase(self) -> None:
        """进入下一个游戏阶段。"""
        # 重置本轮下注
        for p in self.players:
            if not p.is_folded:
                p.current_bet = 0
        self.current_bet = 0
        self.last_raise = 0
        self.min_raise = self.big_blind  # 最小加注增量每街重置为大盲
        self.actions_this_round = []
        self.raises_this_round = 0
        self._last_raise_was_incomplete = False

        if self.phase == GamePhase.PRE_FLOP:
            self._deal_community(3)  # Flop
            self.phase = GamePhase.FLOP
        elif self.phase == GamePhase.FLOP:
            self._deal_community(1)  # Turn
            self.phase = GamePhase.TURN
        elif self.phase == GamePhase.TURN:
            self._deal_community(1)  # River
            self.phase = GamePhase.RIVER
        elif self.phase == GamePhase.RIVER:
            self._showdown()
            return

        # 确定第一个行动的玩家（庄家之后的第一位活跃玩家）
        # 全员 all-in 的 runout 阶段没有可行动玩家，指针保持不动
        if any(p.status == PlayerStatus.ACTIVE for p in self.players):
            self.current_player_index = self._get_next_active_player(
                self.dealer_index
            )
        self._emit("phase_changed", self.phase)

    def _deal_community(self, n: int) -> None:
        """发公共牌。烧一张牌再发 n 张。"""
        self.deck.deal_one()  # 烧牌
        self.community_cards.extend(self.deck.deal(n))

    def _showdown(self) -> None:
        """摊牌并判定赢家。"""
        self.phase = GamePhase.SHOWDOWN

        active_players = [
            p for p in self.players
            if p.status in (PlayerStatus.ACTIVE, PlayerStatus.ALL_IN)
        ]

        if len(active_players) == 0:
            self.phase = GamePhase.FINISHED
            return

        # 评估每位活跃玩家的手牌
        hand_results: Dict[str, HandResult] = {}
        for p in active_players:
            all_cards = p.hole_cards + self.community_cards
            hand_results[p.name] = HandEvaluator.evaluate(all_cards)

        # 计算底池分层（退款直接由 Pot 应用到玩家）
        self.pot.collect_bets(self.players)

        # 分配底池给赢家
        self._distribute_pots(active_players, hand_results)

        # 记录终局快照（底池分配后）
        self._step_snapshots.append(self._capture_snapshot())

        self._emit("showdown", {
            "community": [str(c) for c in self.community_cards],
            "hands": {name: str(hr) for name, hr in hand_results.items()},
            "winners": dict(self.winners),
        })

        self.phase = GamePhase.FINISHED

        # 记录历史
        history = HandHistory(
            hand_id=self.hand_id,
            players=[p.name for p in self.players],
            hole_cards={p.name: list(p.hole_cards) for p in self.players},
            community_cards=list(self.community_cards),
            actions=list(self.all_actions),
            winners=dict(self.winners),
            winning_hands=dict(self.winning_hands),
            pot_total=self.pot.total,
            step_snapshots=list(self._step_snapshots),
        )
        self.hand_history.append(history)
        self._emit("hand_finished", history)

    def _distribute_pots(
        self,
        active_players: List[Player],
        hand_results: Dict[str, HandResult],
    ) -> None:
        """按边池层级分配筹码给赢家。hands_won 每手牌只递增一次。"""
        self.winners = {}
        self.winning_hands = {}

        for pot_layer in self.pot.pots:
            eligible = [
                p for p in active_players
                if p.name in pot_layer.eligible_players
            ]
            self._distribute_one_pot(pot_layer.amount, eligible, hand_results)

        # 每位赢家的 hands_won 只递增一次（每手牌，非每池）
        for name in self.winners:
            p = self._find_player(name)
            if p:
                p.hands_won += 1

    def _distribute_one_pot(
        self,
        amount: int,
        eligible: List[Player],
        hand_results: Dict[str, HandResult],
    ) -> None:
        """分配一个底池给最佳手牌玩家（可平分）。"""
        if amount == 0 or not eligible:
            return

        # 找出最佳手牌
        best_result = max(
            (hand_results[p.name] for p in eligible),
            key=lambda hr: hr.score,
        )

        winners = [
            p for p in eligible
            if hand_results[p.name].score == best_result.score
        ]

        split = amount // len(winners)
        remainder = amount - split * len(winners)

        for i, winner in enumerate(winners):
            extra = 1 if i < remainder else 0
            win_amount = split + extra
            winner.win_pot(win_amount)
            self.winners[winner.name] = self.winners.get(winner.name, 0) + win_amount
            self.winning_hands[winner.name] = hand_results[winner.name]

    # ================================================================
    # 玩家动作处理
    # ================================================================

    def get_legal_actions(self, player: Player) -> List[ActionType]:
        """获取指定玩家的合法动作列表。"""
        if player.status != PlayerStatus.ACTIVE:
            return []

        legal: List[ActionType] = []

        # 固定限注：每街 1 bet + 3 raise 封顶后不再允许加注
        fl_capped = (
            self.betting_structure == BettingStructure.FIXED_LIMIT
            and self.raises_this_round >= 4
        )

        to_call = self.current_bet - player.current_bet
        if to_call == 0:
            legal.append(ActionType.CHECK)
            # 可以主动下注
            if not fl_capped:
                if self.current_bet == 0:
                    legal.append(ActionType.BET)
                else:
                    legal.append(ActionType.RAISE)
        else:
            # 免费弃牌（to_call == 0 时弃牌）被禁止：会造成无人认领的死钱
            legal.append(ActionType.FOLD)
            legal.append(ActionType.CALL)
            # 只有筹码超过跟注额时才允许加注（否则只能全下跟注）
            if player.chips > to_call and not fl_capped:
                # 不完整加注规则：如果玩家本轮已行动过且最后加注不完整，无权再加注
                if self._last_raise_was_incomplete:
                    has_acted = any(
                        a.player_name == player.name for a in self.actions_this_round
                    )
                    if not has_acted:
                        legal.append(ActionType.RAISE)
                else:
                    legal.append(ActionType.RAISE)

        return legal

    def get_max_bet(self, player: Player) -> int:
        """获取玩家最大可下注额。"""
        if self.betting_structure == BettingStructure.NO_LIMIT:
            return player.chips + player.current_bet
        elif self.betting_structure == BettingStructure.POT_LIMIT:
            to_call = self.current_bet - player.current_bet
            pot_after_call = self.pot.total + to_call
            return min(
                player.chips + player.current_bet,
                pot_after_call + player.current_bet + to_call,
            )
        else:  # FIXED_LIMIT
            return min(
                player.chips + player.current_bet,
                self.current_bet + self._fl_bet_size(),
            )

    def get_min_raise_amount(self, player: Player) -> int:
        """获取最小加注/下注总额。"""
        if self.betting_structure == BettingStructure.FIXED_LIMIT:
            # 固定限注：加注额固定为当前街的下注单位
            return min(
                self.current_bet + self._fl_bet_size(),
                player.chips + player.current_bet,
            )
        if self.current_bet == 0:
            return self.big_blind
        min_total = self.current_bet + max(self.min_raise, self.last_raise)
        return min(min_total, player.chips + player.current_bet)

    def _fl_bet_size(self) -> int:
        """固定限注当前街的下注单位（Turn 起为大注）。"""
        return (
            self.big_blind * 2
            if self.phase >= GamePhase.TURN
            else self.big_blind
        )

    def apply_action(self, action: Action) -> bool:
        """应用玩家的动作。引擎层作为最终权威校验合法性。

        Returns:
            True 如果该轮下注结束（进入下一阶段或摊牌）。

        Raises:
            ValueError: 动作非法（非当前玩家回合、无效动作、金额不合法等）。
        """
        player = self._find_player(action.player_name)
        if player is None:
            raise ValueError(f"找不到玩家: {action.player_name}")

        # ---- 合法性校验（引擎层最终权威） ----

        # 0. 游戏必须处于可行动阶段
        if self.phase.value >= GamePhase.SHOWDOWN.value:
            raise ValueError(
                f"游戏已结束（阶段: {self.phase.name}），无法执行动作"
            )

        # 1. 必须轮到该玩家
        current_player = self.players[self.current_player_index]
        if player.name != current_player.name:
            raise ValueError(
                f"不是 {player.name} 的回合（当前: {current_player.name}）"
            )

        # 2. 玩家必须处于 ACTIVE 状态
        if player.status != PlayerStatus.ACTIVE:
            raise ValueError(
                f"{player.name} 无法行动（状态: {player.status.name}）"
            )

        # 3. 动作类型必须在合法列表中
        legal = self.get_legal_actions(player)
        if action.action_type not in legal:
            raise ValueError(
                f"非法动作 {action.action_type.name}，"
                f"合法: {[a.name for a in legal]}"
            )

        to_call = self.current_bet - player.current_bet

        # 4. 金额合法性校验
        if action.action_type in (ActionType.BET, ActionType.RAISE):
            amount = action.amount
            # 金额不能低于玩家已有下注（防止"降注"攻击）
            if amount < player.current_bet:
                raise ValueError(
                    f"下注额 ({amount}) 不能低于已有下注 ({player.current_bet})"
                )
            # 金额不能低于最小加注（除非全下）
            min_allowed = self.get_min_raise_amount(player)
            is_all_in_bet = amount >= player.chips + player.current_bet
            if amount < min_allowed and not is_all_in_bet:
                raise ValueError(
                    f"加注额 ({amount}) 低于最低加注 ({min_allowed})"
                )
            # 金额不能超过最大限额
            max_allowed = self.get_max_bet(player)
            if amount > max_allowed:
                raise ValueError(
                    f"下注额 ({amount}) 超过最大限额 ({max_allowed})"
                )
        elif action.action_type == ActionType.CHECK:
            if to_call > 0:
                raise ValueError(f"需要跟注 {to_call}，不能过牌")
        elif action.action_type == ActionType.CALL:
            if to_call <= 0:
                raise ValueError("无需跟注，应使用 CHECK")

        # ---- 执行动作 ----

        self.all_actions.append(action)
        self.actions_this_round.append(action)
        action.phase = self.phase  # 记录动作发生时的游戏阶段

        if action.action_type == ActionType.FOLD:
            player.fold()
            self._emit("player_folded", player.name)

            # 检查是否只剩一名在局玩家
            active_count = sum(1 for p in self.players if p.is_in_hand)
            if active_count == 1:
                self._handle_last_player_wins()
                return True

        elif action.action_type == ActionType.CHECK:
            pass  # 过牌不改变任何状态

        elif action.action_type == ActionType.CALL:
            added = player.call(self.current_bet)
            self.pot.add_bet(added)
            if player.is_all_in:
                action.is_all_in = True

        elif action.action_type in (ActionType.BET, ActionType.RAISE):
            amount = action.amount
            # amount 已经过校验，确保 >= player.current_bet
            added = amount - player.current_bet

            if added >= player.chips:
                # 全下
                added = player.chips
                amount = player.current_bet + added
                action.is_all_in = True

            player.chips -= added
            player.current_bet = amount
            player.total_bet += added
            self.pot.add_bet(added)

            if player.chips == 0:
                player.status = PlayerStatus.ALL_IN
                action.is_all_in = True

            # ---- 更新下注轮状态 ----
            if amount > self.current_bet:
                raise_amount = amount - self.current_bet
                if self.current_bet > 0 and raise_amount < self.min_raise:
                    # 不完整加注（短码 all-in）：不更新 last_raise/min_raise
                    self._last_raise_was_incomplete = True
                    self.current_bet = amount
                else:
                    # 完整加注
                    self._last_raise_was_incomplete = False
                    self.last_raise = raise_amount
                    self.min_raise = max(self.last_raise, self.big_blind)
                    self.current_bet = amount
                    self.raises_this_round += 1
            else:
                # amount <= current_bet：短码全下，未达到当前下注
                if self.current_bet > 0:
                    self._last_raise_was_incomplete = True
                # current_bet / last_raise / min_raise 保持不变

            self._emit("bet_raised", player.name, amount)

        self._emit("player_action", action)

        # 捕获快照（行动执行后的状态）
        self._step_snapshots.append(self._capture_snapshot())

        # 检查是否所有活跃玩家都已行动且下注平齐
        if self._is_round_complete():
            self._finish_round()
            return True

        # 移到下一个玩家
        self.current_player_index = self._get_next_active_player(
            self.current_player_index
        )
        return False

    def _finish_round(self) -> None:
        """当前下注轮结束。"""
        if self.phase == GamePhase.RIVER:
            self._showdown()
        elif self.phase in (GamePhase.PRE_FLOP, GamePhase.FLOP, GamePhase.TURN):
            # 检查是否只剩一人
            active = [p for p in self.players if p.status == PlayerStatus.ACTIVE]
            all_in_players = [p for p in self.players if p.is_all_in]
            if len(active) <= 1 and len(active) + len(all_in_players) <= 1:
                self._handle_last_player_wins()
                return
            # 所有剩余玩家都全下：快速发完公共牌直接到摊牌
            if len(active) == 0 and len(all_in_players) > 0:
                while self.phase != GamePhase.RIVER:
                    self.advance_phase()
                self._showdown()
                return
            # 只有一位可行动玩家，其余已全下：无人可匹配新下注，直接 runout
            if len(active) == 1 and len(all_in_players) > 0:
                while self.phase != GamePhase.RIVER:
                    self.advance_phase()
                self._showdown()
                return
            self.advance_phase()

    def _handle_last_player_wins(self) -> None:
        """当只剩一名玩家未弃牌时，该玩家赢得底池。"""
        self.winners = {}
        self.winning_hands = {}
        winner = next(
            (p for p in self.players if p.is_in_hand),
            None,
        )
        if winner is None:
            return

        total_pot = sum(p.total_bet for p in self.players)
        # 归还多余筹码：赢家只需匹配其他玩家的最大下注额
        max_other_bet = max(
            (p.total_bet for p in self.players if p.name != winner.name),
            default=0,
        )
        if winner.total_bet > max_other_bet:
            refund = winner.total_bet - max_other_bet
            self.pot.refund_uncalled(winner, refund)
            total_pot -= refund

        winner.win_pot(total_pot)
        winner.hands_won += 1
        self.winners[winner.name] = total_pot

        # 记录终局快照（退款和底池分配后）
        self._step_snapshots.append(self._capture_snapshot())

        # 评估赢家手牌
        if winner.hole_cards:
            all_cards = winner.hole_cards + self.community_cards
            if len(all_cards) >= 5:
                self.winning_hands[winner.name] = HandEvaluator.evaluate(all_cards)

        self.phase = GamePhase.FINISHED

        # 记录历史
        history = HandHistory(
            hand_id=self.hand_id,
            players=[p.name for p in self.players],
            hole_cards={p.name: list(p.hole_cards) for p in self.players},
            community_cards=list(self.community_cards),
            actions=list(self.all_actions),
            winners=dict(self.winners),
            winning_hands=dict(self.winning_hands),
            pot_total=total_pot,
            step_snapshots=list(self._step_snapshots),
        )
        self.hand_history.append(history)
        self._emit("hand_finished", history)

    def _is_round_complete(self) -> bool:
        """检查当前下注轮是否完成。"""
        active_players = [
            p for p in self.players
            if p.status == PlayerStatus.ACTIVE
        ]

        # 没有活跃玩家 = 轮完成
        if len(active_players) == 0:
            return True

        # 只有 1 个活跃玩家：需要他已经行动过且下注额平齐
        # （防止有人在后面加注后，他还没回应就被判定为轮完成）
        if len(active_players) == 1:
            p = active_players[0]
            acted_this_round = {a.player_name for a in self.actions_this_round}
            return p.current_bet == self.current_bet and p.name in acted_this_round

        # 所有活跃玩家的 current_bet 必须等于当前下注额
        for p in active_players:
            if p.current_bet != self.current_bet:
                return False

        # 每个活跃玩家都必须在本轮行动过
        acted_this_round = {a.player_name for a in self.actions_this_round}
        for p in active_players:
            if p.name not in acted_this_round:
                return False

        return True

    # ================================================================
    # 辅助方法
    # ================================================================

    def _find_player(self, name: str) -> Optional[Player]:
        for p in self.players:
            if p.name == name:
                return p
        return None

    def _get_player_after(self, seat: int) -> Player:
        """获取指定座位之后的第一位有筹码的玩家。"""
        for i in range(1, len(self.players) + 1):
            idx = (seat + i) % len(self.players)
            p = self.players[idx]
            if p.chips > 0:
                return p
        raise RuntimeError("没有找到活跃玩家")

    def _get_next_active_player(self, from_seat: int) -> int:
        """获取 from_seat 之后第一位可行动的玩家。

        Raises:
            RuntimeError: 场上没有 ACTIVE 玩家（调用方逻辑错误）。
        """
        for i in range(1, len(self.players) + 1):
            idx = (from_seat + i) % len(self.players)
            p = self.players[idx]
            if p.status == PlayerStatus.ACTIVE:
                return idx
        raise RuntimeError("场上没有可行动的玩家")

    def get_players_in_action_order(self) -> List[Player]:
        """按行动顺序返回玩家列表。"""
        if self.phase == GamePhase.WAITING:
            return list(self.players)

        result: List[Player] = []
        start = self.current_player_index
        for i in range(len(self.players)):
            idx = (start + i) % len(self.players)
            p = self.players[idx]
            if p.status == PlayerStatus.ACTIVE:
                result.append(p)
        return result

    # ================================================================
    # 获取可序列化的状态快照（供前端）
    # ================================================================

    def _capture_snapshot(self) -> dict:
        """捕获当前游戏状态的快照，用于回放渐进式渲染。"""
        return {
            "pot_total": self.pot.total,
            "phase": self.phase.name,
            "community_cards": [str(c) for c in self.community_cards],
            "players": [
                {
                    "name": p.name,
                    "seat": p.seat,
                    "chips": p.chips,
                    "status": p.status.name,
                    "current_bet": p.current_bet,
                    "total_bet": p.total_bet,
                    "rebuy_count": p.rebuy_count,
                    "is_dealer": p.is_dealer,
                    "is_small_blind": p.is_small_blind,
                    "is_big_blind": p.is_big_blind,
                    "hole_cards": [str(c) for c in p.hole_cards],
                }
                for p in self.players
            ],
        }

    def to_dict(self, for_player: Optional[str] = None, reveal_all: bool = False) -> dict:
        """将游戏状态序列化为字典（供 API 返回）。

        Args:
            for_player: 指定查看状态的玩家，其底牌可见。
            reveal_all: 为 True 时显示所有玩家的底牌（旁观/弃牌后）。
        """
        return {
            "hand_id": self.hand_id,
            "phase": self.phase.name,
            "community_cards": [str(c) for c in self.community_cards],
            "pot_total": self.pot.total,
            "current_bet": self.current_bet,
            "dealer_index": self.dealer_index,
            "current_player_index": self.current_player_index,
            "betting_structure": self.betting_structure.value,
            "small_blind": self.small_blind,
            "big_blind": self.big_blind,
            "ante": self.ante,
            "players": [
                self._player_to_dict(p, show_hole=(reveal_all or for_player == p.name))
                for p in self.players
            ],
            "winners": dict(self.winners),
        }

    def _player_to_dict(self, player: Player, show_hole: bool = False) -> dict:
        d = {
            "name": player.name,
            "chips": player.chips,
            "seat": player.seat,
            "status": player.status.name,
            "current_bet": player.current_bet,
            "total_bet": player.total_bet,
            "is_dealer": player.is_dealer,
            "is_small_blind": player.is_small_blind,
            "is_big_blind": player.is_big_blind,
            "is_human": player.is_human,
            "hands_won": player.hands_won,
            "total_won": player.total_won,
            "rebuy_count": player.rebuy_count,
        }
        if show_hole or (self.phase == GamePhase.FINISHED and not player.is_folded):
            d["hole_cards"] = [str(c) for c in player.hole_cards]
        else:
            d["hole_cards"] = ["??", "??"] if player.status not in (
                PlayerStatus.FOLDED, PlayerStatus.OUT
            ) else []
        return d
