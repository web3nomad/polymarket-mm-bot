"""Market making strategy: quote both sides when spread is wide enough."""

from __future__ import annotations

from typing import Any

from core.models import Market, PortfolioState, Signal, SignalType
from strategies.base import BaseStrategy


class MarketMakingStrategy(BaseStrategy):
    name = "market_making"

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self.min_spread = float(config.get("min_spread", 0.02))
        self.edge = float(config.get("edge", 0.005))
        self.order_size = float(config.get("order_size", 10.0))

    def analyze(self, markets: list[Market], portfolio: PortfolioState) -> list[Signal]:
        signals: list[Signal] = []

        for m in markets:
            if m.spread < self.min_spread:
                continue

            # Confidence: spread / (2 * edge) measures how many edges fit in the spread
            # A 4% spread with 0.5% edge = 4x edge coverage = high confidence
            confidence = min(m.spread / max(self.edge * 4, 0.01), 1.0)

            buy_price = max(0.01, min(0.99, m.best_bid + self.edge))
            sell_price = max(m.best_bid + 0.01, min(0.99, m.best_ask - self.edge))

            # Inventory skew: if we're long, favor selling; if short, favor buying
            pos = portfolio.positions.get(m.token_id)
            buy_confidence = confidence
            sell_confidence = confidence
            if pos and pos.size != 0:
                skew = pos.size * pos.avg_entry / max(portfolio.equity, 1)
                buy_confidence = max(0, confidence * (1 - skew * 2))
                sell_confidence = max(0, confidence * (1 + skew * 2))

            # Buy side: always quote
            signals.append(Signal(
                type=SignalType.BUY,
                token_id=m.token_id,
                price=buy_price,
                size=self.order_size,
                confidence=buy_confidence,
                strategy=self.name,
                metadata={"spread": round(m.spread, 4), "edge": self.edge},
            ))

            # Sell side: only if we have inventory to sell
            if pos and pos.size >= 1.0:
                sell_size = min(self.order_size, pos.size)
                signals.append(Signal(
                    type=SignalType.SELL,
                    token_id=m.token_id,
                    price=sell_price,
                    size=sell_size,
                    confidence=sell_confidence,
                    strategy=self.name,
                    metadata={"spread": round(m.spread, 4), "edge": self.edge},
                ))

        return signals
