"""Trading engine: orchestrates market data -> strategies -> risk -> execution."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from core.config import load_config
from core.events import write_event
from core.models import Market, OrderIntent, PortfolioState, Position
from core.risk import RiskManager
from services.clob import create_live_client, execute_live, execute_paper, sync_positions
from services.gamma import fetch_markets
from strategies.arbitrage import ArbitrageStrategy
from strategies.base import BaseStrategy
from strategies.market_making import MarketMakingStrategy
from strategies.mean_reversion import MeanReversionStrategy
from strategies.momentum import MomentumStrategy
from strategies.position_manager import PositionManagerStrategy

LOGGER = logging.getLogger("polymarket.engine")


def _build_strategies(config: dict[str, Any]) -> list[BaseStrategy]:
    """Instantiate all enabled strategies from config."""
    strat_cfg = config.get("strategies", {})
    registry: list[tuple[str, type[BaseStrategy]]] = [
        ("market_making", MarketMakingStrategy),
        ("arbitrage", ArbitrageStrategy),
        ("momentum", MomentumStrategy),
        ("mean_reversion", MeanReversionStrategy),
        ("position_manager", PositionManagerStrategy),
    ]
    active: list[BaseStrategy] = []
    for name, cls in registry:
        cfg = strat_cfg.get(name, {})
        if not cfg.get("enabled", False):
            continue
        active.append(cls(cfg))
        LOGGER.info("Strategy enabled: %s", name)
    return active


def _log_tick(settlement: Path, m: Market) -> None:
    write_event(settlement, {
        "type": "tick",
        "token_id": m.token_id,
        "question": m.question,
        "best_bid": m.best_bid,
        "best_ask": m.best_ask,
        "spread": round(m.spread, 4),
        "liquidity": m.liquidity,
        "volume_24h": m.volume_24h,
        "end_time": m.end_time,
    })


def _log_positions(settlement: Path, portfolio: PortfolioState) -> None:
    rows = []
    for token_id, pos in portfolio.positions.items():
        if abs(pos.size) < 1e-12:
            continue
        rows.append({
            "token_id": token_id,
            "size": round(pos.size, 6),
            "avg_entry": round(pos.avg_entry, 6),
            "realized_pnl": round(pos.realized_pnl, 6),
        })
    write_event(settlement, {"type": "position_snapshot", "positions": rows})


def _log_equity(settlement: Path, portfolio: PortfolioState, mode: str, halted: bool) -> None:
    write_event(settlement, {
        "type": "equity_snapshot",
        "exec_mode": mode,
        "equity": round(portfolio.equity, 6),
        "realized_pnl": round(portfolio.realized_pnl(), 6),
        "unrealized_pnl": round(portfolio.unrealized_pnl(), 6),
        "drawdown": round(portfolio.drawdown, 6),
        "halted": halted,
    })


def _log_loop(settlement: Path, mode: str, n_markets: int, n_signals: int, n_intents: int, n_executed: int, strategies_used: list[str]) -> None:
    write_event(settlement, {
        "type": "loop_summary",
        "exec_mode": mode,
        "markets": n_markets,
        "signals": n_signals,
        "intents": n_intents,
        "executed": n_executed,
        "strategies": strategies_used,
    })


def run_loop(config: dict[str, Any], once: bool, interval: float | None, confirm_live: bool) -> int:
    """Main trading loop."""
    settlement = Path(config.get("settlement_file", "settlement.jsonl"))
    settlement.parent.mkdir(parents=True, exist_ok=True)
    settlement.touch(exist_ok=True)

    mode = str(config.get("mode", "paper")).lower().strip()
    if mode not in ("paper", "live"):
        raise ValueError(f"Unsupported mode: {mode}")
    if mode == "live" and not confirm_live:
        raise RuntimeError("Live mode requires --confirm-live flag.")

    # Initialize portfolio
    initial_equity = float(config["risk"]["initial_equity"])
    portfolio = PortfolioState(
        equity=initial_equity,
        cash=initial_equity,
        positions={},
        peak_equity=initial_equity,
        daily_pnl=0.0,
        last_prices={},
    )

    # Initialize components
    strategies = _build_strategies(config)
    if not strategies:
        LOGGER.error("No strategies enabled. Check config.strategies.")
        return 1

    risk_mgr = RiskManager(config)

    live_client = None
    if mode == "live":
        try:
            live_client = create_live_client(config)
            LOGGER.info("Live client initialized.")
        except Exception as exc:
            LOGGER.error("Live client init failed: %s", exc)
            write_event(settlement, {"type": "halt", "reason": "live_client_init_failed", "error": str(exc)})
            return 1

    last_position_sync = 0.0
    position_sync_interval = 30.0  # Re-sync positions every 30s
    cooldowns: dict[str, float] = {}
    sleep_sec = float(interval if interval is not None else config.get("run_interval_sec", 2.0))
    kill_switch = Path(str(config.get("kill_switch_file", ".halt")))

    LOGGER.info("Engine started: mode=%s strategies=%s interval=%.1fs",
                mode, [s.name for s in strategies], sleep_sec)

    try:
        while True:
            # Kill switch
            if kill_switch.exists():
                write_event(settlement, {"type": "halt", "reason": "kill_switch"})
                LOGGER.warning("Kill switch detected. Stopping.")
                return 0

            # Fetch markets
            try:
                markets = fetch_markets(config)
            except Exception as exc:
                LOGGER.warning("Market fetch failed: %s", exc)
                if once:
                    return 0
                time.sleep(sleep_sec)
                continue

            if not markets:
                LOGGER.warning("No markets after filtering.")
                if once:
                    return 0
                time.sleep(sleep_sec)
                continue

            # Sync live positions periodically
            now = time.time()
            if mode == "live" and now - last_position_sync >= position_sync_interval and config.get("live", {}).get("sync_existing_positions", True):
                try:
                    synced = sync_positions(live_client, config, markets)
                    for token_id, pos in synced.items():
                        if abs(pos.size) > 1e-12:
                            portfolio.positions[token_id] = pos
                    last_position_sync = now
                    write_event(settlement, {
                        "type": "position_sync",
                        "exec_mode": "live",
                        "synced_count": len([p for p in synced.values() if abs(p.size) > 1e-12]),
                    })
                except Exception as exc:
                    LOGGER.warning("Position sync failed: %s", exc)
                    last_position_sync = now  # Don't retry immediately

            # Update prices
            for m in markets:
                portfolio.last_prices[m.token_id] = m.mid_price
            portfolio.update_equity()

            # Log ticks
            for m in markets:
                _log_tick(settlement, m)

            # Run all strategies
            all_signals = []
            strategies_used = []
            for strategy in strategies:
                try:
                    signals = strategy.analyze(markets, portfolio)
                    if signals:
                        all_signals.extend(signals)
                        strategies_used.append(strategy.name)
                except Exception as exc:
                    LOGGER.warning("Strategy %s error: %s", strategy.name, exc)

            # Risk filter: signals -> intents
            intents, halted = risk_mgr.signals_to_intents(all_signals, portfolio)
            if halted:
                write_event(settlement, {"type": "halt", "reason": "daily_loss_limit"})
                LOGGER.warning("Daily loss limit reached. Halting.")
                return 0

            # Execute
            if mode == "paper":
                executed = execute_paper(intents, markets, portfolio, settlement)
            else:
                executed = execute_live(intents, live_client, config, portfolio, settlement, cooldowns)

            # Update equity after fills
            portfolio.update_equity()

            # Log snapshots
            _log_positions(settlement, portfolio)
            _log_equity(settlement, portfolio, mode, False)
            _log_loop(settlement, mode, len(markets), len(all_signals), len(intents), executed, strategies_used)

            LOGGER.info(
                "mode=%s markets=%d signals=%d intents=%d executed=%d equity=%.2f",
                mode, len(markets), len(all_signals), len(intents), executed, portfolio.equity,
            )

            if once:
                return 0
            time.sleep(max(0.1, sleep_sec))

    except KeyboardInterrupt:
        LOGGER.info("Interrupted by user.")
        return 0
