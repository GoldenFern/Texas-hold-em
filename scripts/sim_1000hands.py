"""1000局仿真：零和利润追踪，每轮座次随机化。"""
import sys, random, time
sys.path.insert(0, ".")

from collections import Counter

from src.engine.game import GameState, Action, ActionType
from src.engine.player import Player
from src.ai.bots import BoltzmannBot, BOT_PROFILES, BotStyle

SEED = 2026
PROFILES = [
    BOT_PROFILES[BotStyle.COLD],
    BOT_PROFILES[BotStyle.COOL],
    BOT_PROFILES[BotStyle.BALANCED],
    BOT_PROFILES[BotStyle.WARM],
    BOT_PROFILES[BotStyle.HOT],
    BOT_PROFILES[BotStyle.CHAOS],
]
STARTING_CHIPS = 5000
N = 1000

rng = random.Random(SEED)
all_decisions = []
hand_wins = Counter()
player_profits = Counter()
bet_amounts_by_bot = {pf.display_name: [] for pf in PROFILES}  # 每位 bot 的下注/加注额列表

t0 = time.perf_counter()
zero_sum_checks = []  # 每局零和验证

for h in range(1, N + 1):
    order = list(range(len(PROFILES)))
    rng.shuffle(order)
    pf_shuffled = [PROFILES[i] for i in order]

    players = [Player(name=pf.display_name, chips=STARTING_CHIPS, seat=i) for i, pf in enumerate(pf_shuffled)]
    game = GameState(players, small_blind=5, big_blind=10, auto_rebuy=False)
    bots = {}
    for pf, ply in zip(pf_shuffled, players):
        bots[ply.name] = BoltzmannBot(ply.name, pf, seed=rng.randint(0, 99999))

    # 零和基准
    start_chips = {p.name: p.chips for p in players}

    game.start_new_hand()

    # 检查游戏是否因玩家不足而提前结束
    if game.phase.value >= 6:
        # 所有玩家都不够 — 记录零利润
        for p in players:
            pass  # 没有手牌可玩
        continue

    while game.phase.value < 6:
        cp = game.players[game.current_player_index]
        if cp.is_folded or cp.status.value >= 2:
            game.current_player_index = game._get_next_active_player(game.current_player_index)
            continue

        action = bots[cp.name].decide(game, cp)
        pot = game.pot.total
        to_call = game.current_bet - cp.current_bet

        if action.action_type not in game.get_legal_actions(cp):
            action = Action(cp.name, ActionType.FOLD)

        all_decisions.append({
            "action": action.action_type.name,
            "amount": action.amount,
            "all_in": action.is_all_in,
            "pot": pot,
            "player": cp.name,
            "hand": h,
            "to_call": to_call,
        })
        game.apply_action(action)

    # 零和利润：终局筹码 - 开局筹码
    winners = dict(game.winners)
    for name in winners:
        hand_wins[name] += 1

    hand_delta_sum = 0
    for p in players:
        delta = p.chips - start_chips[p.name]
        player_profits[p.name] += delta
        hand_delta_sum += delta
        # 收集下注/加注金额
        for d in all_decisions:
            if d["hand"] == h and d["player"] == p.name and d["action"] in ("BET", "RAISE"):
                bet_amounts_by_bot[p.name].append(d["amount"])

    zero_sum_checks.append(abs(hand_delta_sum))

    if h % 200 == 0:
        elapsed = time.perf_counter() - t0
        print(f"  ... {h}/{N} hands ({elapsed:.0f}s)")

elapsed = time.perf_counter() - t0
total = len(all_decisions)

print(f"\n{'='*80}")
print(f"{N}-HAND SIMULATION (random seats, zero-sum, {elapsed:.0f}s)")
print(f"Starting chips: ${STARTING_CHIPS}  |  No auto-rebuy")
print(f"{'='*80}")

# ---- 利润排名（零和） ----
print(f"\n{'Rank':>4s} {'Bot':>16s} {'Wins':>5s} {'Win%':>6s} {'Profit':>10s} {'PerHand':>8s}")
print("-" * 65)
total_profit = 0
for rank, (name, profit) in enumerate(sorted(player_profits.items(), key=lambda x: -x[1]), 1):
    w = hand_wins[name]
    wr = w / N * 100
    total_profit += profit
    print(f"  {rank:2d}. {name:16s} {w:5d} {wr:5.1f}% {'+' if profit>=0 else ''}${profit:>9d} {'+' if profit/N>=0 else ''}${profit/N:>+7.0f}")

print(f"\n  Total profit sum: ${total_profit} {'PASS ZERO-SUM' if abs(total_profit) < N else 'FAIL (expected 0)'}")

# ---- 全局动作分布 ----
counts = Counter()
ai_cnt = 0
all_bets = []
for d in all_decisions:
    counts[d["action"]] += 1
    if d["all_in"]: ai_cnt += 1
    if d["action"] in ("BET", "RAISE"): all_bets.append(d["amount"])

print(f"\nGLOBAL ({total} decisions)")
for a in ["FOLD", "CHECK", "CALL", "BET", "RAISE"]:
    c = counts.get(a, 0)
    print(f"  {a:6s}: {c:5d} ({c/total*100:.1f}%)")
if all_bets:
    bt_cnt = counts.get("BET", 0) + counts.get("RAISE", 0)
    print(f"  Avg bet/raise: ${sum(all_bets)/len(all_bets):.0f}")
    print(f"  All-in: {ai_cnt}/{bt_cnt} ({ai_cnt/bt_cnt*100:.0f}% of bet/raise)")

# ---- 每位 Bot 详细统计 ----
print(f"\n{'PER-BOT':-^80}")
print(f"  {'Bot':>16s} {'Decs':>5s} {'F%':>5s} {'K%':>5s} {'C%':>5s} {'BR%':>5s} {'AI':>4s} {'AvgBet':>7s} {'Profit'}")
print(f"  {'-'*65}")
for name in sorted(set(d["player"] for d in all_decisions)):
    acts = [d for d in all_decisions if d["player"] == name]
    n = len(acts)
    c = Counter(d["action"] for d in acts)
    br = c.get("BET", 0) + c.get("RAISE", 0)
    ai = sum(1 for d in acts if d["all_in"])
    bets = bet_amounts_by_bot.get(name, [])
    avg_bet = sum(bets) / len(bets) if bets else 0
    profit = player_profits.get(name, 0)
    print(f"  {name:16s} {n:5d} {c.get('FOLD',0)/n*100:4.0f}% {c.get('CHECK',0)/n*100:4.0f}% "
          f"{c.get('CALL',0)/n*100:4.0f}% {br/n*100:4.0f}% {ai:4d} ${avg_bet:6.0f}  ${profit:+d}")

# ---- 下注/加注金额分布 ----
print(f"\n{'BET/RAISE SIZE DISTRIBUTION':-^80}")
buckets_all = {"≤BB(10)": 0, "11-30": 0, "31-100": 0, "101-500": 0, "501-2000": 0, ">2000": 0}
for a in all_bets:
    if a <= 10: buckets_all["≤BB(10)"] += 1
    elif a <= 30: buckets_all["11-30"] += 1
    elif a <= 100: buckets_all["31-100"] += 1
    elif a <= 500: buckets_all["101-500"] += 1
    elif a <= 2000: buckets_all["501-2000"] += 1
    else: buckets_all[">2000"] += 1
print(f"  All bots (n={len(all_bets)}):")
for k, v in buckets_all.items():
    bar = "█" * (v // max(1, len(all_bets) // 40))
    print(f"    {k:>10s}: {v:5d} ({v/len(all_bets)*100:4.1f}%) {bar}")

# 每位 Bot 的金额分布
for name in sorted(bet_amounts_by_bot.keys()):
    bets = bet_amounts_by_bot[name]
    if not bets: continue
    print(f"\n  {name} (n={len(bets)}, avg=${sum(bets)/len(bets):.0f}):")
    b_bot = {"≤BB": 0, "11-30": 0, "31-100": 0, "101-500": 0, "501-2000": 0, ">2000": 0}
    for a in bets:
        if a <= 10: b_bot["≤BB"] += 1
        elif a <= 30: b_bot["11-30"] += 1
        elif a <= 100: b_bot["31-100"] += 1
        elif a <= 500: b_bot["101-500"] += 1
        elif a <= 2000: b_bot["501-2000"] += 1
        else: b_bot[">2000"] += 1
    for k, v in b_bot.items():
        if v > 0:
            bar = "█" * (v // max(1, len(bets) // 30))
            print(f"    {k:>10s}: {v:4d} ({v/len(bets)*100:4.1f}%) {bar}")

# ---- 利润趋势（每 200 手） ----
# ---- 质量检查 ----
bad = [d for d in all_decisions if d["action"] == "FOLD" and d["to_call"] <= 0]
print(f"\nFree-Check-Folds: {len(bad)}  {'PASS' if len(bad)==0 else 'FAIL'}")

max_zs = max(zero_sum_checks) if zero_sum_checks else 0
print(f"Max per-hand zero-sum deviation: ${max_zs}  {'PASS' if max_zs < 5 else 'FAIL'}")

print("Done.")
