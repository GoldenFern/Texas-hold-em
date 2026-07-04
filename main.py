"""Texas Hold'em Poker — 主入口。

启动方式:
    python main.py              # 启动 Web 服务器（默认 localhost:5000）
    python main.py --cli        # 命令行模式（AI vs AI 自动对战）
    python main.py --test       # 运行全部测试
"""

from __future__ import annotations

import argparse
import sys


def run_server(host: str = "0.0.0.0", port: int = 5000, debug: bool = False) -> None:
    """启动 Flask + SocketIO Web 服务器。"""
    from src.llm.client import configure_llm_traffic_logging

    configure_llm_traffic_logging(enabled=True)
    from src.server.app import create_app

    app = create_app()

    # create_app() 中 register_events() 会初始化全局 socketio，通过模块引用获取
    import src.server.events as evt

    print(f"\n{'='*50}")
    print(f"  Texas Hold'em Poker Server")
    print(f"  访问: http://localhost:{port}")
    print(f"{'='*50}\n")
    evt.socketio.run(app, host=host, port=port, debug=debug, allow_unsafe_werkzeug=True)


def run_cli(num_hands: int = 10) -> None:
    """命令行模式：AI 机器人自动对战 N 手牌。"""
    from src.llm.client import configure_llm_traffic_logging

    configure_llm_traffic_logging(enabled=True)
    from src.engine.game import Action, ActionType, GameState
    from src.engine.player import Player
    from src.ai.bots import BotFactory, BotStyle

    styles = [
        BotStyle.TAG, BotStyle.LAG, BotStyle.NIT,
        BotStyle.CALLING_STATION, BotStyle.MANIAC, BotStyle.SHARK,
    ]
    bots = [BotFactory.create(s, name=s.value, seed=i * 100) for i, s in enumerate(styles)]
    players = [
        Player(name=bot.name, chips=1000, seat=i)
        for i, bot in enumerate(bots)
    ]

    game = GameState(players, small_blind=5, big_blind=10)
    print(f"CLI 模式：{len(players)} 个 AI 机器人自动对战 {num_hands} 手牌\n")

    for hand_idx in range(num_hands):
        game.start_new_hand()
        print(f"\n--- Hand #{game.hand_id} ---")

        while game.phase.value < 5:  # 未到摊牌
            cp = game.players[game.current_player_index]
            bot = bots[cp.seat]
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

            game.apply_action(action)

        # 显示结果
        if game.winners:
            for name, amount in game.winners.items():
                winning_hand = game.winning_hands.get(name)
                hand_desc = winning_hand.description if winning_hand else "?"
                print(f"  Winner: {name} (+${amount}) — {hand_desc}")

        # 重置玩家状态（不补充筹码，保持真实筹码量）
        for p in players:
            p.reset_for_new_hand()

    print("\n=== 对战结束 ===")
    for p in sorted(players, key=lambda x: x.chips, reverse=True):
        print(f"  {p.name}: ${p.chips} ({p.hands_won} wins)")


def run_tests() -> None:
    """运行全部测试。"""
    import subprocess
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-v", "--tb=short"],
        capture_output=False,
    )
    sys.exit(result.returncode)


def main() -> None:
    parser = argparse.ArgumentParser(description="Texas Hold'em Poker")
    parser.add_argument("--cli", action="store_true", help="命令行 AI 对战模式")
    parser.add_argument("--test", action="store_true", help="运行全部测试")
    parser.add_argument("--hands", type=int, default=10, help="CLI 模式下的手牌数")
    parser.add_argument("--host", default="0.0.0.0", help="服务器主机")
    parser.add_argument("--port", type=int, default=5000, help="服务器端口")
    parser.add_argument("--debug", action="store_true", help="调试模式")

    args = parser.parse_args()

    if args.test:
        run_tests()
    elif args.cli:
        run_cli(num_hands=args.hands)
    else:
        run_server(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
