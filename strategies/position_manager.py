"""Position manager: take-profit and stop-loss for existing positions."""

from __future__ import annotations

from core.models import Market, PortfolioState, Signal, SignalType
from strategies.base import BaseStrategy


class PositionManagerStrategy(BaseStrategy):
    name = "position_manager"

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self.take_profit_pct = float(config.get("take_profit_pct", 0.10))  # +10%
        self.stop_loss_pct = float(config.get("stop_loss_pct", 0.15))      # -15%
        self.min_position_size = float(config.get("min_position_size", 1.0))

    def analyze(self, markets: list[Market], portfolio: PortfolioState) -> list[Signal]:
        signals: list[Signal] = []
        by_token = {m.token_id: m for m in markets}

        for token_id, pos in portfolio.positions.items():
            if pos.size < self.min_position_size:
                continue

            m = by_token.get(token_id)
            if not m or m.best_bid <= 0 or pos.avg_entry <= 0:
                continue

            current_price = m.best_bid  # sell at bid
            pnl_pct = (current_price - pos.avg_entry) / pos.avg_entry

            # Take profit
            if pnl_pct >= self.take_profit_pct:
                signals.append(Signal(
                    type=SignalType.SELL,
                    token_id=token_id,
                    price=current_price,
                    size=pos.size,
                    confidence=min(0.5 + pnl_pct, 1.0),  # higher profit = higher confidence
                    strategy=self.name,
                    metadata={"reason": "take_profit", "pnl_pct": round(pnl_pct, 4)},
                ))

            # Stop loss
            elif pnl_pct <= -self.stop_loss_pct:
                signals.append(Signal(
                    type=SignalType.SELL,
                    token_id=token_id,
                    price=current_price,
                    size=pos.size,
                    confidence=min(0.5 + abs(pnl_pct), 1.0),
                    strategy=self.name,
                    metadata={"reason": "stop_loss", "pnl_pct": round(pnl_pct, 4)},
                ))

        return signals
