from __future__ import annotations

import logging
import time
import uuid
from pathlib import Path

from polymarket_mm_bot.config.models import AppConfig
from polymarket_mm_bot.execution.client import PaperExecutionEngine
from polymarket_mm_bot.market_data.ws_client import GammaPollingMarketDataClient, MarketDataClient, SnapshotReplayClient
from polymarket_mm_bot.models import MarketSnapshot, QuoteIntent, RiskContext
from polymarket_mm_bot.persistence.sqlite_store import SqliteStore
from polymarket_mm_bot.risk.manager import RiskManager
from polymarket_mm_bot.strategy.mm_strategy import MarketMakingStrategy

LOGGER = logging.getLogger(__name__)


def run_bot(
    *,
    config: AppConfig,
    config_path: Path,
    once: bool,
    interval_sec: float,
    snapshots_file: Path | None = None,
) -> int:
    if config.execution.mode != "paper":
        LOGGER.warning("Only paper mode is implemented. Forcing paper mode.")

    store = SqliteStore(config.telemetry.db_path)
    run_id = f"paper-{uuid.uuid4().hex[:10]}"
    store.start_run(run_id=run_id, mode="paper", config_path=str(config_path))

    market_data: MarketDataClient
    if snapshots_file is not None:
        market_data = SnapshotReplayClient(str(snapshots_file))
        LOGGER.info("Running in backtest-lite replay mode from %s", snapshots_file)
    else:
        market_data = GammaPollingMarketDataClient(config.market_selection)

    execution = PaperExecutionEngine(
        initial_cash=config.risk.strategy_capital,
        slippage_bps=config.execution.slippage_bps,
    )
    strategy = MarketMakingStrategy(config.strategy, config.execution)
    risk_manager = RiskManager(config.risk)

    start_of_day_equity = config.risk.strategy_capital
    halted = False

    try:
        while True:
            snapshots = market_data.get_snapshots()
            snapshots_by_market = {s.market_id: s for s in snapshots}

            if not snapshots:
                LOGGER.warning("No market snapshots this loop. Skipping safely.")
                if snapshots_file is not None:
                    LOGGER.info("Replay finished (no more snapshots).")
                    break
                if once:
                    break
                time.sleep(max(0.05, interval_sec))
                continue

            fills_from_resting = execution.process_open_orders(snapshots_by_market)
            if fills_from_resting:
                store.record_fills(run_id, fills_from_resting)

            equity, cash, unrealized = execution.mark_to_market(snapshots_by_market)
            risk_ctx = RiskContext(
                equity=equity,
                start_of_day_equity=start_of_day_equity,
                open_order_count=len(execution.open_orders),
                market_exposure_by_id=execution.market_exposure(snapshots_by_market),
                theme_exposure_by_name=execution.theme_exposure(snapshots_by_market),
            )

            raw_intents = strategy.generate_intents(snapshots, execution.positions)
            allowed_intents = _filter_intents(raw_intents, snapshots_by_market, risk_manager, risk_ctx)

            if not halted and not allowed_intents and _drawdown_or_limit_halted(risk_manager, risk_ctx):
                halted = True
                LOGGER.warning("Risk halt triggered; bot will stop placing new orders.")

            submit_result = execution.submit_intents(allowed_intents, snapshots_by_market)
            store.record_orders(run_id, submit_result.orders)
            store.record_fills(run_id, submit_result.fills)

            equity, cash, unrealized = execution.mark_to_market(snapshots_by_market)
            store.record_equity(run_id, equity, cash, execution.realized_pnl, unrealized)
            if config.telemetry.persist_positions_every_loop:
                store.record_positions(run_id, execution.positions)

            LOGGER.info(
                "loop markets=%s intents=%s orders=%s fills=%s open_orders=%s equity=%.2f",
                len(snapshots),
                len(raw_intents),
                len(submit_result.orders),
                len(submit_result.fills),
                len(execution.open_orders),
                equity,
            )

            if once:
                break
            time.sleep(max(0.05, interval_sec))
    except KeyboardInterrupt:
        LOGGER.info("Interrupted by user.")
    finally:
        store.close()

    return 0


def report(db_path: str) -> dict:
    store = SqliteStore(db_path)
    try:
        return store.report_today()
    finally:
        store.close()


def _filter_intents(
    intents: list[QuoteIntent],
    snapshots_by_market: dict[str, MarketSnapshot],
    risk_manager: RiskManager,
    ctx: RiskContext,
) -> list[QuoteIntent]:
    allowed: list[QuoteIntent] = []
    local_ctx = RiskContext(
        equity=ctx.equity,
        start_of_day_equity=ctx.start_of_day_equity,
        open_order_count=ctx.open_order_count,
        market_exposure_by_id=dict(ctx.market_exposure_by_id),
        theme_exposure_by_name=dict(ctx.theme_exposure_by_name),
    )

    for intent in intents:
        snap = snapshots_by_market.get(intent.market_id)
        if snap is None:
            continue
        ok, reason = risk_manager.allow_intent(intent, snap, local_ctx)
        if not ok:
            LOGGER.debug("Risk blocked intent market=%s side=%s reason=%s", intent.market_id, intent.side, reason)
            continue

        trade_notional = abs(intent.price * intent.size)
        local_ctx.open_order_count += 1
        local_ctx.market_exposure_by_id[intent.market_id] = (
            local_ctx.market_exposure_by_id.get(intent.market_id, 0.0) + trade_notional
        )
        local_ctx.theme_exposure_by_name[snap.theme] = local_ctx.theme_exposure_by_name.get(snap.theme, 0.0) + trade_notional
        allowed.append(intent)

    return allowed


def _drawdown_or_limit_halted(risk_manager: RiskManager, ctx: RiskContext) -> bool:
    return risk_manager._is_drawdown_halted(ctx) or ctx.open_order_count >= risk_manager.cfg.max_open_orders
