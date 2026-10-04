"""SocketIO 事件处理 —— 实时游戏通信。"""

from __future__ import annotations

import math
import re
import time
import traceback
import zlib
from threading import Event, Lock
from typing import Any, Dict, List, Optional

from flask import Flask
from flask_socketio import SocketIO

from src.engine.game import Action, ActionType, BettingStructure, GameState
from src.engine.hand import HandEvaluator
from src.engine.player import Player
from src.ai.bots import BotFactory, BotStyle
from src.analysis.battle_analyzer import BattleAnalyzer
from src.analysis.reporter import HandReporter
from src.server.routes import set_game_manager

# 人类玩家行动超时（秒），超时自动过牌/弃牌
HUMAN_ACTION_TIMEOUT = 60.0

# 浏览器 Origin 白名单:本地 Flask :5000 与 Vite :5173。
# 用 --port/--allow-origin 启动时由 create_app(extra_origins=...) 追加。
DEFAULT_CORS_ORIGINS = [
    "http://127.0.0.1:5000", "http://localhost:5000",
    "http://127.0.0.1:5173", "http://localhost:5173",
]

# 兼容旧代码的模块级引用（register_events 时赋值；新代码用实例属性）
socketio: Optional[SocketIO] = None


class GameManager:
    """管理游戏生命周期、人类玩家与 AI 机器人。

    Args:
        sio: SocketIO 实例（构造注入，便于测试与未来多会话扩展）。
    """

    def __init__(self, sio: Optional[SocketIO] = None) -> None:
        self._socketio: Optional[SocketIO] = sio
        self.game: Optional[GameState] = None
        self.bots: Dict[str, Any] = {}
        self.human_player_name: str = ""
        self.reporter = HandReporter()
        self.analyzer = BattleAnalyzer()
        self._lock = Lock()
        self._bot_running: bool = False
        self._bot_wake_event = Event()
        self._hand_paused: bool = False  # 手牌结束后暂停
        self._hand_continue_event = Event()
        self._replay_history: List[dict] = []  # 所有已完成手牌的完整回放数据
        self._game_generation: int = 0  # 递增的游戏代际，防竞态
        self._action_sequence: int = 0  # 当前手牌动作序号（从 0 开始）
        self._decision_snapshots: List[dict] = []  # 人类行动前的可见分析
        self._latest_analysis: Optional[dict] = None
        self._latest_analysis_hand_id: int = 0
        self._latest_analysis_action_sequence: int = -1

    def attach_socketio(self, sio: SocketIO) -> None:
        """注入 SocketIO 实例。"""
        self._socketio = sio

    # ---- 通信单点（未来加 room= 只改这里） ----

    def _emit(self, event: str, payload: Optional[dict] = None) -> None:
        """向本会话的所有客户端广播事件。"""
        if self._socketio is not None:
            self._socketio.emit(event, payload if payload is not None else {})

    def _wait_event(self, event: Event, timeout: Optional[float] = None) -> bool:
        """后台线程安全地等待 Event。

        以 socketio.sleep(0.1) 粒度轮询,兼容任意 async_mode
        (阻塞式 Event.wait 会长期占用线程且无法响应循环终止)。
        超时以 time.monotonic() 截止时间为准:按循环次数累计会在
        调度/GC 停顿下产生远超预期的时间漂移。

        Returns:
            True 表示事件已置位；False 表示超时或循环被终止。
        """
        if self._socketio is None:
            return event.is_set()
        deadline = None if timeout is None else time.monotonic() + timeout
        while self._bot_running:
            if event.is_set():
                return True
            if deadline is None:
                self._socketio.sleep(0.1)
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            self._socketio.sleep(min(0.1, remaining))
        return False

    @staticmethod
    def _sanitize_name(name: str, max_len: int = 20) -> str:
        """清理玩家名称：限制长度、剔除 HTML 标签。"""
        name = re.sub(r'<[^>]*>', '', name)  # 移除 HTML 标签
        name = name.strip()[:max_len]  # 限制长度
        return name if name else "Player"

    @staticmethod
    def _coerce_int(value: Any, label: str) -> int:
        """把客户端传入的数值参数严格转换为 int。

        拒绝 bool/字符串/NaN/非整数浮点，防止 TypeError 静默崩溃
        或 NaN 比较导致的不可预期钳位。

        Raises:
            ValueError: 值不是有限整数时。
        """
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{label} 必须是数字,收到: {value!r}")
        fval = float(value)
        if not math.isfinite(fval) or not fval.is_integer():
            raise ValueError(f"{label} 必须是整数,收到: {value!r}")
        return int(fval)

    def create_game(
        self,
        player_name: str,
        bot_configs: list,
        starting_chips: int = 1000,
        small_blind: int = 5,
        big_blind: int = 10,
        ante: int = 0,
        betting_structure: str = "no_limit",
        auto_rebuy: bool = True,
    ) -> tuple:
        """创建新游戏。

        全部参数先校验、后变更状态；构建中途失败会回滚到
        无游戏的一致状态（旧循环已终止,不可复活旧局）。

        Args:
            auto_rebuy: True = 现金局,破产玩家下一手按起始筹码重购;
                False = 锦标赛,破产即出局,只剩 1 人有筹码时结束。

        Returns:
            (成功与否, 失败原因)。
        """
        # ---- 阶段 1: 参数校验与名称清理（未触碰任何可变状态） ----
        bs_map = {
            "no_limit": BettingStructure.NO_LIMIT,
            "pot_limit": BettingStructure.POT_LIMIT,
            "fixed_limit": BettingStructure.FIXED_LIMIT,
        }
        if betting_structure not in bs_map:
            return False, f"无效的下注结构: {betting_structure}"
        if not isinstance(auto_rebuy, bool):
            return False, "重购规则必须是布尔值"

        try:
            starting_chips = self._coerce_int(starting_chips, "初始筹码")
            small_blind = self._coerce_int(small_blind, "小盲注")
            big_blind = self._coerce_int(big_blind, "大盲注")
            ante = self._coerce_int(ante, "前注")
        except ValueError as e:
            return False, str(e)
        if starting_chips <= 0 or small_blind <= 0 or big_blind <= 0 or ante < 0:
            return False, "筹码与盲注必须为正数,前注不能为负"
        if big_blind < small_blind:
            return False, "大盲注不能小于小盲注"

        if not isinstance(bot_configs, list):
            return False, "机器人配置必须是列表"
        if len(bot_configs) > 8:
            return False, "机器人数量最多 8 个(含人类共 9 人)"

        player_name = self._sanitize_name(str(player_name))
        sanitized_bots: List[tuple] = []
        seen_names = {player_name}
        for i, cfg in enumerate(bot_configs):
            if not isinstance(cfg, dict):
                return False, f"机器人配置 #{i + 1} 格式错误"
            style_name = cfg.get("style", "BALANCED")
            try:
                style = BotStyle(style_name)
            except ValueError:
                return False, f"无效的机器人风格: {style_name}"
            # Bot 名与人类名同样清理（XSS 源头之一）
            bot_name = self._sanitize_name(str(cfg.get("name", f"Bot{i+1}")))
            if bot_name in seen_names:
                return False, f"玩家名称重复: {bot_name}"
            seen_names.add(bot_name)
            sanitized_bots.append((bot_name, style, cfg))

        # RLCard 集成约束:可选依赖 + 仅单挑(1 人类 + 1 Bot)
        rlcard_bots = [b for b in sanitized_bots if b[1] == BotStyle.RLCARD]
        if rlcard_bots:
            if len(sanitized_bots) != 1:
                return False, (
                    "RLCard Bot 仅支持单挑(1 人类 + 1 Bot),"
                    f"当前配置了 {len(sanitized_bots)} 个 Bot"
                )
            from src.rlcard import is_available as rlcard_available
            if not rlcard_available():
                return False, "RLCard 未安装,请先 pip install rlcard"
            eff_stack = starting_chips / big_blind
            ref_stack = 100.0
            deviation = abs(eff_stack - ref_stack) / ref_stack
            if deviation > 0.20:
                print(
                    f"[GameManager] ⚠ 有效筹码深度 {eff_stack:.0f} BB 与训练参考值 "
                    f"{ref_stack:.0f} BB 偏差 {deviation:.0%},RLCard Bot 决策质量可能下降"
                )

        with self._lock:
            # ---- 阶段 2: 终止旧循环并递增代际（此后旧局不可恢复） ----
            self._bot_running = False
            self._bot_wake_event.set()
            self._hand_continue_event.set()
            self._game_generation += 1

            # ---- 阶段 3: 构建新游戏；失败则回滚到无游戏的一致状态 ----
            try:
                players = [Player(
                    name=player_name, chips=starting_chips, seat=0, is_human=True,
                )]
                bots_new: Dict[str, Any] = {}
                for i, (bot_name, style, cfg) in enumerate(sanitized_bots):
                    seed = zlib.crc32(bot_name.encode("utf-8")) % 10000

                    # LLM 机器人特殊处理
                    if style == BotStyle.LLM or cfg.get("llm_config"):
                        llm_cfg = cfg.get("llm_config", {})
                        from src.llm.config import LLMConfig, load_config
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
                            seed=seed,
                        )
                        # 注入 ContextManager 的 reporter 引用
                        bot.context_manager._sync_opponent_stats(self.reporter)
                    else:
                        bot = BotFactory.create(
                            style, name=bot_name, seed=seed,
                            temperature=cfg.get("temperature"),
                            rlcard_config=cfg.get("rlcard_config"),
                        )
                    bots_new[bot_name] = bot
                    players.append(Player(
                        name=bot_name, chips=starting_chips, seat=i + 1,
                    ))

                # 注入共享对手模型（基于 reporter 统计的逐对手 F_max/λ 估计）
                from src.ai.opponent_model import OpponentModel
                opponent_model = OpponentModel(self.reporter)
                for bot in bots_new.values():
                    bot.set_opponent_model(opponent_model)

                game = GameState(
                    players=players,
                    small_blind=small_blind,
                    big_blind=big_blind,
                    ante=ante,
                    betting_structure=bs_map[betting_structure],
                    auto_rebuy=auto_rebuy,
                    # 重购按本桌买入补满,避免与起始筹码脱节
                    rebuy_amount=starting_chips,
                )
                game.on("hand_finished", self._on_hand_finished)
                game.start_new_hand()

                # 全部构建成功才提交新状态
                self.bots = bots_new
                self.human_player_name = player_name
                self.game = game
                self._action_sequence = 0
                self._decision_snapshots = []
                self._latest_analysis = None
                self._latest_analysis_hand_id = game.hand_id
                self._latest_analysis_action_sequence = -1
                # 新对局不继承旧回放与旧统计（战绩/对手模型重新开始）
                self._replay_history = []
                self.reporter.clear()
            except Exception as e:  # noqa: BLE001 —— 构建失败必须上报而非撕裂
                traceback.print_exc()
                self.bots = {}
                self.game = None
                self.human_player_name = ""
                self._emit("game_error", {"message": f"创建游戏失败: {e}"})
                return False, f"创建游戏失败: {e}"

            # 广播初始状态并启动 Bot 循环（作为 SocketIO 后台线程）
            self._broadcast_state()
            self._start_bot_loop()
        return True, ""

    def handle_human_action(self, action_type: ActionType, amount: Any = 0) -> tuple:
        """处理人类玩家的动作。

        Args:
            amount: 下注/加注金额。仅接受有限数字（bool 视为非法），
                非法输入直接拒绝并回报原因，绝不让异常静默丢失。

        Returns:
            (成功与否, 失败原因)。失败原因用于 action_rejected 事件。
        """
        with self._lock:
            if self.game is None:
                return False, "没有进行中的游戏"

            game = self.game
            player = self._get_human_player()
            current = game.players[game.current_player_index]
            if player is None or player.name != current.name:
                return False, f"不是你的回合（当前: {current.name}）"

            legal = game.get_legal_actions(player)
            if action_type not in legal:
                legal_names = [a.name for a in legal]
                return False, f"非法动作 {action_type.name}（合法: {legal_names}）"

            # 构造金额（BET/RAISE 先做严格类型校验再钳位）
            if action_type in (ActionType.BET, ActionType.RAISE):
                try:
                    amount = self._coerce_int(amount, "下注金额")
                except ValueError as e:
                    return False, str(e)
                min_raise = game.get_min_raise_amount(player)
                max_bet = game.get_max_bet(player)
                amount = max(min_raise, min(amount, max_bet))
                amount = min(amount, player.chips + player.current_bet)
            else:
                # 协议规定 call/check/fold 的 amount 恒为 0,忽略客户端传值
                amount = 0

            self._record_human_decision(action_type, amount, game, player)
            action = Action(player.name, action_type, amount)
            self._apply_action_and_emit(action)

            self._broadcast_state()

            # 唤醒 Bot 循环继续处理
            self._bot_wake_event.set()

            return True, ""

    def _apply_action_and_emit(self, action: Action) -> bool:
        """应用引擎动作并发出一次实时动作事件。

        所有动作入口都经过这里，包含最后一名玩家弃牌这种引擎提前返回
        的路径，避免动作事件漏发或因重复监听而触发两次动画。
        """
        if self.game is None:
            raise RuntimeError("没有进行中的游戏")
        round_done = self.game.apply_action(action)
        self._emit_action_applied(action)
        return round_done

    def _emit_action_applied(self, action: Action) -> None:
        """向前端广播引擎已经接受的动作。"""
        if self.game is None:
            return
        phase = action.phase.name if action.phase is not None else self.game.phase.name
        payload = {
            "hand_id": self.game.hand_id,
            "action_index": self._action_sequence,
            "player": action.player_name,
            "action": action.action_type.name.lower(),
            "amount": action.amount,
            "phase": phase,
            "pot_total": self.game.pot.total,
            "is_all_in": bool(action.is_all_in),
            "occurred_at": int(time.time() * 1000),
        }
        self._action_sequence += 1
        self._emit("action_applied", payload)

    def _record_human_decision(
        self,
        action_type: ActionType,
        amount: int,
        game: GameState,
        player: Player,
    ) -> None:
        """保存人类行动前可见的最小决策快照,供本手结束复盘。"""
        to_call = max(0, game.current_bet - player.current_bet)
        analysis = (
            self._latest_analysis
            if (
                self._latest_analysis is not None
                and self._latest_analysis_hand_id == game.hand_id
                and self._latest_analysis_action_sequence == self._action_sequence
            )
            else {}
        )
        odds = analysis.get("odds_ev", {})
        required = odds.get("required_equity")
        if required is None and to_call > 0:
            required = round(to_call / max(1, game.pot.total + to_call) * 100, 2)
        snapshot = {
            "action_index": self._action_sequence,
            "action": action_type.name.lower(),
            "phase": game.phase.name,
            "pot_total": game.pot.total,
            "to_call": to_call,
            "amount": amount,
            "equity": odds.get("equity"),
            "required_equity": required,
            "ev": odds.get("ev"),
        }
        self._decision_snapshots.append(snapshot)

    def _start_bot_loop(self) -> None:
        """启动 Bot 循环作为 SocketIO 后台 green thread。"""
        if self._socketio is None:
            return
        if self._bot_running:
            self._bot_wake_event.set()
            return

        self._bot_running = True
        self._socketio.start_background_task(self._bot_loop)

    def _bot_loop(self) -> None:
        """Bot 主循环 —— 运行在 SocketIO 后台线程中(async_mode=threading)。

        任何未捕获异常都会以 game_error 事件上报并保持循环存活,
        避免静默冻结整局游戏。
        """
        if self._socketio is None:
            return
        my_generation = self._game_generation

        while self._bot_running:
            if self._game_generation != my_generation:
                return
            try:
                should_exit = self._bot_loop_step()
                if should_exit:
                    return
            except Exception as e:  # noqa: BLE001 —— 循环级兜底,必须上报而非崩溃
                import traceback
                traceback.print_exc()
                self._emit("game_error", {"message": f"服务器内部错误: {e}"})
                self._socketio.sleep(1.0)

    def _bot_loop_step(self) -> bool:
        """执行循环的一轮。

        Returns:
            True 表示循环应退出。
        """
        _sleep = self._socketio.sleep

        # 阶段 1: 判断当前局面（锁内快照）
        need_wait_human = False
        wait_generation = self._game_generation  # 等待侧代际快照(防跨局误伤)
        with self._lock:
            if self.game is None:
                return True
            game = self.game
            if game.phase.value < 6:
                cp = game.players[game.current_player_index]
                if cp.is_human:
                    self._bot_wake_event.clear()
                    self._emit_action_required(cp.name)
                    need_wait_human = True

        # 阶段 2: 等人类行动（事件驱动 + 超时自动过牌/弃牌）
        if need_wait_human:
            acted = self._wait_event(self._bot_wake_event, HUMAN_ACTION_TIMEOUT)
            if not acted and self._bot_running:
                self._auto_act_for_human(wait_generation)
            return False

        # 阶段 3: 手牌结束处理
        hand_ended = False
        with self._lock:
            if self.game is None:
                return True
            game = self.game
            if game.phase.value >= 6:
                # 末手同样先发结算数据,由"继续/结束"决定下一手或收场
                self._broadcast_state()
                self._emit_hand_completed()
                self._hand_paused = True
                self._hand_continue_event.clear()
                hand_ended = True

        if hand_ended:
            # 等待用户点击"继续"或"结束"（事件驱动,无超时）
            self._wait_event(self._hand_continue_event)
            if not self._bot_running:
                return True
            with self._lock:
                if self.game is None:
                    return True
                # 现金局会给 0 筹码玩家按起始筹码重购;锦标赛不足 2 人则开局即结束
                self.game.start_new_hand()
                if self.game.phase.value >= 6:
                    self._broadcast_state()
                    self._emit_game_over()
                    return True
                self._action_sequence = 0
                self._decision_snapshots = []
                self._latest_analysis = None
                self._latest_analysis_hand_id = self.game.hand_id
                self._latest_analysis_action_sequence = -1
                self._broadcast_state()
            return False

        # 阶段 4: Bot 决策（锁内快照 → 锁外思考 → 锁内校验应用）
        with self._lock:
            if self.game is None:
                return True
            game = self.game
            if game.phase.value >= 6:
                return False
            cp = game.players[game.current_player_index]
            if cp.is_human:
                return False
            bot = self.bots.get(cp.name)
            if bot is None:
                raise RuntimeError(f"找不到机器人 '{cp.name}'")
            is_llm_bot = self._is_llm_bot(bot)
            snap_hand_id = game.hand_id
            snap_player_name = cp.name
            snap_generation = self._game_generation

        # 思考指示 + 模拟思考延迟
        self._emit("bot_thinking", {"player": snap_player_name, "is_llm": is_llm_bot})
        _sleep(0.4 if not is_llm_bot else 0.1)

        # LLM 决策在锁外执行（API 调用可能耗时较长）
        action = None
        llm_status = None
        if is_llm_bot:
            llm_before = bot.llm_decisions
            action = bot.decide(game, cp)
            llm_status = "ok" if bot.llm_decisions > llm_before else "fallback"

        # 应用动作（锁内）—— 校验代际/手牌/玩家是否仍匹配
        with self._lock:
            if self.game is None or not self._bot_running:
                return True
            if self._game_generation != snap_generation:
                return False
            game = self.game
            if game.phase.value >= 6 or game.hand_id != snap_hand_id:
                return False
            cp = game.players[game.current_player_index]
            if cp.is_human or cp.name != snap_player_name:
                return False

            # 非 LLM 机器人在锁内决策（快速,无网络调用）
            if action is None:
                action = bot.decide(game, cp)

            # 引擎是最终权威;这里只做金额精调,非法动作类型据实上报
            legal = game.get_legal_actions(cp)
            if action.action_type not in legal:
                self._emit("game_error", {
                    "message": (
                        f"机器人 {cp.name} 给出非法动作 "
                        f"{action.action_type.name},已降级处理"
                    ),
                })
                fallback = (
                    ActionType.CHECK if ActionType.CHECK in legal
                    else ActionType.CALL if ActionType.CALL in legal
                    else ActionType.FOLD
                )
                action = Action(cp.name, fallback)

            if action.action_type in (ActionType.BET, ActionType.RAISE):
                min_raise = game.get_min_raise_amount(cp)
                max_bet = game.get_max_bet(cp)
                action.amount = max(min_raise, min(action.amount, max_bet))
                action.amount = min(action.amount, cp.chips + cp.current_bet)
                if action.action_type == ActionType.RAISE and game.current_bet == 0:
                    action = Action(cp.name, ActionType.BET, amount=action.amount)
            else:
                # call/check/fold 金额恒为 0(防 Bot 返回脏值破坏 action_applied 契约)
                action.amount = 0

            self._apply_action_and_emit(action)
            if llm_status is not None:
                payload = {"player": snap_player_name, "status": llm_status}
                error_type = getattr(bot, "last_error_type", "")
                if llm_status != "ok" and error_type:
                    payload["error_type"] = error_type
                self._emit("llm_status", payload)
            self._broadcast_state()
        return False

    def _auto_act_for_human(self, generation: Optional[int] = None) -> None:
        """人类行动超时:自动过牌,不能过则弃牌。

        Args:
            generation: 发起等待时的代际快照。若已开新局（代际不匹配），
                旧循环的超时动作必须作废，否则会误伤新游戏的行动。
        """
        with self._lock:
            if generation is not None and generation != self._game_generation:
                return  # 已开新局,本次超时作废
            if self.game is None:
                return
            game = self.game
            if game.phase.value >= 6:
                return
            cp = game.players[game.current_player_index]
            if not cp.is_human:
                return
            legal = game.get_legal_actions(cp)
            if not legal:
                return
            auto = (
                ActionType.CHECK if ActionType.CHECK in legal else ActionType.FOLD
            )
            self._apply_action_and_emit(Action(cp.name, auto))
            self._emit("action_rejected", {
                "action": "timeout",
                "reason": f"行动超时,已自动{'过牌' if auto == ActionType.CHECK else '弃牌'}",
            })
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

    def _update_llm_contexts(self, history: Any) -> None:
        """手牌结束后更新 LLM Bot 的上下文。"""
        # 收集实际摊牌玩家（仅未弃牌者）
        if history and hasattr(history, "hole_cards"):
            folded_names = set()
            if hasattr(history, "actions"):
                for a in history.actions:
                    if a.action_type.name == "FOLD":
                        folded_names.add(a.player_name)
            showdown_hands: Dict[str, str] = {}
            for pname, cards in history.hole_cards.items():
                if pname not in folded_names and cards:
                    cards_str = " ".join(str(c) for c in cards)
                    if cards_str:
                        showdown_hands[pname] = cards_str

        # 本手每人实际投入 = 开局筹码 - 终局筹码 + 赢得（快照首末帧）
        spent_by_player = {}
        snapshots = getattr(history, "step_snapshots", None) if history else None
        if snapshots and len(snapshots) >= 2:
            first = {p["name"]: p["chips"] for p in snapshots[0].get("players", [])}
            last = {p["name"]: p["chips"] for p in snapshots[-1].get("players", [])}
            for pname in history.players:
                won_amt = history.winners.get(pname, 0)
                spent_by_player[pname] = (
                    first.get(pname, 0) - last.get(pname, 0) + won_amt
                )

        for name, bot in self.bots.items():
            if not self._is_llm_bot(bot):
                continue
            won = name in history.winners if history else False
            gross = history.winners.get(name, 0) if history and history.winners else 0
            # 净利润 = 赢得 - 本手投入（输家为负,模型能看到亏损了）
            profit = gross - spent_by_player.get(name, 0)

            bot.context_manager.end_hand(won=won, profit=profit, reporter=self.reporter)

            # 仅记录实际摊牌对手的手牌（不含弃牌者）
            if history and hasattr(history, "hole_cards"):
                for opponent_name, cards_str in showdown_hands.items():
                    if opponent_name != name:
                        bot.context_manager.record_showdown(opponent_name, cards_str)

    def _get_human_player(self) -> Optional[Player]:
        if self.game is None:
            return None
        for p in self.game.players:
            if p.is_human:
                return p
        return None

    def _broadcast_state(self) -> None:
        """广播游戏状态（调用方须持锁）。

        锁内只做轻量快照;蒙特卡洛分析在锁外的后台任务中计算,
        完成后携带 analysis 再次广播同一状态。
        """
        if self._socketio is None or self.game is None:
            return
        human = self._get_human_player()
        # 人类玩家弃牌后，展示所有底牌（旁观模式）
        human_folded = human is not None and human.is_folded
        state = self.game.to_dict(
            for_player=human.name if human and not human_folded else None,
            reveal_all=human_folded,
        )
        # 让客户端丢弃延迟到达的旧分析状态,动作数与 action_applied 对齐。
        state["action_index"] = self._action_sequence
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

        # 锁内抓取分析所需的数值快照,锁外计算（避免持锁跑 MC 或竞态读活对象）
        analysis_args = None
        if human and human.hole_cards:
            active_opponents = sum(
                1 for p in self.game.players
                if p.is_in_hand and p.name != human.name
            )
            analysis_args = {
                "hole_cards": list(human.hole_cards),
                "community_cards": list(self.game.community_cards),
                "active_opponent_count": active_opponents,
                "pot_total": self.game.pot.total,
                "to_call": max(0, self.game.current_bet - human.current_bet),
                "player_chips": human.chips,
                "dead_money": sum(
                    p.total_bet for p in self.game.players if p.is_folded
                ),
                "sunk_cost": human.total_bet,
            }

        self._emit("game_update", state)

        if analysis_args is not None:
            analysis_hand_id = self.game.hand_id
            analysis_action_sequence = self._action_sequence
            self._socketio.start_background_task(
                self._emit_analysis_update, state, analysis_args,
                self._game_generation, analysis_hand_id, analysis_action_sequence,
            )

    def _emit_analysis_update(
        self,
        state: dict,
        analysis_args: dict,
        generation: int,
        hand_id: int,
        action_sequence: int,
    ) -> None:
        """锁外计算分析并广播带 analysis 的状态（后台任务）。"""
        analysis = self.analyzer.analyze_snapshot(**analysis_args)
        if generation != self._game_generation:
            return  # 游戏已重建，丢弃过期分析
        if self.game is None or self.game.hand_id != hand_id:
            return
        if self._action_sequence != action_sequence:
            return  # 动作已推进,避免旧分析覆盖当前决策
        self._latest_analysis = analysis
        self._latest_analysis_hand_id = hand_id
        self._latest_analysis_action_sequence = action_sequence
        state = dict(state)
        state["analysis"] = analysis
        self._emit("game_update", state)

    def _emit_action_required(self, player_name: str) -> None:
        """通知客户端需要行动。"""
        hand_id = self.game.hand_id if self.game is not None else 0
        deadline_at = int((time.time() + HUMAN_ACTION_TIMEOUT) * 1000)
        self._emit("action_required", {
            "hand_id": hand_id,
            "player": player_name,
            "timeout_seconds": HUMAN_ACTION_TIMEOUT,
            "deadline_at": deadline_at,
        })

    def _emit_hand_completed(self) -> None:
        """通知手牌完成，等待用户选择继续或结束。"""
        if self.game is None:
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
                else:
                    # 不足 5 张牌（翻牌前/翻牌圈结束），直接展示已有底牌
                    best_five = [c.short_str for c in p.hole_cards]
                    hand_description = "未摊牌"
                    sort_key = None
            player_dict = {
                "name": p.name,
                "is_folded": is_folded,
                "is_winner": (winners.get(p.name, 0) - p.total_bet) > 0,
                "net_profit": winners.get(p.name, 0) - p.total_bet,
                "best_five": best_five,
                "hand_description": hand_description,
                "hole_cards": [c.short_str for c in p.hole_cards] if p.hole_cards else [],
            }
            entries.append((player_dict, sort_key))

        # 排序：有有效牌力的按 score 从大到小（强→弱），无牌力的放末尾
        with_hand = [(d, k) for d, k in entries if k is not None]
        without_hand = [(d, k) for d, k in entries if k is None]
        with_hand.sort(key=lambda x: x[1], reverse=True)  # score 降序 = 最强在前
        players_data = [d for d, _ in with_hand] + [d for d, _ in without_hand]

        payload = {
            "hand_id": self.game.hand_id,
            "players": players_data,
            "pot_total": self.game.pot.total,
        }
        review = self._build_decision_review()
        if review is not None:
            payload["decision_review"] = review
        self._emit("hand_completed", payload)

    def _build_decision_review(self) -> Optional[dict]:
        """从人类行动前快照选择一条有价值的过程复盘。"""
        if not self._decision_snapshots:
            return None
        candidates = [
            item for item in self._decision_snapshots
            if item.get("ev") is not None or item.get("equity") is not None
        ]
        item = candidates[-1] if candidates else self._decision_snapshots[-1]
        action = str(item.get("action", "check"))
        phase = str(item.get("phase", "PRE_FLOP"))
        ev = item.get("ev")
        equity = item.get("equity")
        required = item.get("required_equity")

        verdict = "neutral"
        title = "记录一次决策"
        detail = "这次复盘缺少完整模拟结果，先关注行动前的信息和下注尺度。"
        if isinstance(ev, (int, float)):
            if action in {"call", "bet", "raise"} and ev < 0:
                verdict = "review"
                title = "复盘这次投入"
                detail = "行动前估计的期望值为负，下一次可以先比较所需权益与自己的权益。"
            elif action == "fold" and ev > 0:
                verdict = "review"
                title = "复盘这次弃牌"
                detail = "行动前估计仍有正期望，下一次可以检查是否过早放弃了可实现的权益。"
            else:
                verdict = "good_process"
                title = "过程判断稳定"
                detail = "这次行动与行动前的权益和底池价格一致，继续记录过程质量。"

        review = {
            "action_index": int(item.get("action_index", 0)),
            "action": action,
            "phase": phase,
            "verdict": verdict,
            "title": title,
            "detail": detail,
        }
        if equity is not None:
            review["equity"] = equity
        if required is not None:
            review["required_equity"] = required
        if ev is not None:
            review["ev"] = ev
        return review

    def _emit_game_over(self) -> None:
        """通知游戏结束。"""
        self._emit("game_over", {"message": "游戏结束！"})

    def _on_hand_finished(self, history: Any) -> None:
        """牌局结束回调。"""
        if history is not None:
            self.reporter.record_hand(history)

            # 更新 LLM Bot 的上下文（手牌结果 + 对手摊牌数据）
            self._update_llm_contexts(history)
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
            review = self._build_decision_review()
            if review is not None:
                replay["decision_review"] = review
            self._replay_history.append(replay)

            # 限制回放历史内存（最多保留 100 手）
            if len(self._replay_history) > 100:
                self._replay_history = self._replay_history[-100:]

    def continue_game(self) -> None:
        """用户选择继续游戏 —— 开始下一手牌。"""
        self._hand_paused = False
        self._hand_continue_event.set()

    def end_game(self) -> None:
        """用户选择结束游戏:停循环、清游戏状态、通知客户端。"""
        with self._lock:
            self._bot_running = False
            self._hand_paused = False
            self._hand_continue_event.set()
            self._bot_wake_event.set()
            self.game = None
        self._emit_game_over()

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

    def get_llm_context(self) -> Optional[dict]:
        """获取所有 LLM Bot 的最近调用上下文（供前端调试面板）。

        Returns:
            {"contexts": {bot 名: 上下文}, **最近一个上下文} 或 None。
        """
        contexts: Dict[str, dict] = {}
        for name, bot in self.bots.items():
            if self._is_llm_bot(bot):
                ctx = getattr(bot, 'last_llm_context', None)
                if ctx:
                    contexts[name] = ctx
        if not contexts:
            return None
        latest = list(contexts.values())[-1]
        return {**latest, "contexts": contexts}

    def get_human_player_name(self) -> str:
        return self.human_player_name


# ================================================================
# 会话注册表 —— 当前单会话("default"),未来多桌只需增键
# ================================================================

class GameSessionRegistry:
    """会话 ID → GameManager 的注册表。"""

    def __init__(self) -> None:
        self._sessions: Dict[str, GameManager] = {}

    def get_or_create(self, session_id: str = "default") -> GameManager:
        """获取或创建指定会话的 GameManager。"""
        if session_id not in self._sessions:
            self._sessions[session_id] = GameManager()
        return self._sessions[session_id]

    def get(self, session_id: str = "default") -> Optional[GameManager]:
        return self._sessions.get(session_id)


registry = GameSessionRegistry()
_game_manager = registry.get_or_create("default")
set_game_manager(_game_manager)


def register_events(
    app: Flask, extra_origins: Optional[List[str]] = None,
) -> None:
    """注册 SocketIO 事件处理器。

    Args:
        app: Flask 应用。
        extra_origins: 额外允许的浏览器 Origin(如 --port/局域网地址)。
    """
    global socketio
    # 显式固定 threading 模式：代码使用原生 threading.Lock/Event,
    # 与真实线程语义一致。eventlet 已弃用,且未 monkey_patch 时
    # green thread + 原生锁会冻结整个事件循环。
    # CORS 白名单:默认本地 Flask :5000 与 Vite :5173,额外来源由调用方追加
    origins = list(DEFAULT_CORS_ORIGINS)
    for origin in extra_origins or []:
        if origin and origin not in origins:
            origins.append(origin)
    socketio = SocketIO(app, async_mode="threading", cors_allowed_origins=origins)
    _game_manager.attach_socketio(socketio)

    @socketio.on("connect")
    def handle_connect():
        print("[SocketIO] 客户端已连接")
        # 仅当有进行中的游戏时同步状态（避免 end_game 后推送陈旧状态）
        if _game_manager.game is not None:
            with _game_manager._lock:
                if _game_manager.game is not None:
                    _game_manager._broadcast_state()

    @socketio.on("disconnect")
    def handle_disconnect():
        print("[SocketIO] 客户端已断开")

    @socketio.on("new_game")
    def handle_new_game(data: dict):
        """创建新游戏。任何异常都回报客户端,严禁静默吞。"""
        data = data if isinstance(data, dict) else {}
        print(f"[SocketIO] 收到 new_game 请求, player={data.get('player_name', '?')}")
        try:
            ok, reason = _game_manager.create_game(
                player_name=data.get("player_name", "Player"),
                bot_configs=data.get("bots", [
                    {"style": "COOL", "name": "偏冷"},
                    {"style": "WARM", "name": "偏热"},
                    {"style": "COLD", "name": "极冷"},
                    {"style": "HOT", "name": "炎热"},
                    {"style": "CHAOS", "name": "混沌"},
                ]),
                starting_chips=data.get("starting_chips", 1000),
                small_blind=data.get("small_blind", 5),
                big_blind=data.get("big_blind", 10),
                ante=data.get("ante", 0),
                betting_structure=data.get("betting_structure", "no_limit"),
                auto_rebuy=data.get("auto_rebuy", True),
            )
        except Exception as e:  # noqa: BLE001 —— 入口级兜底
            traceback.print_exc()
            ok, reason = False, f"创建游戏失败: {e}"
        if not ok:
            _game_manager._emit("action_rejected", {
                "action": "new_game", "reason": reason,
            })

    @socketio.on("continue_game")
    def handle_continue_game():
        """用户选择继续游戏。"""
        _game_manager.continue_game()

    @socketio.on("end_game")
    def handle_end_game():
        """用户选择结束游戏。"""
        _game_manager.end_game()

    @socketio.on("player_action")
    def handle_player_action(data: dict):
        """处理人类玩家的动作。任何异常都回报客户端,严禁静默吞。"""
        data = data if isinstance(data, dict) else {}
        action_name = str(data.get("action", "")).lower()
        amount = data.get("amount", 0)

        action_map = {
            "fold": ActionType.FOLD,
            "check": ActionType.CHECK,
            "call": ActionType.CALL,
            "bet": ActionType.BET,
            "raise": ActionType.RAISE,
        }

        if action_name not in action_map:
            _game_manager._emit("action_rejected", {
                "action": action_name, "reason": f"未知动作: {action_name}",
            })
            return
        try:
            ok, reason = _game_manager.handle_human_action(
                action_map[action_name], amount,
            )
        except Exception as e:  # noqa: BLE001 —— 入口级兜底(畸形输入/引擎异常)
            traceback.print_exc()
            ok, reason = False, f"服务器内部错误: {e}"
        if not ok:
            _game_manager._emit("action_rejected", {
                "action": action_name, "reason": reason,
            })
