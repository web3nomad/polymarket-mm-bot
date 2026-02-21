from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class RiskConfig:
    total_capital: float
    strategy_capital: float
    per_trade_risk_pct: float
    market_exposure_pct: float
    theme_exposure_pct: float
    daily_drawdown_stop_pct: float
    max_open_orders: int


@dataclass(slots=True)
class StrategyConfig:
    quote_refresh_sec: float
    quote_half_spread_bps: float
    inventory_skew_bps_per_contract: float
    max_inventory_contracts: float


@dataclass(slots=True)
class MarketSelectionConfig:
    top_n: int
    min_liquidity: float
    max_spread_bps: float
    min_minutes_to_expiry: int


@dataclass(slots=True)
class ExecutionConfig:
    mode: str
    default_order_size: float
    slippage_bps: float


@dataclass(slots=True)
class TelemetryConfig:
    db_path: str
    persist_positions_every_loop: bool


@dataclass(slots=True)
class RuntimeConfig:
    dry_run: bool = True
    log_level: str = "INFO"


@dataclass(slots=True)
class AppConfig:
    risk: RiskConfig
    strategy: StrategyConfig
    market_selection: MarketSelectionConfig
    execution: ExecutionConfig
    telemetry: TelemetryConfig
    runtime: RuntimeConfig
