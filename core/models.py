"""Core data models for the trading engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class SignalType(Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass
class Market:
    token_id: str
    condition_id: str
    question: str
    best_bid: float
    best_ask: float
    volume_24h: float
    liquidity: float
    end_time: str | None = None
    minutes_to_expiry: float | None = None
    complement_token_id: str | None = None

    @property
    def mid_price(self) -> float:
        return (self.best_bid + self.best_ask) / 2.0

    @property
    def spread(self) -> float:
        return self.best_ask - self.best_bid


@dataclass
class Signal:
    type: SignalType
    token_id: str
    price: float
    size: float
    confidence: float  # 0.0 - 1.0
    strategy: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class OrderIntent:
    token_id: str
    side: str  # "buy" or "sell"
    price: float
    size: float
    strategy: str
    confidence: float
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def notional(self) -> float:
        return self.price * self.size


@dataclass
class Position:
    size: float = 0.0
    avg_entry: float = 0.0
    realized_pnl: float = 0.0

    def apply_fill(self, side: str, price: float, qty: float) -> float:
        """Apply a fill and return realized PnL from this fill."""
        signed = qty if side == "buy" else -qty

        if self.size == 0:
            self.size = signed
            self.avg_entry = price
            return 0.0

        # Same direction: average in
        if (self.size > 0 and signed > 0) or (self.size < 0 and signed < 0):
            total = abs(self.size) + abs(signed)
            self.avg_entry = (
                abs(self.size) * self.avg_entry + abs(signed) * price
            ) / max(total, 1e-12)
            self.size += signed
            return 0.0

        # Opposite direction: close then maybe flip
        closing_qty = min(abs(self.size), abs(signed))
        if self.size > 0:
            realized = (price - self.avg_entry) * closing_qty
        else:
            realized = (self.avg_entry - price) * closing_qty

        remaining = self.size + signed
        self.realized_pnl += realized

        if remaining == 0:
            self.size = 0.0
            self.avg_entry = 0.0
        elif abs(signed) > abs(self.size):
            # Flipped direction
            self.size = remaining
            self.avg_entry = price
        else:
            self.size = remaining

        return realized


@dataclass
class PortfolioState:
    equity: float
    cash: float
    positions: dict[str, Position]
    peak_equity: float
    daily_pnl: float
    last_prices: dict[str, float]

    @property
    def drawdown(self) -> float:
        if self.peak_equity <= 0:
            return 0.0
        return (self.peak_equity - self.equity) / self.peak_equity

    def unrealized_pnl(self) -> float:
        total = 0.0
        for token_id, pos in self.positions.items():
            if pos.size == 0:
                continue
            mark = self.last_prices.get(token_id, pos.avg_entry)
            if pos.size > 0:
                total += (mark - pos.avg_entry) * pos.size
            else:
                total += (pos.avg_entry - mark) * abs(pos.size)
        return total

    def realized_pnl(self) -> float:
        return sum(p.realized_pnl for p in self.positions.values())

    def update_equity(self) -> None:
        self.equity = self.cash + self.unrealized_pnl() + self.realized_pnl()
        self.peak_equity = max(self.peak_equity, self.equity)

    def market_exposure(self, token_id: str) -> float:
        pos = self.positions.get(token_id)
        if not pos:
            return 0.0
        price = self.last_prices.get(token_id, pos.avg_entry)
        return abs(pos.size * price)
