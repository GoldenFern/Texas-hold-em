"""T 预实验：在不同温度下输出各动作选择概率，确定各风格合理的 T 预设。"""
import math, sys
sys.path.insert(0, ".")

# 局面定义
SCENARIOS = [
    {
        "name": "preflop AA pot=15 to_call=10",
        "comment": "extreme strong hand",
        "evs": {
            "Fold": 0,
            "Call": 0.85 * (15 + 10) - 10,  # 11.25
        },
    },
    {
        "name": "preflop 72o pot=15 to_call=10",
        "comment": "extreme weak hand",
        "evs": {
            "Fold": 0,
            "Call": 0.25 * (15 + 10) - 10,  # -3.75
        },
    },
    {
        "name": "postflop pair pot=30 to_call=15 win=0.65",
        "comment": "medium strength, call half-pot",
        "evs": {
            "Fold": 0,
            "Call": 0.65 * (30 + 15) - 15,  # 14.25
        },
    },
    {
        "name": "postflop highcard pot=20 to_call=0 win=0.25",
        "comment": "weak hand, free to see next card",
        "evs": {
            "Check": 0.25 * 20,  # 5.0
        },
    },
]

Ts = [0.3, 0.5, 0.8, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 12.0, 16.0, 20.0]

def boltzmann_prob(evs, T):
    max_ev = max(evs.values())
    weights = {a: math.exp((e - max_ev) / T) for a, e in evs.items()}
    total = sum(weights.values())
    return {a: round(w / total * 100, 1) for a, w in weights.items()}

print("=" * 90)
print("T Pre-Experiment: Boltzmann-EV Bot Temperature Calibration")
print("=" * 90)

for sc in SCENARIOS:
    print(f"\n{'─' * 80}")
    print(f"Scenario: {sc['name']}")
    print(f"  {sc['comment']}")
    print(f"{'─' * 80}")

    evs = sc["evs"]
    for a, e in sorted(evs.items(), key=lambda x: -x[1]):
        print(f"  {a:8s}: {e:+.2f} BB")

    actions = sorted(evs.keys(), key=lambda a: -evs[a])
    print(f"\n{'T':>5s}", end="")
    for a in actions:
        print(f"{a:>8s}", end="")
    print("  | Best Action Prob")

    for T in Ts:
        probs = boltzmann_prob(evs, T)
        best_a = max(probs, key=probs.get)
        best_p = probs[best_a]
        tag = ""
        if best_p >= 95: tag = "DOMINANT"
        elif best_p >= 80: tag = "STRONG"
        elif best_p >= 60: tag = "CLEAR"
        elif best_p >= 45: tag = "MODERATE"
        else: tag = "FLAT"
        print(f"{T:5.1f} ", end="")
        for a in actions:
            print(f"{probs[a]:6.1f}%", end="")
        print(f"  | {best_a} {best_p:.0f}% [{tag}]")

print("\n" + "=" * 90)
print("Recommendations:")
print("  NIT   : T=0.5 (near-deterministic, best action strongly dominant)")
print("  TAG   : T=1.0 (clear preference for high EV actions)")
print("  Shark : T=2.0 (moderate, balanced, DEFAULT)")
print("  LAG   : T=4.0 (mild EV preference, more exploration)")
print("  CS    : T=8.0 (weak EV preference, hard to fold)")
print("  Maniac: T=16.0 (near-uniform, barely EV-driven)")
print("=" * 90)
