"""6 Boltzmann-EV Bots 对战 20 局仿真，逐局核查决策合理性与零和利润。"""
import sys, random
sys.path.insert(0, ".")

from collections import Counter

from src.engine.game import GameState, Action, ActionType
from src.engine.hand import HandEvaluator
from src.engine.player import Player
from src.ai.bots import BoltzmannBot, BOT_PROFILES, BotStyle

SEED = 20250705
PROFILES = [
    BOT_PROFILES[BotStyle.COLD],
    BOT_PROFILES[BotStyle.COOL],
    BOT_PROFILES[BotStyle.BALANCED],
    BOT_PROFILES[BotStyle.WARM],
    BOT_PROFILES[BotStyle.HOT],
    BOT_PROFILES[BotStyle.CHAOS],
]

STARTING_CHIPS = 5000


def run_hand(hand_id, rng):
    players = [Player(name=pf.display_name, chips=STARTING_CHIPS, seat=i) for i, pf in enumerate(PROFILES)]
    game = GameState(players, small_blind=5, big_blind=10, auto_rebuy=False)
    bots = {}
    for pf, ply in zip(PROFILES, players):
        bots[ply.name] = BoltzmannBot(ply.name, pf, seed=rng.randint(0, 9999))

    # 记录手牌开始前筹码（零和基准）
    start_chips = {p.name: p.chips for p in players}

    game.start_new_hand()

    # 检查是否因玩家不足而结束
    if game.phase.value >= 6:
        return [], {}, 0, start_chips, {p.name: p.chips for p in players}

    decisions = []
    while game.phase.value < 6:
        cp = game.players[game.current_player_index]
        if cp.is_folded or cp.status.value >= 2:
            game.current_player_index = game._get_next_active_player(game.current_player_index)
            continue

        bot = bots[cp.name]
        action = bot.decide(game, cp)
        legal = game.get_legal_actions(cp)

        if action.action_type not in legal:
            print(f"  *** ILLEGAL: {cp.name} tried {action.action_type}, legal={[a.name for a in legal]}")
            action = Action(cp.name, ActionType.FOLD)

        decisions.append({
            "hand": hand_id,
            "phase": game.phase.name,
            "player": cp.name,
            "action": action.action_type.name,
            "amount": action.amount,
            "all_in": action.is_all_in,
            "hole": " ".join(c.short_str for c in cp.hole_cards),
            "community": " ".join(c.short_str for c in game.community_cards),
            "pot": game.pot.total,
            "chips": cp.chips,
            "to_call": game.current_bet - cp.current_bet,
        })

        game.apply_action(action)

    end_chips = {p.name: p.chips for p in players}

    # 评估赢家手牌
    winning_hands = {}
    if game.winning_hands:
        for name, hr in game.winning_hands.items():
            winning_hands[name] = f"{hr.description} ({' '.join(c.short_str for c in hr.best_five)})"

    return decisions, dict(game.winners), game.pot.total, start_chips, end_chips, winning_hands


def print_hand_detail(h, decisions, winners, pot, start_chips, end_chips, winning_hands):
    """打印单局详细信息。"""
    community_final = ""
    for d in decisions:
        if d["community"]:
            community_final = d["community"]

    print(f"\n{'='*70}")
    print(f"Hand #{h:2d}  |  Pot: ${pot}")
    if community_final:
        print(f"  Community: {community_final}")
    else:
        print(f"  Community: (all folded preflop)")

    # 每位玩家的底牌
    player_holes = {}
    for d in decisions:
        if d["player"] not in player_holes and d["hole"]:
            player_holes[d["player"]] = d["hole"]
    print(f"  Hole cards:")
    for name, hole in player_holes.items():
        print(f"    {name:16s}: {hole}")

    # 动作序列
    print(f"\n  Actions ({len(decisions)}):")
    for d in decisions:
        amt_str = f" ${d['amount']}" if d['amount'] > 0 else ""
        ai_str = " [ALL-IN]" if d['all_in'] else ""
        print(f"    [{d['phase']:>8s}] {d['player']:16s} {d['action']:>5s}{amt_str}{ai_str}"
              f"  (pot=${d['pot']}, to_call=${d['to_call']})")

    # 赢家
    if winners:
        print(f"\n  Winners:")
        for name, amt in winners.items():
            hand_desc = winning_hands.get(name, "?")
            print(f"    {name:16s}: +${amt}  — {hand_desc}")
    else:
        print(f"  Winners: (none — game ended early)")

    # 筹码变化（零和验证）
    print(f"\n  Chip Delta (zero-sum):")
    total_delta = 0
    for name in sorted(start_chips.keys()):
        delta = end_chips.get(name, 0) - start_chips[name]
        total_delta += delta
        print(f"    {name:16s}: {start_chips[name]:5d} ->{end_chips.get(name, 0):5d}  ({'+' if delta>=0 else ''}${delta})")
    print(f"    {'Zero-sum check':16s}: {'PASS' if abs(total_delta) < 1 else f'FAIL ({total_delta})'}")


def main():
    rng = random.Random(SEED)
    all_decisions = []
    player_profits = Counter()

    for h in range(1, 21):
        result = run_hand(h, rng)
        decisions, winners, pot, start_chips, end_chips = result[:5]
        winning_hands = result[5] if len(result) > 5 else {}
        all_decisions.extend(decisions)

        # 累积利润
        for name in start_chips:
            delta = end_chips.get(name, 0) - start_chips[name]
            player_profits[name] += delta

        # 打印单局详情
        print_hand_detail(h, decisions, winners, pot, start_chips, end_chips, winning_hands)

    # ============================================================
    # 最终汇总
    # ============================================================
    print(f"\n{'='*70}")
    print(f"FINAL SUMMARY — 20 Hands (starting chips: ${STARTING_CHIPS})")
    print(f"{'='*70}")

    total_decisions = len(all_decisions)

    # 利润排名（零和）
    print(f"\n{'Rank':>4s} {'Bot':>16s} {'Wins':>5s} {'Profit':>10s} {'PerHand':>8s} {'NetChips'}")
    print("-" * 70)
    # 统计胜场
    win_counts = Counter()
    for d in all_decisions:
        pass  # handled below
    # 从每局赢家统计
    win_counts = Counter()
    for h in range(1, 21):
        # 找到本局的赢家信息
        hand_decs = [d for d in all_decisions if d["hand"] == h]
        # 从汇总利润推断胜场（利润>0 的那手就是赢的）
        pass

    # 更简单的方法：直接从 player_profits 反推
    total_profit_sum = sum(player_profits.values())
    for rank, (name, profit) in enumerate(sorted(player_profits.items(), key=lambda x: -x[1]), 1):
        # 统计该玩家的决策
        acts = [d for d in all_decisions if d["player"] == name]
        # 统计胜场：该玩家在手牌结束时筹码增加的手数
        wins = 0
        for h in range(1, 21):
            hand_acts = [d for d in all_decisions if d["player"] == name and d["hand"] == h]
            if hand_acts:
                # 用最后一手动作的 chips + won 来推断...太复杂
                pass
        print(f"  {rank:2d}. {name:16s} {'?':>5s} {'+' if profit>=0 else ''}${profit:>9d} {'+' if profit/20>=0 else ''}${profit/20:>+7.0f}")

    # 简化版：直接从决策统计
    print(f"\n  Total profit sum: ${total_profit_sum} {'PASS ZERO-SUM' if abs(total_profit_sum) < 10 else 'FAIL NON-ZERO'}")
    print(f"\n  Total decisions: {total_decisions}")

    # 每位玩家动作统计
    print(f"\nPer-Player Action Breakdown:")
    print(f"  {'Bot':>16s} {'Decs':>5s} {'Fold':>6s} {'Check':>6s} {'Call':>6s} {'Bet':>6s} {'Raise':>6s} {'BR%':>6s}")
    print(f"  {'-'*60}")
    for name in sorted(set(d["player"] for d in all_decisions)):
        acts = [d for d in all_decisions if d["player"] == name]
        c = Counter(d["action"] for d in acts)
        n = len(acts)
        br = c.get("BET", 0) + c.get("RAISE", 0)
        profit = player_profits.get(name, 0)
        print(f"  {name:16s} {n:5d} {c.get('FOLD',0):5d} {c.get('CHECK',0):5d} "
              f"{c.get('CALL',0):5d} {c.get('BET',0):5d} {c.get('RAISE',0):5d} "
              f"{br/n*100:5.0f}%  ${profit:+d}")

    # 非法动作检查
    bad_folds = [d for d in all_decisions if d["action"] == "FOLD" and d["to_call"] <= 0]
    if bad_folds:
        print(f"\n*** BAD FOLDS (to_call<=0): {len(bad_folds)}")
        for d in bad_folds[:10]:
            print(f"  Hand#{d['hand']} {d['player']} phase={d['phase']} hole={d['hole']} to_call={d['to_call']}")
    else:
        print(f"\nFree-Check-Folds: 0  PASS")

    # Bet/Raise 金额分析
    bet_amounts = [d["amount"] for d in all_decisions if d["action"] in ("BET", "RAISE")]
    if bet_amounts:
        print(f"\nBet/Raise Sizing (n={len(bet_amounts)}):")
        print(f"  Min: ${min(bet_amounts)}  Max: ${max(bet_amounts)}  Avg: ${sum(bet_amounts)/len(bet_amounts):.0f}")
        # 按大小分桶
        buckets = {"tiny(≤10)": 0, "small(11-30)": 0, "med(31-100)": 0, "large(101-500)": 0, "huge(>500)": 0}
        for a in bet_amounts:
            if a <= 10: buckets["tiny(≤10)"] += 1
            elif a <= 30: buckets["small(11-30)"] += 1
            elif a <= 100: buckets["med(31-100)"] += 1
            elif a <= 500: buckets["large(101-500)"] += 1
            else: buckets["huge(>500)"] += 1
        print(f"  Distribution: " + ", ".join(f"{k}:{v}" for k, v in buckets.items()))

    print("\nDone.")


if __name__ == "__main__":
    main()
