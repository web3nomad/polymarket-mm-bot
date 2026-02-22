"""Momentum strategy: trade based on price direction, volume, and orderbook imbalance."""

from __future__ import annotations

import logging
from typing import Any

from core.models import Market, PortfolioState, Signal, SignalType
from strategies.base import BaseStrategy

LOGGER = logging.getLogger("polymarket.momentum")


class MomentumStrategy(BaseStrategy):
    name = "momentum"

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self.buy_threshold = float(config.get("buy_threshold", 0.3))
        self.sell_threshold = float(config.get("sell_threshold", -0.3))
        self.order_size = float(config.get("order_size", 20.0))
        # Rolling price history per token (populated by engine on each tick)
        self.price_history: dict[str, list[float]] = {}
        self.volume_history: dict[str, list[float]] = {}

    def update_history(self, markets: list[Market]) -> None:
        """Call each tick to accumulate price/volume data."""
        for m in markets:
            self.price_history.setdefault(m.token_id, []).append(m.mid_price)
            self.volume_history.setdefault(m.token_id, []).append(m.volume_24h)
            # Keep last 100 ticks
            if len(self.price_history[m.token_id]) > 100:
                self.price_history[m.token_id] = self.price_history[m.token_id][-100:]
                self.volume_history[m.token_id] = self.volume_history[m.token_id][-100:]

    def analyze(self, markets: list[Market], portfolio: PortfolioState) -> list[Signal]:
        self.update_history(markets)
        signals: list[Signal] = []

        for m in markets:
            prices = self.price_history.get(m.token_id, [])
            if len(prices) < 5:
                continue  # Need at least 5 data points

            # Price momentum: compare recent vs older average
            recent = prices[-3:]
            older = prices[-min(len(prices), 10):-3] if len(prices) > 3 else prices[:1]
            if not older:
                continue

            recent_avg = sum(recent) / len(recent)
            older_avg = sum(older) / len(older)
            price_change = (recent_avg - older_avg) / max(older_avg, 0.01)

            # Volume momentum
            volumes = self.volume_history.get(m.token_id, [])
            vol_recent = sum(volumes[-3:]) / max(len(volumes[-3:]), 1)
            vol_older = sum(volumes[-10:-3]) / max(len(volumes[-10:-3]), 1) if len(volumes) > 3 else vol_recent
            volume_ratio = (vol_recent / max(vol_older, 1)) - 1.0

            # Orderbook imbalance (using bid/ask as proxy)
            total = m.best_bid + (1 - m.best_ask)
            imbalance = (m.best_bid - (1 - m.best_ask)) / max(total, 0.01)

            # Composite score
            score = price_change * 0.4 + volume_ratio * 0.3 + imbalance * 0.3

            if score > self.buy_threshold:
                confidence = min(abs(score), 1.0)
                signals.append(Signal(
                    type=SignalType.BUY,
                    token_id=m.token_id,
                    price=m.best_ask,
                    size=self.order_size,
                    confidence=confidence,
                    strategy=self.name,
                    metadata={
                        "score": round(score, 4),
                        "price_change": round(price_change, 4),
                        "volume_ratio": round(volume_ratio, 4),
                        "imbalance": round(imbalance, 4),
                    },
                ))
            elif score < self.sell_threshold:
                confidence = min(abs(score), 1.0)
                signals.append(Signal(
                    type=SignalType.SELL,
                    token_id=m.token_id,
                    price=m.best_bid,
                    size=self.order_size,
                    confidence=confidence,
                    strategy=self.name,
                    metadata={
                        "score": round(score, 4),
                        "price_change": round(price_change, 4),
                        "volume_ratio": round(volume_ratio, 4),
                        "imbalance": round(imbalance, 4),
                    },
                ))

        return signals
