"""Round 2 数值实验：聚焦 k ∈ [0.4, 0.5, 0.6] + separated + cap ∈ [0.75, 0.85]"""
import sys, random, time
sys.path.insert(0, ".")

from collections import Counter
from src.engine.game import GameState, Action, ActionType
from src.engine.player import Player
from src.ai.bots import BoltzmannBot, BOT_PROFILES, BotStyle

SEED_BASE = 20260707
STARTING_CHIPS = 5000
PROFILES = [
    BOT_PROFILES[BotStyle.COLD],
    BOT_PROFILES[BotStyle.COOL],
    BOT_PROFILES[BotStyle.BALANCED],
    BOT_PROFILES[BotStyle.WARM],
    BOT_PROFILES[BotStyle.HOT],
    BOT_PROFILES[BotStyle.CHAOS],
]

def run_sweep(configs, n_hands, postflop_sims=25):
    results = []
    for i, cfg in enumerate(configs):
        desc, params = cfg
        print(f"    [{i+1}/{len(configs)}] {desc} ...", end=" ", flush=True)
        rng = random.Random(SEED_BASE + i * 1000)
        player_profits = Counter()
        all_bets = []

        for h in range(1, n_hands + 1):
            order = list(range(len(PROFILES)))
            rng.shuffle(order)
            pf_shuffled = [PROFILES[j] for j in order]
            players = [Player(name=pf.display_name, chips=STARTING_CHIPS, seat=j) for j, pf in enumerate(pf_shuffled)]
            game = GameState(players, small_blind=5, big_blind=10, auto_rebuy=False)
            bots = {}
            for pf, ply in zip(pf_shuffled, players):
                bots[ply.name] = BoltzmannBot(ply.name, pf, seed=rng.randint(0, 99999),
                                               postflop_sims=postflop_sims, **params)
            game.start_new_hand()
            if game.phase.value >= 6:
                continue
            start_chips = {p.name: p.chips for p in players}
            while game.phase.value < 6:
                cp = game.players[game.current_player_index]
                if cp.is_folded or cp.status.value >= 2:
                    game.current_player_index = game._get_next_active_player(game.current_player_index)
                    continue
                action = bots[cp.name].decide(game, cp)
                if action.action_type not in game.get_legal_actions(cp):
                    action = Action(cp.name, ActionType.FOLD)
                if action.action_type in (ActionType.BET, ActionType.RAISE):
                    all_bets.append(action.amount)
                game.apply_action(action)
            for p in players:
                player_profits[p.name] += p.chips - start_chips[p.name]

        avg_bet = sum(all_bets) / len(all_bets) if all_bets else 0
        n_bets = len(all_bets)

        # Collect per-bot profits
        bot_profits = {pf.display_name: player_profits.get(pf.display_name, 0) for pf in PROFILES}
        cold_p = bot_profits[BOT_PROFILES[BotStyle.COLD].display_name]
        cool_p = bot_profits[BOT_PROFILES[BotStyle.COOL].display_name]
        bal_p = bot_profits[BOT_PROFILES[BotStyle.BALANCED].display_name]
        warm_p = bot_profits[BOT_PROFILES[BotStyle.WARM].display_name]
        hot_p = bot_profits[BOT_PROFILES[BotStyle.HOT].display_name]
        chaos_p = bot_profits[BOT_PROFILES[BotStyle.CHAOS].display_name]

        print(f"avg=${avg_bet:.0f} Bal=${bal_p:+d} Cool=${cool_p:+d} Cold=${cold_p:+d}", flush=True)
        results.append({
            "desc": desc, "params": params, "avg_bet": avg_bet, "n_bets": n_bets,
            "cold": cold_p, "cool": cool_p, "bal": bal_p,
            "warm": warm_p, "hot": hot_p, "chaos": chaos_p,
        })
    results.sort(key=lambda r: -r["bal"])
    return results

def print_results(results, title, n_hands):
    print(f"\n{'='*100}")
    print(f"  {title}")
    print(f"{'='*100}")
    print(f"  {'Rank':>3s} {'Config':<32s} {'AvgBet':>7s} {'Cold':>9s} {'Cool':>9s} {'Bal':>9s} {'Warm':>9s} {'Hot':>9s} {'Chaos':>9s}")
    print(f"  {'-'*95}")
    for rank, r in enumerate(results, 1):
        print(f"  {rank:3d} {r['desc']:<32s} ${r['avg_bet']:6.0f} "
              f"{'+' if r['cold']>=0 else ''}${r['cold']:8d} "
              f"{'+' if r['cool']>=0 else ''}${r['cool']:8d} "
              f"{'+' if r['bal']>=0 else ''}${r['bal']:8d} "
              f"{'+' if r['warm']>=0 else ''}${r['warm']:8d} "
              f"{'+' if r['hot']>=0 else ''}${r['hot']:8d} "
              f"{'+' if r['chaos']>=0 else ''}${r['chaos']:8d} ")


def main():
    t0 = time.perf_counter()
    N = 150  # quick rounds

    # Test promising combinations
    configs = [
        ("k=0.4 sep cap=0.75", {"bet_k_value": 0.4, "bet_strategy": "separated", "bet_cap_frac": 0.75}),
        ("k=0.45 sep cap=0.75", {"bet_k_value": 0.45, "bet_strategy": "separated", "bet_cap_frac": 0.75}),
        ("k=0.5 sep cap=0.75", {"bet_k_value": 0.5, "bet_strategy": "separated", "bet_cap_frac": 0.75}),
        ("k=0.55 sep cap=0.75", {"bet_k_value": 0.55, "bet_strategy": "separated", "bet_cap_frac": 0.75}),
        ("k=0.6 sep cap=0.75", {"bet_k_value": 0.6, "bet_strategy": "separated", "bet_cap_frac": 0.75}),
        ("k=0.5 sep cap=0.80", {"bet_k_value": 0.5, "bet_strategy": "separated", "bet_cap_frac": 0.80}),
        ("k=0.6 sep cap=0.80", {"bet_k_value": 0.6, "bet_strategy": "separated", "bet_cap_frac": 0.80}),
        ("BASELINE k=0.8 bl cap=1", {"bet_k_value": 0.8, "bet_strategy": "blended", "bet_cap_frac": 1.0}),
    ]

    print("=" * 100)
    print(f"ROUND 2A: Fine-tuning k + cap  (strategy=separated, n={N})")
    print("=" * 100)

    results = run_sweep(configs, N, postflop_sims=25)
    print_results(results, f"Round 2A Results (n={N})", N)

    # Best 3 for final validation
    print(f"\n{'='*100}")
    print(f"FINAL VALIDATION: Top 3 vs Baseline (n=500)")
    print(f"{'='*100}")

    final_list = [
        (f"BEST: {results[0]['desc']}", results[0]["params"]),
        (f"2nd:  {results[1]['desc']}", results[1]["params"]),
        ("BASELINE k=0.8 bl cap=1", {"bet_k_value": 0.8, "bet_strategy": "blended", "bet_cap_frac": 1.0}),
    ]

    results_final = run_sweep(final_list, 500, postflop_sims=100)
    print_results(results_final, f"Final Results (n=500)", 500)

    elapsed = time.perf_counter() - t0
    best = results_final[0]
    params = best.get("params", {})
    print(f"\n{'='*100}")
    print(f"FINAL RECOMMENDATION (total {elapsed:.0f}s)")
    print(f"  Config: {best['desc']}")
    print(f"  Params: k={params.get('bet_k_value','?')}, strat={params.get('bet_strategy','?')}, cap={params.get('bet_cap_frac','?')}")
    print(f"  Avg bet: ${best['avg_bet']:.0f} ({best['avg_bet']/10:.0f} BB)")
    print(f"  Balanced profit: ${best['bal']} ({best['bal']/500:.0f}/hand)")
    print(f"  Cool profit: ${best['cool']} ({best['cool']/500:.0f}/hand)")
    print(f"  Update bots.py defaults: bet_k_value={params.get('bet_k_value','?')}, "
          f"bet_strategy='{params.get('bet_strategy','?')}', bet_cap_frac={params.get('bet_cap_frac','?')}")
    print(f"{'='*100}")


if __name__ == "__main__":
    main()
