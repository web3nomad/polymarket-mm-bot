"""Risk management: Kelly sizing, drawdown guards, exposure limits."""

from __future__ import annotations

import logging
from typing import Any

from core.models import OrderIntent, PortfolioState, Signal, SignalType

LOGGER = logging.getLogger("polymarket.risk")


class RiskManager:
    def __init__(self, config: dict[str, Any]) -> None:
        risk = config.get("risk", {})
        self.initial_equity = float(risk.get("initial_equity", 1000))
        self.max_order_notional = float(risk.get("max_order_notional", 20))
        self.max_market_exposure = float(risk.get("max_market_exposure", 100))
        self.daily_loss_limit = float(risk.get("daily_loss_limit", 50))
        self.use_kelly = bool(risk.get("use_kelly", True))
        self.kelly_fraction = float(risk.get("kelly_fraction", 0.5))
        self.min_confidence = float(risk.get("min_confidence", 0.3))
        self.max_orders_per_loop = int(config.get("max_orders_per_loop", 20))

        live = config.get("live", {})
        self.mode = str(config.get("mode", "paper")).lower()
        self.allow_sell = bool(live.get("allow_sell", False))
        self.trade_side = str(live.get("trade_side", "buy")).lower()
        self.min_order_usd = max(
            float(live.get("min_order_usd", 0)),
            float(live.get("exchange_min_order_usd", 1.0)),
        )
        self.exchange_min_shares = float(live.get("exchange_min_shares", 5))

    def is_halted(self, portfolio: PortfolioState) -> bool:
        return portfolio.equity <= self.initial_equity - self.daily_loss_limit

    def kelly_size(self, signal: Signal) -> float:
        """Calculate position size using half-Kelly criterion.

        For market_making signals, confidence represents edge quality (not
        directional win probability), so we scale the raw size by confidence
        instead of using the full Kelly formula.

        For directional strategies, Kelly formula:
            f* = (p * b - q) / b
        where p = win probability, b = payout odds, q = 1 - p.
        """
        if not self.use_kelly or signal.confidence <= 0:
            return signal.size

        # Market making: edge-based sizing (not directional Kelly)
        if signal.strategy == "market_making":
            scaled = signal.size * signal.confidence * self.kelly_fraction * 2
            dollar_cap = self.max_order_notional / signal.price if signal.price > 0 else 0
            return min(max(scaled, 1.0), dollar_cap)

        # Directional strategies: full Kelly
        p = signal.confidence
        q = 1.0 - p

        if signal.type == SignalType.BUY:
            b = (1.0 - signal.price) / signal.price if signal.price > 0 else 0
        else:
            b = signal.price / (1.0 - signal.price) if signal.price < 1 else 0

        if b <= 0:
            return 0.0

        kelly = (p * b - q) / b
        if kelly <= 0:
            return 0.0

        kelly *= self.kelly_fraction
        dollar_size = min(kelly * self.initial_equity, self.max_order_notional)
        shares = dollar_size / signal.price if signal.price > 0 else 0
        return max(0.0, shares)

    def signals_to_intents(
        self,
        signals: list[Signal],
        portfolio: PortfolioState,
    ) -> tuple[list[OrderIntent], bool]:
        """Convert signals to risk-filtered order intents.

        Returns (intents, halted).
        """
        if self.is_halted(portfolio):
            return [], True

        # Filter and sort by confidence (highest first)
        valid = [s for s in signals if s.type != SignalType.HOLD and s.confidence >= self.min_confidence]
        valid.sort(key=lambda s: s.confidence, reverse=True)

        intents: list[OrderIntent] = []
        projected_exposure: dict[str, float] = {}

        for signal in valid:
            side = signal.type.value  # "buy" or "sell"

            # Side gating for live mode
            if self.mode == "live":
                if side == "sell" and not self.allow_sell:
                    continue
                if self.trade_side not in (side, "both"):
                    continue

            # Calculate size (Kelly or raw)
            size = self.kelly_size(signal) if self.use_kelly else signal.size
            if size <= 0:
                continue

            # Enforce exchange minimum shares
            if self.mode == "live" and size < self.exchange_min_shares:
                size = self.exchange_min_shares

            notional = signal.price * size

            # Notional bounds
            if notional > self.max_order_notional:
                size = self.max_order_notional / signal.price
                notional = self.max_order_notional

            # Re-check min shares after notional cap
            if self.mode == "live" and size < self.exchange_min_shares:
                continue

            if self.mode == "live" and notional < self.min_order_usd:
                continue

            # Market exposure check
            current_exp = projected_exposure.get(
                signal.token_id, portfolio.market_exposure(signal.token_id)
            )
            if current_exp + notional > self.max_market_exposure:
                continue

            projected_exposure[signal.token_id] = current_exp + notional
            intents.append(
                OrderIntent(
                    token_id=signal.token_id,
                    side=side,
                    price=signal.price,
                    size=round(size, 4),
                    strategy=signal.strategy,
                    confidence=signal.confidence,
                    metadata=signal.metadata,
                )
            )

            if len(intents) >= self.max_orders_per_loop:
                break

        return intents, False
