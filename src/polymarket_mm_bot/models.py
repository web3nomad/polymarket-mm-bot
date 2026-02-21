from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

Side = Literal["buy", "sell"]
OrderStatus = Literal["open", "filled", "cancelled", "rejected"]


@dataclass(slots=True)
class MarketSnapshot:
    ts: datetime
    market_id: str
    question: str
    theme: str
    liquidity: float
    best_bid: float
    best_ask: float
    mid: float
    spread_bps: float
    minutes_to_expiry: float


@dataclass(slots=True)
class QuoteIntent:
    market_id: str
    side: Side
    price: float
    size: float
    reason: str = "mm_quote"


@dataclass(slots=True)
class Order:
    order_id: str
    ts: datetime
    market_id: str
    side: Side
    price: float
    size: float
    status: OrderStatus
    reason: str = ""


@dataclass(slots=True)
class Fill:
    fill_id: str
    order_id: str
    ts: datetime
    market_id: str
    side: Side
    price: float
    size: float
    slippage_bps: float


@dataclass(slots=True)
class Position:
    market_id: str
    qty: float = 0.0
    avg_price: float = 0.0
    realized_pnl: float = 0.0
    updated_at: datetime | None = None


@dataclass(slots=True)
class PortfolioState:
    cash: float
    positions: dict[str, Position] = field(default_factory=dict)
    open_orders: dict[str, Order] = field(default_factory=dict)
    realized_pnl: float = 0.0


@dataclass(slots=True)
class RiskContext:
    equity: float
    start_of_day_equity: float
    open_order_count: int
    market_exposure_by_id: dict[str, float]
    theme_exposure_by_name: dict[str, float]
