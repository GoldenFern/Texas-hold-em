"""10,000局仿真：零和利润，每轮座次随机化，使用优化后的 bet sizing。"""
import sys, random, time
sys.path.insert(0, ".")

from collections import Counter

from src.engine.game import GameState, Action, ActionType
from src.engine.player import Player
from src.ai.bots import BoltzmannBot, BOT_PROFILES, BotStyle

SEED = 20260710
PROFILES = [
    BOT_PROFILES[BotStyle.COLD],
    BOT_PROFILES[BotStyle.COOL],
    BOT_PROFILES[BotStyle.BALANCED],
    BOT_PROFILES[BotStyle.WARM],
    BOT_PROFILES[BotStyle.HOT],
    BOT_PROFILES[BotStyle.CHAOS],
]
STARTING_CHIPS = 10000  # 更多筹码，减少 bust-out
N = 10000

rng = random.Random(SEED)
all_decisions = []
hand_wins = Counter()
player_profits = Counter()
bet_amounts_by_bot = {pf.display_name: [] for pf in PROFILES}
profit_history = {pf.display_name: [] for pf in PROFILES}  # 每 500 手记录一次

t0 = time.perf_counter()
zero_sum_checks = []

for h in range(1, N + 1):
    order = list(range(len(PROFILES)))
    rng.shuffle(order)
    pf_shuffled = [PROFILES[i] for i in order]

    players = [Player(name=pf.display_name, chips=STARTING_CHIPS, seat=i) for i, pf in enumerate(pf_shuffled)]
    game = GameState(players, small_blind=5, big_blind=10, auto_rebuy=False)
    bots = {}
    for pf, ply in zip(pf_shuffled, players):
        bots[ply.name] = BoltzmannBot(ply.name, pf, seed=rng.randint(0, 99999), postflop_sims=50)

    start_chips = {p.name: p.chips for p in players}
    game.start_new_hand()

    if game.phase.value >= 6:
        continue

    hand_decisions = []
    while game.phase.value < 6:
        cp = game.players[game.current_player_index]
        if cp.is_folded or cp.status.value >= 2:
            game.current_player_index = game._get_next_active_player(game.current_player_index)
            continue

        action = bots[cp.name].decide(game, cp)
        if action.action_type not in game.get_legal_actions(cp):
            action = Action(cp.name, ActionType.FOLD)

        hand_decisions.append({
            "action": action.action_type.name,
            "amount": action.amount,
            "all_in": action.is_all_in,
            "pot": game.pot.total,
            "player": cp.name,
            "hand": h,
            "to_call": game.current_bet - cp.current_bet,
        })
        game.apply_action(action)

    all_decisions.extend(hand_decisions)

    for name, amount in game.winners.items():
        hand_wins[name] += 1

    hand_delta_sum = 0
    for p in players:
        delta = p.chips - start_chips[p.name]
        player_profits[p.name] += delta
        hand_delta_sum += delta
        for d in hand_decisions:
            if d["player"] == p.name and d["action"] in ("BET", "RAISE"):
                bet_amounts_by_bot[p.name].append(d["amount"])

    zero_sum_checks.append(abs(hand_delta_sum))

    # 每 500 手打印进度 + 记录利润快照
    if h % 500 == 0:
        elapsed = time.perf_counter() - t0
        eta = elapsed / h * (N - h)
        print(f"  [{h:5d}/{N}] {elapsed:.0f}s elapsed, ~{eta:.0f}s remaining", flush=True)
        for pf in PROFILES:
            profit_history[pf.display_name].append(player_profits.get(pf.display_name, 0))

elapsed = time.perf_counter() - t0

# ================================================================
# 报告
# ================================================================
print(f"\n{'='*90}")
print(f"10,000-HAND SIMULATION")
print(f"Starting: ${STARTING_CHIPS}  |  No rebuy  |  Strategy: separated k=0.6 kbl=0.65 cap=0.75")
print(f"Total time: {elapsed:.0f}s ({elapsed/60:.1f} min)")
print(f"{'='*90}")

total = len(all_decisions)

# ---- 利润排名 ----
print(f"\n{'Rank':>4s} {'Bot':>16s} {'Wins':>6s} {'Win%':>6s} {'Profit':>12s} {'PerHand':>8s} {'NetChips'}")
print("-" * 80)
total_profit = 0
results = []
for pf in PROFILES:
    name = pf.display_name
    p = player_profits.get(name, 0)
    w = hand_wins.get(name, 0)
    results.append((name, w, p))
    total_profit += p

for rank, (name, w, p) in enumerate(sorted(results, key=lambda x: -x[2]), 1):
    wr = w / N * 100
    final_chips = STARTING_CHIPS + p
    print(f"  {rank:2d}. {name:16s} {w:6d} {wr:5.1f}%  {'+' if p>=0 else ''}${p:>11d}  {'+' if p/N>=0 else ''}${p/N:>+7.0f}  ${final_chips}")

print(f"\n  Total profit sum: ${total_profit}  {'ZERO-SUM OK' if abs(total_profit) < N*2 else 'DRIFT!'}")

# ---- 全局动作 ----
counts = Counter()
ai_cnt = 0
all_bets = []
for d in all_decisions:
    counts[d["action"]] += 1
    if d["all_in"]: ai_cnt += 1
    if d["action"] in ("BET", "RAISE"): all_bets.append(d["amount"])

print(f"\n{'GLOBAL':-^80}")
print(f"  Total decisions: {total}")
for a in ["FOLD", "CHECK", "CALL", "BET", "RAISE"]:
    c = counts.get(a, 0)
    print(f"  {a:6s}: {c:6d} ({c/total*100:5.1f}%)")
if all_bets:
    bt_cnt = counts.get("BET", 0) + counts.get("RAISE", 0)
    print(f"  Avg bet/raise: ${sum(all_bets)/len(all_bets):.0f} ({sum(all_bets)/len(all_bets)/10:.0f} BB)")
    print(f"  All-in rate: {ai_cnt}/{bt_cnt} ({ai_cnt/bt_cnt*100:.0f}%)")

# ---- 每位 Bot ----
print(f"\n{'PER-BOT':-^80}")
print(f"  {'Bot':>16s} {'Decs':>6s} {'F%':>5s} {'K%':>5s} {'C%':>5s} {'BR%':>5s} {'AI':>5s} {'AvgBet':>7s}  {'Profit'}")
print(f"  {'-'*65}")
for name in sorted(set(d["player"] for d in all_decisions)):
    acts = [d for d in all_decisions if d["player"] == name]
    n = len(acts)
    c = Counter(d["action"] for d in acts)
    br = c.get("BET", 0) + c.get("RAISE", 0)
    ai = sum(1 for d in acts if d["all_in"])
    bets = bet_amounts_by_bot.get(name, [])
    avg_bet = sum(bets) / len(bets) if bets else 0
    p = player_profits.get(name, 0)
    print(f"  {name:16s} {n:6d} {c.get('FOLD',0)/n*100:4.0f}% {c.get('CHECK',0)/n*100:4.0f}% "
          f"{c.get('CALL',0)/n*100:4.0f}% {br/n*100:4.0f}% {ai:5d} ${avg_bet:6.0f}  {'+' if p>=0 else ''}${p}")

# ---- 下注额分布 ----
print(f"\n{'BET SIZE DISTRIBUTION':-^80}")
buckets = {"≤BB": 0, "2-3BB": 0, "3-10BB": 0, "10-50BB": 0, "50-200BB": 0, ">200BB": 0}
for a in all_bets:
    bb = a / 10
    if bb <= 1: buckets["≤BB"] += 1
    elif bb <= 3: buckets["2-3BB"] += 1
    elif bb <= 10: buckets["3-10BB"] += 1
    elif bb <= 50: buckets["10-50BB"] += 1
    elif bb <= 200: buckets["50-200BB"] += 1
    else: buckets[">200BB"] += 1
print(f"  All (n={len(all_bets)}, avg={sum(all_bets)/len(all_bets)/10:.0f} BB):")
for k, v in buckets.items():
    pct = v / len(all_bets) * 100 if all_bets else 0
    bar = "█" * max(1, int(pct))
    print(f"    {k:>10s}: {v:6d} ({pct:4.1f}%) {bar}")

# ---- 利润趋势 ----
print(f"\n{'PROFIT TREND':-^80}")
print(f"  {'Checkpoint':>8s}", end="")
for pf in PROFILES:
    print(f"  {pf.display_name:>12s}", end="")
print()
for i, cp in enumerate(range(500, N + 1, 500)):
    print(f"  {cp:8d}", end="")
    for pf in PROFILES:
        hist = profit_history[pf.display_name]
        val = hist[i] if i < len(hist) else 0
        print(f"  {'+' if val>=0 else ''}${val:>11d}", end="")
    print()

# ---- 质量检查 ----
bad = [d for d in all_decisions if d["action"] == "FOLD" and d["to_call"] <= 0]
print(f"\nFree-Check-Folds: {len(bad)}  {'OK' if len(bad)==0 else 'BUG!'}")
max_zs = max(zero_sum_checks) if zero_sum_checks else -1
print(f"Max zero-sum deviation: ${max_zs}  {'OK' if max_zs < 5 else 'ISSUE'}")
print(f"\nDone. Total: {elapsed:.0f}s ({elapsed/60:.1f} min)")
