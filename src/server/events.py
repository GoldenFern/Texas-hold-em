"""SocketIO 事件处理 —— 实时游戏通信。"""

from __future__ import annotations

import time
import threading
from threading import Event, Lock
from typing import Any, Dict, List, Optional

from flask import Flask
from flask_socketio import SocketIO

from src.engine.game import Action, ActionType, BettingStructure, GameState
from src.engine.hand import HandEvaluator
from src.engine.player import Player
from src.ai.bots import BotBase, BotFactory, BotStyle
from src.analysis.equity import calculate_hand_type_probs
from src.analysis.reporter import HandReporter
from src.server.routes import set_game_manager

# 全局 SocketIO 实例
socketio: Optional[SocketIO] = None


class GameManager:
    """管理游戏生命周期、人类玩家与 AI 机器人。"""

    def __init__(self) -> None:
        self.game: Optional[GameState] = None
        self.bots: Dict[str, BotBase] = {}
        self.human_player_name: str = ""
        self.reporter = HandReporter()
        self._lock = Lock()
        self._bot_running: bool = False
        self._bot_wake_event = Event()
        self._hand_paused: bool = False  # 手牌结束后暂停
        self._hand_continue_event = Event()
        self._replay_history: List[dict] = []  # 所有已完成手牌的完整回放数据

    def create_game(
        self,
        player_name: str,
        bot_configs: list,
        starting_chips: int = 1000,
        small_blind: int = 5,
        big_blind: int = 10,
        ante: int = 0,
        betting_structure: str = "no_limit",
    ) -> None:
        """创建新游戏。"""
        with self._lock:
            # 停止旧的 Bot 循环
            self._bot_running = False
            self._bot_wake_event.set()

            self.human_player_name = player_name
            self.bots.clear()

            # 创建玩家列表
            players = []
            # 人类玩家（座位 0）
            players.append(Player(
                name=player_name, chips=starting_chips, seat=0, is_human=True,
            ))

            # 机器人玩家
            for i, cfg in enumerate(bot_configs):
                style_name = cfg.get("style", "TAG")
                bot_name = cfg.get("name", f"Bot{i+1}")
                style = BotStyle(style_name)

                # LLM 机器人特殊处理
                if style == BotStyle.LLM or cfg.get("llm_config"):
                    llm_cfg = cfg.get("llm_config", {})
                    from src.llm.config import LLMConfig, ProviderConfig, load_config
                    try:
                        llm_config = load_config()
                    except Exception:
                        llm_config = LLMConfig()
                    if llm_cfg.get("provider"):
                        llm_config.primary.provider = llm_cfg["provider"]
                    if llm_cfg.get("model"):
                        llm_config.primary.model = llm_cfg["model"]
                    bot = BotFactory.create_llm(
                        name=bot_name,
                        provider=llm_config.primary.provider,
                        model=llm_config.primary.model,
                        seed=hash(bot_name) % 10000,
                    )
                else:
                    bot = BotFactory.create(style, name=bot_name, seed=hash(bot_name) % 10000)
                self.bots[bot_name] = bot
                players.append(Player(
                    name=bot_name, chips=starting_chips, seat=i + 1,
                ))

            bs_map = {
                "no_limit": BettingStructure.NO_LIMIT,
                "pot_limit": BettingStructure.POT_LIMIT,
                "fixed_limit": BettingStructure.FIXED_LIMIT,
            }

            self.game = GameState(
                players=players,
                small_blind=small_blind,
                big_blind=big_blind,
                ante=ante,
                betting_structure=bs_map.get(betting_structure, BettingStructure.NO_LIMIT),
            )

            # 注册事件回调
            self.game.on("hand_finished", self._on_hand_finished)

            # 开始第一手牌
            self.game.start_new_hand()

            # 广播初始状态
            self._broadcast_state()

            # 启动 Bot 循环（作为 SocketIO 后台 green thread）
            self._start_bot_loop()

    def handle_human_action(self, action_type: ActionType, amount: int = 0) -> bool:
        """处理人类玩家的动作。

        Returns:
            True 如果动作被成功处理。
        """
        with self._lock:
            if self.game is None:
                return False

            game = self.game
            player = self._get_human_player()
            if player is None or player.name != game.players[game.current_player_index].name:
                print(f"[Game] 不是人类玩家的回合（当前: {game.players[game.current_player_index].name}）")
                return False

            legal = game.get_legal_actions(player)
            if action_type not in legal:
                print(f"[Game] 非法动作 {action_type.name}, 合法: {[a.name for a in legal]}")
                return False

            # 构造金额
            if action_type in (ActionType.BET, ActionType.RAISE):
                min_raise = game.get_min_raise_amount(player)
                max_bet = game.get_max_bet(player)
                amount = max(min_raise, min(amount, max_bet))
                amount = min(amount, player.chips + player.current_bet)
            elif action_type == ActionType.CALL:
                amount = 0

            action = Action(player.name, action_type, amount)
            round_done = game.apply_action(action)

            self._broadcast_state()

            # 唤醒 Bot 循环继续处理
            self._bot_wake_event.set()

            return True

    def _start_bot_loop(self) -> None:
        """启动 Bot 循环作为 SocketIO 后台 green thread。"""
        if socketio is None:
            return
        if self._bot_running:
            self._bot_wake_event.set()
            return

        self._bot_running = True
        socketio.start_background_task(self._bot_loop)

    def _bot_loop(self) -> None:
        """Bot 主循环 —— 运行在 Eventlet green thread 中。"""
        if socketio is None:
            return
        _sleep = socketio.sleep  # Eventlet 协程式 sleep

        while self._bot_running:
            # 检查是否需要等待人类玩家
            need_wait = False
            with self._lock:
                if self.game is None:
                    break
                game = self.game
                if game.phase.value >= 6:  # FINISHED
                    need_wait = False
                else:
                    cp = game.players[game.current_player_index]
                    if cp.is_human:
                        self._emit_action_required(cp.name)
                        self._bot_wake_event.clear()
                        need_wait = True
                    else:
                        need_wait = False

            if need_wait:
                # 轮询等待（每 0.5s 检查一次），最长等 60s
                waited = 0
                while self._bot_running and not self._bot_wake_event.is_set():
                    _sleep(0.5)
                    waited += 0.5
                    if waited >= 60:
                        print("[BotLoop] 等待人类行动超时，继续检查...")
                        break
                continue

            # 处理手牌结束 → 自动开始下一手
            hand_ended = False
            game_over = False
            with self._lock:
                if self.game is None:
                    break
                game = self.game
                if game.phase.value >= 6:
                    active = [p for p in game.players if p.chips > 0]
                    if len(active) >= 2:
                        # 手牌结束 → 暂停等待用户选择
                        self._broadcast_state()
                        self._emit_hand_completed()
                        self._hand_paused = True
                        self._hand_continue_event.clear()
                        hand_ended = True
                    else:
                        self._broadcast_state()
                        self._emit_game_over()
                        game_over = True

            if game_over:
                break

            if hand_ended:
                # 在锁外轮询等待用户点击"继续"或"结束"。
                # 必须用 socketio.sleep（协程友好）而非 threading.Event.wait，
                # 否则会阻塞 eventlet 事件循环，导致 HTTP 请求（如回放接口）无法处理。
                while self._bot_running and self._hand_paused:
                    _sleep(0.5)
                if not self._bot_running:
                    break
                # 用户选择继续 → 开始下一手
                with self._lock:
                    if self.game is None:
                        break
                    self.game.start_new_hand()
                    self._broadcast_state()
                continue

            # 手牌进行中，当前是机器人 → 延迟以模拟思考时间
            _sleep(1.0)

            # 重新获取锁，确认当前玩家和机器人
            with self._lock:
                if self.game is None:
                    break
                game = self.game
                if game.phase.value >= 6:
                    continue
                cp = game.players[game.current_player_index]
                if cp.is_human:
                    continue
                bot = self.bots.get(cp.name)
                if bot is None:
                    print(f"[BotLoop] 警告: 找不到机器人 '{cp.name}'，跳过")
                    continue
                is_llm_bot = self._is_llm_bot(bot)

            # LLM 机器人决策在锁外执行（API 调用可能耗时较长）
            if is_llm_bot:
                action = bot.decide(game, cp)
            else:
                action = None  # 规则机器人在锁内决策

            # 应用动作（锁内）
            with self._lock:
                if self.game is None or not self._bot_running:
                    break
                game = self.game
                if game.phase.value >= 6:
                    continue
                cp = game.players[game.current_player_index]
                if cp.is_human:
                    continue
                bot = self.bots.get(cp.name)
                if bot is None:
                    continue

                # 非 LLM 机器人在锁内决策（快速，无网络调用）
                if not is_llm_bot or action is None:
                    action = bot.decide(game, cp)

                # 验证合法性
                legal = game.get_legal_actions(cp)
                if action.action_type not in legal:
                    if ActionType.CHECK in legal:
                        action = Action(cp.name, ActionType.CHECK)
                    elif ActionType.CALL in legal:
                        action = Action(cp.name, ActionType.CALL)
                    else:
                        action = Action(cp.name, ActionType.FOLD)

                if action.action_type in (ActionType.BET, ActionType.RAISE):
                    min_raise = game.get_min_raise_amount(cp)
                    if action.amount < min_raise:
                        action.amount = min_raise
                    max_bet = game.get_max_bet(cp)
                    if action.amount > max_bet:
                        action.amount = max_bet
                    action.amount = min(action.amount, cp.chips + cp.current_bet)

                if action.action_type == ActionType.RAISE and game.current_bet == 0:
                    action = Action(cp.name, ActionType.BET, amount=action.amount)

                game.apply_action(action)
                self._broadcast_state()

    @staticmethod
    def _is_llm_bot(bot) -> bool:
        """检查机器人是否为 LLM 驱动（需要锁外执行）。"""
        if bot is None:
            return False
        try:
            from src.llm.llm_bot import LLMBot
            return isinstance(bot, LLMBot)
        except ImportError:
            return False

    def _get_human_player(self) -> Optional[Player]:
        if self.game is None:
            return None
        for p in self.game.players:
            if p.is_human:
                return p
        return None

    def _broadcast_state(self) -> None:
        """广播游戏状态给所有客户端。"""
        if socketio is None or self.game is None:
            return
        human = self._get_human_player()
        # 人类玩家弃牌后，展示所有底牌（旁观模式）
        human_folded = human is not None and human.is_folded
        state = self.game.to_dict(
            for_player=human.name if human and not human_folded else None,
            reveal_all=human_folded,
        )
        # 添加当前可行动作
        if human and human.name == self.game.players[self.game.current_player_index].name:
            state["legal_actions"] = [
                a.name for a in self.game.get_legal_actions(human)
            ]
            state["min_raise"] = self.game.get_min_raise_amount(human)
            state["max_bet"] = self.game.get_max_bet(human)
            state["to_call"] = self.game.current_bet - human.current_bet
        else:
            state["legal_actions"] = []
        # 为人类玩家计算各牌型概率（仅当底牌可见且手牌未结束时）
        if human and human.hole_cards and human.hole_cards[0] is not None:
            hand_type_probs = calculate_hand_type_probs(
                hole_cards=human.hole_cards,
                community_cards=self.game.community_cards,
            )
            state["hand_type_probs"] = hand_type_probs
        socketio.emit("game_update", state)

    def _emit_action_required(self, player_name: str) -> None:
        """通知客户端需要行动。"""
        if socketio is None:
            return
        socketio.emit("action_required", {"player": player_name})

    def _emit_hand_completed(self) -> None:
        """通知手牌完成，等待用户选择继续或结束。"""
        if socketio is None or self.game is None:
            return
        winners = dict(self.game.winners) if self.game.winners else {}

        # 为每位玩家计算最佳 5 张牌，收集 (dict, sort_key) 对
        entries: list[tuple[dict, Any]] = []
        for p in self.game.players:
            is_folded = p.is_folded or p.is_out
            best_five: list[str] = []
            hand_description = ""
            sort_key = None
            if p.hole_cards:
                all_cards = list(p.hole_cards) + self.game.community_cards
                if len(all_cards) >= 5:
                    result = HandEvaluator.evaluate(all_cards)
                    best_five = [c.short_str for c in result.best_five]
                    hand_description = result.description
                    sort_key = result.score  # 元组可比，越小牌力越强
            player_dict = {
                "name": p.name,
                "is_folded": is_folded,
                "is_winner": p.name in winners,
                "net_profit": winners.get(p.name, 0) - p.total_bet,
                "best_five": best_five,
                "hand_description": hand_description,
            }
            entries.append((player_dict, sort_key))

        # 排序：有有效牌力的按 score 从大到小（强→弱），无牌力的放末尾
        with_hand = [(d, k) for d, k in entries if k is not None]
        without_hand = [(d, k) for d, k in entries if k is None]
        with_hand.sort(key=lambda x: x[1], reverse=True)  # score 降序 = 最强在前
        players_data = [d for d, _ in with_hand] + [d for d, _ in without_hand]

        socketio.emit("hand_completed", {
            "hand_id": self.game.hand_id,
            "players": players_data,
            "pot_total": self.game.pot.total,
        })

    def _emit_game_over(self) -> None:
        """通知游戏结束。"""
        if socketio is None:
            return
        socketio.emit("game_over", {"message": "游戏结束！"})

    def _on_hand_finished(self, history: Any) -> None:
        """牌局结束回调。"""
        if history is not None:
            self.reporter.record_hand(history)
            # 构建阶段化的回放数据
            community_cards = [str(c) for c in history.community_cards]
            # 推断每个阶段开始的动作索引（翻牌前→翻牌→转牌→河牌）
            phase_starts = [0]  # PRE_FLOP 从第 0 个动作开始
            if history.actions and getattr(history.actions[0], 'phase', None) is not None:
                # 优先使用动作上记录的 phase 判断阶段切换
                current_phase = history.actions[0].phase
                for i, a in enumerate(history.actions[1:], start=1):
                    if a.phase != current_phase:
                        phase_starts.append(i)
                        current_phase = a.phase
            else:
                # 兜底：根据社区牌数量推断（兼容旧数据）
                cc_count = 0
                for i in range(1, len(history.actions)):
                    new_cc = min(len(community_cards), cc_count + (3 if cc_count == 0 else 1))
                    if new_cc > cc_count and cc_count < len(community_cards):
                        phase_starts.append(i)
                        cc_count = new_cc
                    if cc_count >= len(community_cards):
                        break

            replay = {
                "hand_id": history.hand_id,
                "players": [
                    {
                        "name": name,
                        "hole_cards": [str(c) for c in history.hole_cards.get(name, [])],
                        "is_human": name == self.human_player_name,
                    }
                    for name in history.players
                ],
                "community_cards": community_cards,
                "actions": [
                    {
                        "player": a.player_name,
                        "action": a.action_type.name,
                        "amount": a.amount,
                        "is_all_in": a.is_all_in,
                    }
                    for a in history.actions
                ],
                "phase_boundaries": phase_starts,  # 每个阶段开始的 action 索引
                "winners": dict(history.winners),
                "winning_hands": {n: str(h) for n, h in history.winning_hands.items()},
                "pot_total": history.pot_total,
                "step_snapshots": getattr(history, 'step_snapshots', []),
            }
            self._replay_history.append(replay)

            # 限制回放历史内存（最多保留 100 手）
            if len(self._replay_history) > 100:
                self._replay_history = self._replay_history[-100:]

    def continue_game(self) -> None:
        """用户选择继续游戏 —— 开始下一手牌。"""
        self._hand_paused = False
        self._hand_continue_event.set()

    def end_game(self) -> None:
        """用户选择结束游戏。"""
        self._bot_running = False
        self._hand_paused = False
        self._hand_continue_event.set()

    def get_replay_list(self) -> list:
        """返回所有可回放的手牌摘要列表。"""
        return [
            {
                "hand_id": r["hand_id"],
                "num_actions": len(r["actions"]),
                "winners": r["winners"],
                "winning_hands": r["winning_hands"],
                "pot_total": r["pot_total"],
                "community_cards": r["community_cards"],
            }
            for r in self._replay_history[-50:]  # 最近 50 手
        ]

    def get_replay(self, hand_id: Optional[int] = None) -> Optional[dict]:
        """返回指定手牌的完整回放数据，默认返回最近一手。"""
        if not self._replay_history:
            return None
        if hand_id is not None:
            for r in self._replay_history:
                if r["hand_id"] == hand_id:
                    return r
            return None
        return self._replay_history[-1]

    def get_history(self) -> list:
        """获取牌局历史摘要（最近 20 手）。"""
        summaries = []
        for h in (self.reporter.history[-20:]):
            summaries.append(self._hand_to_summary(h))
        return [s for s in summaries if s is not None]

    def _hand_to_summary(self, h) -> dict:
        """将一手牌历史转换为摘要字典。"""
        return {
            "hand_id": h.hand_id,
            "community_cards": [str(c) for c in h.community_cards],
            "pot_total": h.pot_total,
            "winners": dict(h.winners),
            "actions": [repr(a) for a in h.actions[-10:]],
            "num_actions": len(h.actions),
        }

    def get_human_player_name(self) -> str:
        return self.human_player_name


# 全局单例
_game_manager = GameManager()
set_game_manager(_game_manager)


def register_events(app: Flask) -> None:
    """注册 SocketIO 事件处理器。"""
    global socketio
    socketio = SocketIO(app, cors_allowed_origins="*")

    @socketio.on("connect")
    def handle_connect():
        print("[SocketIO] 客户端已连接")
        # 发送当前状态
        if _game_manager.game is not None:
            _game_manager._broadcast_state()

    @socketio.on("disconnect")
    def handle_disconnect():
        print("[SocketIO] 客户端已断开")

    @socketio.on("new_game")
    def handle_new_game(data: dict):
        """创建新游戏。"""
        print(f"[SocketIO] 收到 new_game 请求, player={data.get('player_name', '?')}")
        _game_manager.create_game(
            player_name=data.get("player_name", "Player"),
            bot_configs=data.get("bots", [
                {"style": "TAG", "name": "曹操"},
                {"style": "LAG", "name": "刘备"},
                {"style": "NIT", "name": "孙权"},
                {"style": "CALLING_STATION", "name": "诸葛"},
                {"style": "MANIAC", "name": "吕布"},
            ]),
            starting_chips=data.get("starting_chips", 1000),
            small_blind=data.get("small_blind", 5),
            big_blind=data.get("big_blind", 10),
            ante=data.get("ante", 0),
            betting_structure=data.get("betting_structure", "no_limit"),
        )

    @socketio.on("continue_game")
    def handle_continue_game():
        """用户选择继续游戏。"""
        print("[SocketIO] 用户选择继续游戏")
        _game_manager.continue_game()

    @socketio.on("end_game")
    def handle_end_game():
        """用户选择结束游戏。"""
        print("[SocketIO] 用户选择结束游戏")
        _game_manager.end_game()

    @socketio.on("player_action")
    def handle_player_action(data: dict):
        """处理人类玩家的动作。"""
        action_name = data.get("action", "").lower()
        amount = data.get("amount", 0)
        print(f"[SocketIO] 收到玩家动作: {action_name} ${amount}")

        action_map = {
            "fold": ActionType.FOLD,
            "check": ActionType.CHECK,
            "call": ActionType.CALL,
            "bet": ActionType.BET,
            "raise": ActionType.RAISE,
        }

        if action_name in action_map:
            success = _game_manager.handle_human_action(action_map[action_name], amount)
            if not success:
                print(f"[SocketIO] 动作 {action_name} 处理失败（可能不是你的回合或非法动作）")
