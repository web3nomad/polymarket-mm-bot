"""Arbitrage strategy: exploit YES + NO pricing inefficiencies."""

from __future__ import annotations

from typing import Any

from core.models import Market, PortfolioState, Signal, SignalType
from strategies.base import BaseStrategy


class ArbitrageStrategy(BaseStrategy):
    name = "arbitrage"

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self.threshold = float(config.get("threshold", 0.02))
        self.order_size = float(config.get("order_size", 50.0))

    def analyze(self, markets: list[Market], portfolio: PortfolioState) -> list[Signal]:
        signals: list[Signal] = []

        # Group markets by condition_id to find YES/NO pairs
        by_condition: dict[str, list[Market]] = {}
        for m in markets:
            by_condition.setdefault(m.condition_id, []).append(m)

        for condition_id, pair in by_condition.items():
            if len(pair) < 2:
                # Single market: check if best_ask for YES + implied NO > 1
                m = pair[0]
                total = m.best_ask + (1 - m.best_bid)
                if total > 1.0 + self.threshold:
                    profit_pct = (total - 1.0) * 100
                    confidence = min(profit_pct / 10.0, 1.0)
                    # Buy the cheaper side
                    if m.best_ask < 0.5:
                        signals.append(Signal(
                            type=SignalType.BUY,
                            token_id=m.token_id,
                            price=m.best_ask,
                            size=self.order_size,
                            confidence=confidence,
                            strategy=self.name,
                            metadata={
                                "arb_type": "overpriced_single",
                                "total": round(total, 4),
                                "profit_pct": round(profit_pct, 2),
                            },
                        ))
                continue

            # Two markets in same condition: check cross-market arb
            m1, m2 = pair[0], pair[1]
            total_ask = m1.best_ask + m2.best_ask
            total_bid = m1.best_bid + m2.best_bid

            # Overpriced: sum of asks < 1 (can buy both and guarantee profit)
            if total_ask < 1.0 - self.threshold:
                profit_pct = (1.0 - total_ask) * 100
                confidence = min(profit_pct / 10.0, 1.0)
                for m in [m1, m2]:
                    signals.append(Signal(
                        type=SignalType.BUY,
                        token_id=m.token_id,
                        price=m.best_ask,
                        size=self.order_size,
                        confidence=confidence,
                        strategy=self.name,
                        metadata={
                            "arb_type": "underpriced_pair",
                            "total_ask": round(total_ask, 4),
                            "profit_pct": round(profit_pct, 2),
                        },
                    ))

            # Underpriced: sum of bids > 1 (can sell both)
            if total_bid > 1.0 + self.threshold:
                profit_pct = (total_bid - 1.0) * 100
                confidence = min(profit_pct / 10.0, 1.0)
                for m in [m1, m2]:
                    signals.append(Signal(
                        type=SignalType.SELL,
                        token_id=m.token_id,
                        price=m.best_bid,
                        size=self.order_size,
                        confidence=confidence,
                        strategy=self.name,
                        metadata={
                            "arb_type": "overpriced_pair",
                            "total_bid": round(total_bid, 4),
                            "profit_pct": round(profit_pct, 2),
                        },
                    ))

        return signals
