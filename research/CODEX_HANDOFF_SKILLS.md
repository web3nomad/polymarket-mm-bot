# CODEX Handoff: Polymarket Skill Research (for implementation)

## Existing research files
1. `research/skill-due-diligence.md`
2. `research/x-skill-scan.md`

## Recommended skill priority
1. `agentmc15/polymarket-trader@polymarket-api`
2. `agentmc15/polymarket-trader@trading-strategies`
3. `agentmc15/polymarket-trader@trader-analysis` (optional)

## Install commands
```bash
npx skills add agentmc15/polymarket-trader@polymarket-api -g -y
npx skills add agentmc15/polymarket-trader@trading-strategies -g -y
npx skills add agentmc15/polymarket-trader@trader-analysis -g -y
```

## Reference links
- https://skills.sh/agentmc15/polymarket-trader/polymarket-api
- https://skills.sh/agentmc15/polymarket-trader/trading-strategies
- https://skills.sh/agentmc15/polymarket-trader/trader-analysis
- https://github.com/agentmc15/polymarket-trader

## What to apply into this repo (polymarket-mm-bot)
1. Improve market-selection logic (beyond top liquidity only)
2. Add strategy abstraction layer (signal -> risk -> execution)
3. Add robust live order handling:
   - min order notional checks
   - GTC/FOK adaptive mode
   - retries/backoff with clear error taxonomy
4. Add position/balance prechecks before sell intents
5. Add a small backtest/replay harness for parameter tuning
6. Strengthen risk controls:
   - session-level drawdown guard
   - per-market cooldown
   - daily order caps

## Constraints from live tests already observed
- Frequent `not enough balance / allowance`
- Occasional geoblock `403` responses
- FOK often kills orders on thin depth
- Tight spread filters can produce `intents=0`

## Suggested first patch set
- Default live order type: `GTC`
- Keep `allow_sell=false` until inventory sync is implemented
- Add inventory/allowance sync before enabling sell
- Make spread/notional filters adaptive by token price and tick size
