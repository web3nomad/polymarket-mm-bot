# Polymarket Trading Bot - Operations Manual

## Quick Start

```bash
cd /Users/xddotcom/.openclaw/workspace/polymarket-mm-bot
source .env          # load POLYMARKET_PRIVATE_KEY & POLYMARKET_FUNDER
source .venv/bin/activate
```

## Commands

### Start Engine

```bash
# foreground (see logs live)
python main.py run --confirm-live

# background (daemon)
nohup python main.py run --confirm-live > data/engine.log 2>&1 &
echo $! > data/engine.pid
```

### Stop Engine

```bash
touch .halt
# engine will stop within 1 loop cycle (~2 seconds)
# remove to restart: rm .halt
```

### Emergency Kill

```bash
kill $(cat data/engine.pid)
# or
pkill -f "main.py run"
```

### Check Status

```bash
# real-time log
tail -f data/engine.log

# summary only
grep "mode=live" data/engine.log | tail -20

# errors/warnings
grep "WARNING\|ERROR" data/engine.log | tail -20

# portfolio report (equity, PnL, positions)
python main.py report

# check USDC balance
python -c "
from services.clob import create_live_client, get_usdc_balance
import yaml
with open('config.yaml') as f:
    config = yaml.safe_load(f)
client = create_live_client(config)
print(f'USDC: \${get_usdc_balance(client):.2f}')
"
```

### Single Loop Test

```bash
# run one cycle then exit (good for testing config changes)
python main.py run --once --confirm-live
```

## Config: config.yaml

### Key Parameters

| Parameter | Current | Description |
|-----------|---------|-------------|
| `mode` | `live` | `live` or `paper` |
| `top_n` | 20 | max markets to trade |
| `min_spread` | 0.005 | minimum bid-ask spread filter |
| `min_liquidity` | 500 | minimum market liquidity ($) |
| `run_interval_sec` | 2 | seconds between loops |

### Risk

| Parameter | Current | Description |
|-----------|---------|-------------|
| `initial_equity` | 50 | starting capital ($) |
| `max_order_notional` | 6 | max $ per order |
| `max_market_exposure` | 12 | max $ per market |
| `daily_loss_limit` | 10 | stop if daily loss exceeds this |
| `kelly_fraction` | 0.5 | half-Kelly for sizing |
| `min_confidence` | 0.3 | minimum signal confidence |

### Strategies

| Strategy | Enabled | Description |
|----------|---------|-------------|
| `market_making` | yes | spread capture with inventory skew |
| `arbitrage` | yes | YES+NO mispricing detection |
| `momentum` | yes | price/volume momentum signals |
| `mean_reversion` | no | z-score mean reversion |

### Live Trading

| Parameter | Current | Description |
|-----------|---------|-------------|
| `order_type` | GTC | Good Till Cancelled |
| `allow_sell` | false | only buy side |
| `trade_side` | buy | restricts to buy orders |
| `exchange_min_shares` | 5 | Polymarket minimum |
| `market_cooldown_sec` | 45 | cooldown after failed order |
| `precheck_required` | true | check balance before ordering |

## Safety Features

- **Kill switch**: `touch .halt` stops engine gracefully
- **Daily loss limit**: auto-stops if daily loss > `daily_loss_limit`
- **Precheck**: verifies USDC balance before every order
- **Market cooldown**: 45s cooldown per market after failed order
- **Side gating**: `allow_sell: false` prevents selling (buy-only mode)
- **Notional cap**: no single order exceeds `max_order_notional`
- **Exposure cap**: no market exceeds `max_market_exposure`

## File Structure

```
config.yaml          # all configuration
.env                 # POLYMARKET_PRIVATE_KEY, POLYMARKET_FUNDER
.halt                # touch to stop, rm to allow restart
data/engine.log           # runtime log (when running as daemon)
data/engine.pid           # PID file
settlement.jsonl     # all order events (append-only audit log)

main.py              # CLI entry point
core/
  engine.py          # main loop orchestration
  risk.py            # Kelly sizing, exposure limits
  models.py          # data structures
  config.py          # config loading
  events.py          # settlement logging
strategies/
  market_making.py   # spread capture
  arbitrage.py       # mispricing detection
  momentum.py        # trend following
  mean_reversion.py  # z-score reversion
services/
  gamma.py           # market data (Gamma API)
  clob.py            # order execution (CLOB API)
  websocket.py       # optional real-time feed
```

## Common Operations

### Change Capital

Edit `config.yaml`:
```yaml
risk:
  initial_equity: <new amount>
```
Then restart engine (`touch .halt`, wait, `rm .halt`, re-run).

### Add More Markets

Lower filters in `config.yaml`:
```yaml
min_spread: 0.003      # was 0.005
min_liquidity: 200      # was 500
top_n: 30               # was 20
```

### Enable Selling

```yaml
live:
  allow_sell: true
  trade_side: "both"    # was "buy"
```

### Enable Mean Reversion

```yaml
strategies:
  mean_reversion:
    enabled: true
```

### View Settlement Log

```bash
# last 10 events
tail -10 settlement.jsonl | python -m json.tool

# count fills
grep '"type": "fill"' settlement.jsonl | wc -l

# count errors
grep '"type": "live_order_error"' settlement.jsonl | wc -l
```

## Monitoring Checklist

| Check | Command | Healthy |
|-------|---------|---------|
| Engine running? | `ps aux \| grep main.py` | process exists |
| Recent activity? | `tail -1 data/engine.log` | timestamp < 10s ago |
| Orders executing? | `grep executed data/engine.log \| tail -1` | executed > 0 |
| No errors? | `grep ERROR data/engine.log \| tail -5` | empty or rare |
| Balance OK? | `python main.py report` | equity > 0 |
| Kill switch off? | `ls .halt 2>/dev/null` | file not found |

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `executed=0` every loop | balance locked in orders or insufficient | check USDC balance, wait for fills |
| `min-size` errors | shares < 5 | increase `max_order_notional` |
| `allowance/balance` | not enough USDC | deposit more or reduce order sizes |
| `geoblock` | IP blocked | check VPN |
| engine stopped | `.halt` file exists | `rm .halt` and restart |
| `Missing env` error | .env not loaded | `source .env` before running |
