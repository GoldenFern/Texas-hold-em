"""1000局仿真：每轮座次随机化。"""
import sys, random, time
sys.path.insert(0, ".")

from src.engine.game import GameState, Action, ActionType
from src.engine.player import Player
from src.ai.bots import BoltzmannBot, BOT_PROFILES, BotStyle
from collections import Counter

SEED = 2026
PROFILES = [
    BOT_PROFILES[BotStyle.NIT],
    BOT_PROFILES[BotStyle.TAG],
    BOT_PROFILES[BotStyle.SHARK],
    BOT_PROFILES[BotStyle.LAG],
    BOT_PROFILES[BotStyle.CALLING_STATION],
    BOT_PROFILES[BotStyle.MANIAC],
]
N = 1000

rng = random.Random(SEED)
all_decisions = []
hand_wins = Counter()
player_profits = Counter()

t0 = time.perf_counter()
for h in range(1, N + 1):
    order = list(range(len(PROFILES)))
    rng.shuffle(order)
    pf_shuffled = [PROFILES[i] for i in order]

    players = [Player(name=pf.display_name, chips=1000, seat=i) for i, pf in enumerate(pf_shuffled)]
    game = GameState(players, small_blind=5, big_blind=10)
    bots = {}
    for pf, ply in zip(pf_shuffled, players):
        bots[ply.name] = BoltzmannBot(ply.name, pf, seed=rng.randint(0, 99999))

    game.start_new_hand()

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

    winners = dict(game.winners)
    for name in winners:
        hand_wins[name] += 1
    for p in game.players:
        won = winners.get(p.name, 0)
        spent = 1000 - p.chips - (won if p.name in winners else 0)
        player_profits[p.name] += won - spent

    if h % 200 == 0:
        elapsed = time.perf_counter() - t0
        print(f"  ... {h}/{N} hands ({elapsed:.0f}s)")

elapsed = time.perf_counter() - t0
total = len(all_decisions)

print(f"\n{'='*80}")
print(f"{N}-HAND SIMULATION (random seats each hand, {elapsed:.0f}s)")
print(f"{'='*80}")

print(f"\n{'Rank':>4s} {'Bot':>14s} {'Wins':>5s} {'Win%':>5s} {'Profit':>10s} {'PerHand'}")
print("-" * 65)
for rank, (name, p) in enumerate(sorted(player_profits.items(), key=lambda x: -x[1]), 1):
    w = hand_wins[name]
    wr = w / N * 100
    print(f"  {rank:2d}. {name:14s} {w:5d} {wr:4.1f}% {'+' if p>=0 else ''}${p:>9d} {'+' if p/N>=0 else ''}${p/N:>+7.0f}")

counts = Counter()
ai_cnt = 0
bets = []
for d in all_decisions:
    counts[d["action"]] += 1
    if d["all_in"]: ai_cnt += 1
    if d["action"] in ("BET", "RAISE"): bets.append(d["amount"])

print(f"\nGLOBAL ({total} decisions)")
for a in ["FOLD", "CHECK", "CALL", "BET", "RAISE"]:
    c = counts.get(a, 0)
    print(f"  {a:6s}: {c:5d} ({c/total*100:.1f}%)")
if bets:
    bt = counts.get("BET",0)+counts.get("RAISE",0)
    print(f"  Avg bet/raise: ${sum(bets)/len(bets):.0f}")
    print(f"  All-in: {ai_cnt}/{bt} ({ai_cnt/bt*100:.0f}% of bet/raise)")

print("\nPER-BOT")
for name in sorted(set(d["player"] for d in all_decisions)):
    acts = [d for d in all_decisions if d["player"] == name]
    n = len(acts)
    c = Counter(d["action"] for d in acts)
    br = c.get("BET",0)+c.get("RAISE",0)
    ai = sum(1 for d in acts if d["all_in"])
    print(f"  {name:14s}: {n:4d} F={c.get('FOLD',0)/n*100:.0f}% K={c.get('CHECK',0)/n*100:.0f}% C={c.get('CALL',0)/n*100:.0f}% BR={br/n*100:.0f}% AI={ai}")

bad = [d for d in all_decisions if d["action"] == "FOLD" and d["to_call"] <= 0]
print(f"\nFree-Check-Folds: {len(bad)}  {'PASS' if len(bad)==0 else 'FAIL'}")
print("Done.")
