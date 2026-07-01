# Texas Hold'em Poker — LLM-Powered AI Opponents

A full-stack Texas Hold'em No-Limit poker application featuring a complete game engine, rule-based AI bots, **LLM-driven AI opponents** (Claude / GPT / Ollama), real-time web interface, and comprehensive analysis tools.

## Features

- **Complete Poker Engine** — Pre-flop → Flop → Turn → River → Showdown, with side-pot calculation, all-in handling, and three betting structures (No Limit / Pot Limit / Fixed Limit)
- **6 AI Bot Personalities** — TAG (tight-aggressive), LAG (loose-aggressive), NIT, Calling Station, Maniac, Shark — each with distinct VPIP, aggression, and bluff profiles
- **LLM-Powered Bot** — Delegates decisions to Claude / GPT / local Ollama models, with multi-level fallback chain and configurable decision frequency
- **Real-Time Web UI** — Flask + SocketIO server with green felt poker table, elliptical player layout, action controls, and analysis side panel
- **Hand Analysis** — Monte Carlo equity simulation, pot odds & implied odds calculator, hand strength visualization
- **Two Play Modes** — Web UI (human vs bots) or CLI mode (AI-vs-AI automated battles)

## Project Structure

```
Texas-hold-em/
├── main.py                 # Entry point (server / CLI / test)
├── requirements.txt        # Python dependencies
├── config/
│   ├── game_config.json    # Game parameters
│   └── llm_config.json     # LLM provider & model settings
├── src/
│   ├── engine/             # Core game engine (card, deck, hand eval, pot, game state)
│   ├── ai/                 # Rule-based AI bots & strategy
│   ├── llm/                # LLM integration (client, prompt, parser, fallback)
│   ├── analysis/           # Equity, odds, reporter
│   ├── server/             # Flask + SocketIO web server
│   └── utils/              # Constants & enums
├── templates/              # Jinja2 HTML templates
├── static/                 # CSS & JavaScript frontend
└── tests/                  # Unit & integration tests
```

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

**Optional — LLM integration** (uncomment in `requirements.txt` first):

```bash
pip install anthropic openai requests python-dotenv
```

### 2. Set API Keys (for LLM bots)

```bash
export ANTHROPIC_API_KEY="your-key-here"   # Claude
export OPENAI_API_KEY="your-key-here"       # GPT
```

Or create a `.env` file with `THP_LLM_API_KEY`, `THP_LLM_PROVIDER`, etc.

### 3. Launch

```bash
# Web server (default) — open http://localhost:5000
python main.py

# Custom host/port
python main.py --host 0.0.0.0 --port 8080 --debug

# CLI mode — 6 AI bots battle automatically
python main.py --cli --hands 25

# Run tests
python main.py --test
```

## Configuration

### Game Settings (`config/game_config.json`)

| Key | Default | Description |
|-----|---------|-------------|
| `max_players` | 9 | Max seats at the table |
| `starting_chips` | 1000 | Initial stack per player |
| `small_blind` | 5 | Small blind amount |
| `big_blind` | 10 | Big blind amount |
| `betting_structure` | `"no_limit"` | `no_limit` / `pot_limit` / `fixed_limit` |
| `time_bank_seconds` | 30 | Time per decision |

### LLM Settings (`config/llm_config.json`)

| Key | Default | Description |
|-----|---------|-------------|
| `provider` | `"anthropic"` | `anthropic` / `openai` / `ollama` |
| `model` | `"claude-sonnet-4-20250514"` | Model ID |
| `strategy.call_frequency` | `"every"` | `every` / `critical` / `mixed` |
| `fallbacks` | Haiku → GPT-4o-mini | Fallback chain order |

## Web Interface

- **Poker Table** — Elliptical green felt layout showing all players, hole cards (yours only), community cards, pot size, and current bet
- **Action Panel** — Fold / Check / Call / Raise buttons with bet slider and All-In option
- **Analysis Panel** — Hand strength meter, pot odds %, draw detection, win probability
- **History Panel** — Hand history log with winners and amounts
- **Settings** — Configure player count, bot styles, blind levels, and LLM options

## AI Bot Styles

| Style | VPIP | Aggression | Description |
|-------|------|------------|-------------|
| **TAG** | 18% | High | Tight-Aggressive: selective hands, plays hard |
| **LAG** | 28% | Very High | Loose-Aggressive: wide range, constant pressure |
| **NIT** | 10% | Low | Ultra-tight: only premium hands |
| **Calling Station** | 40% | Very Low | Loose-passive: calls everything |
| **Maniac** | 50% | Extreme | Hyper-aggressive: raises with anything |
| **Shark** | 22% | Adaptive | Balanced: adapts to opponents |

## LLM Bot Architecture

```
Game State → PromptBuilder → LLM Client (Claude/GPT/Ollama)
                                  ↓
Game Engine ← Action ← ResponseParser ← LLM Response
                                  ↓ (on failure)
                          FallbackChain
                     → Fallback LLMs → Rule Engine
```

The bot receives pre-computed hand strength, pot odds, equity estimates, position, and game context in a structured prompt. The LLM returns a JSON action (`fold`/`check`/`call`/`raise`/`all-in`) with a validated amount.

## Testing

```bash
python main.py --test          # Run all tests
pytest tests/ -v               # With verbose output
pytest tests/test_hand.py -v   # Single test file
```

11 test files covering: card/deck, hand evaluation (all 10 ranks), game state machine, pot/side-pot calculation, AI bot decisions, Monte Carlo equity, LLM integration, and full game flow.
