"""Mean reversion strategy: trade when price deviates significantly from its mean."""

from __future__ import annotations

import math
from typing import Any

from core.models import Market, PortfolioState, Signal, SignalType
from strategies.base import BaseStrategy


class MeanReversionStrategy(BaseStrategy):
    name = "mean_reversion"

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self.std_threshold = float(config.get("std_threshold", 2.0))
        self.order_size = float(config.get("order_size", 20.0))
        # Accumulated price history per token
        self.price_history: dict[str, list[float]] = {}

    def update_history(self, markets: list[Market]) -> None:
        for m in markets:
            self.price_history.setdefault(m.token_id, []).append(m.mid_price)
            if len(self.price_history[m.token_id]) > 200:
                self.price_history[m.token_id] = self.price_history[m.token_id][-200:]

    def analyze(self, markets: list[Market], portfolio: PortfolioState) -> list[Signal]:
        self.update_history(markets)
        signals: list[Signal] = []

        for m in markets:
            prices = self.price_history.get(m.token_id, [])
            if len(prices) < 20:
                continue  # Need enough data for statistics

            mean = sum(prices) / len(prices)
            variance = sum((p - mean) ** 2 for p in prices) / len(prices)
            std = math.sqrt(variance) if variance > 0 else 0

            if std < 0.001:
                continue  # No meaningful variation

            current = m.mid_price
            z_score = (current - mean) / std

            if z_score < -self.std_threshold:
                # Price significantly below mean — buy expecting reversion
                confidence = min(abs(z_score) / 4.0, 1.0)
                signals.append(Signal(
                    type=SignalType.BUY,
                    token_id=m.token_id,
                    price=m.best_ask,
                    size=self.order_size,
                    confidence=confidence,
                    strategy=self.name,
                    metadata={
                        "z_score": round(z_score, 3),
                        "mean": round(mean, 4),
                        "std": round(std, 4),
                        "current": round(current, 4),
                    },
                ))
            elif z_score > self.std_threshold:
                # Price significantly above mean — sell expecting reversion
                confidence = min(abs(z_score) / 4.0, 1.0)
                signals.append(Signal(
                    type=SignalType.SELL,
                    token_id=m.token_id,
                    price=m.best_bid,
                    size=self.order_size,
                    confidence=confidence,
                    strategy=self.name,
                    metadata={
                        "z_score": round(z_score, 3),
                        "mean": round(mean, 4),
                        "std": round(std, 4),
                        "current": round(current, 4),
                    },
                ))

        return signals
