"""数值实验：扫描下注参数，找到最优 k_value / strategy / cap。

实验设计（3 轮）：
  Round 1: 固定 strategy=separated, cap=0.75, 扫描 k_value ∈ [0.3..0.7]
  Round 2: 取最佳 k_value, 扫描 strategy ∈ [value_only, separated, blended]
  Round 3: 取最佳 (k, strategy), 扫描 cap ∈ [0.5, 0.75, 1.0]
  Final:  1000 手验证 Top 3 配置
"""
import sys, random, time, itertools
sys.path.insert(0, ".")

from collections import Counter

from src.engine.game import GameState, Action, ActionType
from src.engine.player import Player
from src.ai.bots import BoltzmannBot, BOT_PROFILES, BotStyle

SEED_BASE = 20260706
STARTING_CHIPS = 5000
PROFILES = [
    BOT_PROFILES[BotStyle.COLD],
    BOT_PROFILES[BotStyle.COOL],
    BOT_PROFILES[BotStyle.BALANCED],
    BOT_PROFILES[BotStyle.WARM],
    BOT_PROFILES[BotStyle.HOT],
    BOT_PROFILES[BotStyle.CHAOS],
]

def run_sweep(configs, n_hands, label, postflop_sims=25):
    """运行一轮参数扫描，每配置 n_hands 手。返回排序后的结果列表。"""
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

        # 聚合统计
        total_profit = sum(player_profits.values())
        profits_list = [player_profits.get(pf.display_name, 0) for pf in PROFILES]
        best_profit = max(profits_list)
        worst_profit = min(profits_list)
        cold_profit = player_profits.get(BOT_PROFILES[BotStyle.COLD].display_name, 0)
        balanced_profit = player_profits.get(BOT_PROFILES[BotStyle.BALANCED].display_name, 0)
        cool_profit = player_profits.get(BOT_PROFILES[BotStyle.COOL].display_name, 0)
        avg_bet = sum(all_bets) / len(all_bets) if all_bets else 0
        n_bets = len(all_bets)

        print(f"done ({n_bets} bets, avg=${avg_bet:.0f})", flush=True)
        results.append({
            "desc": desc,
            "params": params,
            "total_profit": total_profit,
            "best_profit": best_profit,
            "worst_profit": worst_profit,
            "cold_profit": cold_profit,
            "cool_profit": cool_profit,
            "balanced_profit": balanced_profit,
            "avg_bet": avg_bet,
            "n_bets": n_bets,
            "profits_list": profits_list,
        })

    # 按 best bot 的利润排序
    results.sort(key=lambda r: -r["balanced_profit"])
    return results


def print_results(results, title):
    print(f"\n{'='*90}")
    print(f"  {title}")
    print(f"{'='*90}")
    print(f"  {'Rank':>3s} {'Config':<35s} {'AvgBet':>7s} {'Bets':>5s} {'Cold':>8s} {'Cool':>8s} {'Bal':>8s} {'Best':>8s} {'Worst':>8s} {'Sum':>8s}")
    print(f"  {'-'*85}")
    for rank, r in enumerate(results, 1):
        print(f"  {rank:3d} {r['desc']:<35s} ${r['avg_bet']:6.0f} {r['n_bets']:5d} "
              f"{'+' if r['cold_profit']>=0 else ''}${r['cold_profit']:7d} "
              f"{'+' if r['cool_profit']>=0 else ''}${r['cool_profit']:7d} "
              f"{'+' if r['balanced_profit']>=0 else ''}${r['balanced_profit']:7d} "
              f"{'+' if r['best_profit']>=0 else ''}${r['best_profit']:7d} "
              f"{'+' if r['worst_profit']>=0 else ''}${r['worst_profit']:7d} "
              f"{'+' if r['total_profit']>=0 else ''}${r['total_profit']:7d}")


def main():
    t0 = time.perf_counter()
    N_QUICK = 150   # 快速轮的手数
    N_FINAL = 500   # 决赛轮的手数

    # ================================================================
    # Round 1: 扫描 k_value（固定 strategy=separated, cap=0.75）
    # ================================================================
    print("=" * 90)
    print("ROUND 1: Scanning k_value  (strategy=separated, cap=0.75, n=300)")
    print("=" * 90)

    k_values = [0.3, 0.4, 0.5, 0.6, 0.7]
    configs_r1 = []
    for kv in k_values:
        desc = f"k={kv:.1f} sep cap=0.75"
        params = {"bet_k_value": kv, "bet_strategy": "separated", "bet_cap_frac": 0.75}
        configs_r1.append((desc, params))

    results_r1 = run_sweep(configs_r1, N_QUICK, "Round 1")
    print_results(results_r1, f"Round 1 Results (n={N_QUICK})")

    # 取最优 k_value
    best_k = results_r1[0]["params"]["bet_k_value"]
    print(f"\n  >>> Best k_value = {best_k:.1f}")

    # ================================================================
    # Round 2: 扫描 strategy（固定最佳 k_value, cap=0.75）
    # ================================================================
    print(f"\n{'='*90}")
    print(f"ROUND 2: Scanning strategy  (k={best_k:.1f}, cap=0.75, n={N_QUICK})")
    print(f"{'='*90}")

    strategies = [
        ("value_only", "value_only"),
        ("separated", "separated"),
        ("blended (cur)", "blended"),
    ]
    configs_r2 = []
    for desc_s, strat in strategies:
        desc = f"k={best_k:.1f} {desc_s} cap=0.75"
        params = {"bet_k_value": best_k, "bet_strategy": strat, "bet_cap_frac": 0.75}
        configs_r2.append((desc, params))
    # 也加一个当前默认配置作为 baseline
    configs_r2.append(("BASELINE k=0.8 blended cap=1.0", {
        "bet_k_value": 0.8, "bet_strategy": "blended", "bet_cap_frac": 1.0}))

    results_r2 = run_sweep(configs_r2, N_QUICK, "Round 2")
    print_results(results_r2, f"Round 2 Results (n={N_QUICK})")

    best_strategy = results_r2[0]["params"]["bet_strategy"]
    best_cap = results_r2[0]["params"]["bet_cap_frac"]
    print(f"\n  >>> Best strategy = {best_strategy}")

    # ================================================================
    # Round 3: 扫描 cap（固定最佳 k_value, 最佳 strategy）
    # ================================================================
    print(f"\n{'='*90}")
    print(f"ROUND 3: Scanning cap  (k={best_k:.1f}, strategy={best_strategy}, n={N_QUICK})")
    print(f"{'='*90}")

    caps = [0.5, 0.6, 0.75, 0.85, 1.0]
    configs_r3 = []
    for c in caps:
        desc = f"k={best_k:.1f} {best_strategy} cap={c:.2f}"
        params = {"bet_k_value": best_k, "bet_strategy": best_strategy, "bet_cap_frac": c}
        configs_r3.append((desc, params))

    results_r3 = run_sweep(configs_r3, N_QUICK, "Round 3")
    print_results(results_r3, f"Round 3 Results (n={N_QUICK})")

    best_cap = results_r3[0]["params"]["bet_cap_frac"]
    print(f"\n  >>> Best cap = {best_cap:.2f}")

    # ================================================================
    # Final: 1000 手验证 Top 3
    # ================================================================
    print(f"\n{'='*90}")
    print(f"FINAL: 1000-hand validation — Top 3 vs Baseline")
    print(f"{'='*90}")

    top_configs = [
        (f"BEST: k={best_k:.1f} {best_strategy} cap={best_cap:.2f}", {
            "bet_k_value": best_k, "bet_strategy": best_strategy, "bet_cap_frac": best_cap}),
        (f"2nd:  {results_r3[1]['desc']}" if len(results_r3) > 1 else "2nd: k=0.5 sep cap=0.75",
         results_r3[1]["params"] if len(results_r3) > 1 else {"bet_k_value": 0.5, "bet_strategy": "separated", "bet_cap_frac": 0.75}),
        ("BASELINE k=0.8 blended cap=1.0", {
            "bet_k_value": 0.8, "bet_strategy": "blended", "bet_cap_frac": 1.0}),
    ]

    results_final = run_sweep(top_configs, N_FINAL, "Final", postflop_sims=100)
    print_results(results_final, f"Final Results (n={N_FINAL})")

    # ================================================================
    # 推荐
    # ================================================================
    elapsed = time.perf_counter() - t0
    best = results_final[0]
    print(f"\n{'='*90}")
    print(f"RECOMMENDATION (total {elapsed:.0f}s)")
    print(f"{'='*90}")
    print(f"  Best config: {best['desc']}")
    print(f"  Avg bet: ${best['avg_bet']:.0f}")
    print(f"  Balanced bot profit: ${best['balanced_profit']} ({best['balanced_profit']/N_FINAL:.0f}/hand)")
    print(f"  Cool bot profit: ${best['cool_profit']} ({best['cool_profit']/N_FINAL:.0f}/hand)")
    print(f"  Update bots.py: bet_k_value={best_k:.1f}, bet_strategy='{best_strategy}', bet_cap_frac={best_cap:.2f}")
    print(f"{'='*90}")


if __name__ == "__main__":
    main()
