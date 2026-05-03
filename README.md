# ⚠️ DEPRECATED — See DEPRECATED.md

---

# Polymarket Multi-Strategy Trading Engine

4 strategies, Kelly sizing, multi-signal aggregation.

## Architecture

```
Market Data (Gamma API) → [Strategies] → Signals → Risk Manager → Executor (Paper/Live)
```

**Strategies:**
- `market_making` — spread-based quoting with inventory skew
- `arbitrage` — YES+NO mispricing detection
- `momentum` — price trend + volume + orderbook imbalance
- `mean_reversion` — z-score deviation from rolling mean

**Risk:** Kelly criterion sizing, drawdown guard, per-market exposure limit, daily loss halt.

## Setup

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
# Paper mode
python main.py run --once

# Continuous paper
python main.py run --interval 2

# Live mode (real orders!)
python main.py run --once --confirm-live

# Report
python main.py report

# Watch events
python main.py watch --follow --tail 30
```

## Config

All settings in `config.yaml`. Key sections:

- `mode`: `paper` or `live`
- `strategies.*`: enable/disable and tune each strategy
- `risk.*`: Kelly, drawdown, exposure limits
- `live.*`: CLOB credentials, order type, safeguards

## Credentials (.env)

```
POLYMARKET_PRIVATE_KEY=0x...
POLYMARKET_FUNDER=0x...
```

## Kill Switch

```bash
touch .halt    # stops bot on next loop
rm .halt       # re-enable
```

## File Structure

```
main.py              # CLI entry
config.yaml          # Configuration
core/
  engine.py          # Main loop orchestration
  models.py          # Data structures
  config.py          # Config loading
  events.py          # Settlement logging
  risk.py            # Kelly sizing + risk gates
strategies/
  base.py            # Strategy interface
  market_making.py   # Spread quoting
  arbitrage.py       # Price inefficiency
  momentum.py        # Trend following
  mean_reversion.py  # Statistical reversion
services/
  gamma.py           # Market data API
  clob.py            # Order execution
  websocket.py       # Real-time feed (optional)
```
