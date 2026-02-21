from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from polymarket_mm_bot.models import Fill, MarketSnapshot, Order, PortfolioState, Position, QuoteIntent


@dataclass(slots=True)
class SubmitResult:
    orders: list[Order]
    fills: list[Fill]


class PaperExecutionEngine:
    def __init__(self, *, initial_cash: float, slippage_bps: float) -> None:
        self.state = PortfolioState(cash=initial_cash)
        self.slippage_bps = max(0.0, slippage_bps)

    @property
    def positions(self) -> dict[str, Position]:
        return self.state.positions

    @property
    def open_orders(self) -> dict[str, Order]:
        return self.state.open_orders

    @property
    def realized_pnl(self) -> float:
        return self.state.realized_pnl

    def submit_intents(self, intents: list[QuoteIntent], snapshots_by_market: dict[str, MarketSnapshot]) -> SubmitResult:
        now = datetime.now(tz=UTC)
        orders: list[Order] = []
        fills: list[Fill] = []

        for intent in intents:
            order = Order(
                order_id=str(uuid.uuid4()),
                ts=now,
                market_id=intent.market_id,
                side=intent.side,
                price=float(intent.price),
                size=float(intent.size),
                status="open",
                reason=intent.reason,
            )
            orders.append(order)

            snap = snapshots_by_market.get(order.market_id)
            if snap is None:
                order.status = "rejected"
                order.reason = "missing_snapshot"
                continue

            fill = self._try_fill(order, snap, now)
            if fill is None:
                self.state.open_orders[order.order_id] = order
                continue

            fills.append(fill)
            order.status = "filled"
            self._apply_fill(fill)

        return SubmitResult(orders=orders, fills=fills)

    def process_open_orders(self, snapshots_by_market: dict[str, MarketSnapshot]) -> list[Fill]:
        now = datetime.now(tz=UTC)
        fills: list[Fill] = []
        to_remove: list[str] = []

        for order_id, order in list(self.state.open_orders.items()):
            snap = snapshots_by_market.get(order.market_id)
            if snap is None:
                continue
            fill = self._try_fill(order, snap, now)
            if fill is None:
                continue
            fills.append(fill)
            order.status = "filled"
            self._apply_fill(fill)
            to_remove.append(order_id)

        for order_id in to_remove:
            self.state.open_orders.pop(order_id, None)

        return fills

    def mark_to_market(self, snapshots_by_market: dict[str, MarketSnapshot]) -> tuple[float, float, float]:
        unrealized = 0.0
        for market_id, pos in self.state.positions.items():
            snap = snapshots_by_market.get(market_id)
            if snap is None:
                continue
            unrealized += (snap.mid - pos.avg_price) * pos.qty

        equity = self.state.cash + unrealized + self.state.realized_pnl
        return equity, self.state.cash, unrealized

    def market_exposure(self, snapshots_by_market: dict[str, MarketSnapshot]) -> dict[str, float]:
        out: dict[str, float] = {}
        for market_id, pos in self.state.positions.items():
            snap = snapshots_by_market.get(market_id)
            if snap is None:
                continue
            out[market_id] = abs(pos.qty * snap.mid)
        return out

    def theme_exposure(
        self,
        snapshots_by_market: dict[str, MarketSnapshot],
    ) -> dict[str, float]:
        out: dict[str, float] = {}
        for market_id, pos in self.state.positions.items():
            snap = snapshots_by_market.get(market_id)
            if snap is None:
                continue
            value = abs(pos.qty * snap.mid)
            out[snap.theme] = out.get(snap.theme, 0.0) + value
        return out

    def _try_fill(self, order: Order, snap: MarketSnapshot, ts: datetime) -> Fill | None:
        if order.side == "buy" and order.price >= snap.best_ask:
            fill_px = snap.best_ask * (1.0 + self.slippage_bps / 10000.0)
        elif order.side == "sell" and order.price <= snap.best_bid:
            fill_px = snap.best_bid * (1.0 - self.slippage_bps / 10000.0)
        else:
            return None

        return Fill(
            fill_id=str(uuid.uuid4()),
            order_id=order.order_id,
            ts=ts,
            market_id=order.market_id,
            side=order.side,
            price=round(fill_px, 6),
            size=order.size,
            slippage_bps=self.slippage_bps,
        )

    def _apply_fill(self, fill: Fill) -> None:
        signed_qty = fill.size if fill.side == "buy" else -fill.size
        cash_delta = -fill.price * fill.size if fill.side == "buy" else fill.price * fill.size
        self.state.cash += cash_delta

        pos = self.state.positions.get(fill.market_id)
        if pos is None:
            pos = Position(market_id=fill.market_id)
            self.state.positions[fill.market_id] = pos

        realized = _realized_on_fill(pos.qty, pos.avg_price, signed_qty, fill.price)
        self.state.realized_pnl += realized
        pos.realized_pnl += realized

        new_qty = pos.qty + signed_qty
        if abs(new_qty) < 1e-12:
            pos.qty = 0.0
            pos.avg_price = 0.0
        elif pos.qty == 0 or (pos.qty > 0 and signed_qty > 0) or (pos.qty < 0 and signed_qty < 0):
            total_notional = abs(pos.qty) * pos.avg_price + abs(signed_qty) * fill.price
            pos.qty = new_qty
            pos.avg_price = total_notional / abs(new_qty)
        else:
            if (pos.qty > 0 > new_qty) or (pos.qty < 0 < new_qty):
                pos.avg_price = fill.price
            pos.qty = new_qty

        pos.updated_at = fill.ts


def _realized_on_fill(current_qty: float, avg_price: float, signed_fill_qty: float, fill_price: float) -> float:
    if current_qty == 0:
        return 0.0
    if current_qty > 0 and signed_fill_qty < 0:
        closing = min(abs(signed_fill_qty), abs(current_qty))
        return (fill_price - avg_price) * closing
    if current_qty < 0 and signed_fill_qty > 0:
        closing = min(abs(signed_fill_qty), abs(current_qty))
        return (avg_price - fill_price) * closing
    return 0.0
