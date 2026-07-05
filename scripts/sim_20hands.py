"""6 Boltzmann-EV Bots 对战 20 局仿真，逐局核查决策合理性。"""
import sys, random
sys.path.insert(0, ".")

from src.engine.game import GameState, Action, ActionType
from src.engine.player import Player
from src.ai.bots import BoltzmannBot, BOT_PROFILES, BotStyle

SEED = 20250705
PROFILES = [
    BOT_PROFILES[BotStyle.NIT],
    BOT_PROFILES[BotStyle.TAG],
    BOT_PROFILES[BotStyle.SHARK],
    BOT_PROFILES[BotStyle.LAG],
    BOT_PROFILES[BotStyle.CALLING_STATION],
    BOT_PROFILES[BotStyle.MANIAC],
]

def run_hand(hand_id, rng):
    players = [Player(name=pf.display_name, chips=1000, seat=i) for i, pf in enumerate(PROFILES)]
    game = GameState(players, small_blind=5, big_blind=10)
    bots = {}
    for pf, ply in zip(PROFILES, players):
        bots[ply.name] = BoltzmannBot(ply.name, pf, seed=rng.randint(0, 9999))

    game.start_new_hand()
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

    return decisions, game.winners, game.pot.total

def main():
    rng = random.Random(SEED)
    all_decisions = []
    for h in range(1, 21):
        decs, winners, pot = run_hand(h, rng)
        all_decisions.extend(decs)
        winner_str = ", ".join(f"{n}(+${a})" for n, a in winners.items())
        print(f"Hand #{h:2d}: winners={winner_str}, pot=${pot}")

    print(f"\nTotal decisions: {len(all_decisions)}")

    from collections import Counter
    # Per-player stats
    for name in sorted(set(d["player"] for d in all_decisions)):
        acts = [d for d in all_decisions if d["player"] == name]
        counts = Counter(d["action"] for d in acts)
        print(f"  {name:6s}: {dict(counts)}")

    # Bad folds check
    bad_folds = [d for d in all_decisions if d["action"] == "FOLD" and d["to_call"] <= 0]
    if bad_folds:
        print(f"\n*** BAD FOLDS (to_call<=0): {len(bad_folds)}")
        for d in bad_folds[:10]:
            print(f"  Hand#{d['hand']} {d['player']} phase={d['phase']} hole={d['hole']} to_call={d['to_call']}")
    else:
        print("All good: no bot folded when Check was available.")

if __name__ == "__main__":
    main()
