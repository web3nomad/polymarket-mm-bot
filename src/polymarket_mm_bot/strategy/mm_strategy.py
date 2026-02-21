from __future__ import annotations

from polymarket_mm_bot.config.models import ExecutionConfig, StrategyConfig
from polymarket_mm_bot.models import MarketSnapshot, Position, QuoteIntent


class MarketMakingStrategy:
    def __init__(self, cfg: StrategyConfig, exec_cfg: ExecutionConfig) -> None:
        self.cfg = cfg
        self.exec_cfg = exec_cfg

    def generate_intents(
        self,
        snapshots: list[MarketSnapshot],
        positions: dict[str, Position],
    ) -> list[QuoteIntent]:
        intents: list[QuoteIntent] = []
        for snap in snapshots:
            pos_qty = positions.get(snap.market_id, Position(market_id=snap.market_id)).qty
            intents.extend(self._market_quotes(snap, pos_qty))
        return intents

    def _market_quotes(self, snap: MarketSnapshot, pos_qty: float) -> list[QuoteIntent]:
        if self.cfg.max_inventory_contracts <= 0:
            return []

        inv_util = min(abs(pos_qty) / self.cfg.max_inventory_contracts, 1.0)
        size = round(self.exec_cfg.default_order_size * (1.0 - inv_util), 4)
        if size <= 0.0:
            return []

        half_spread_bps = self.cfg.quote_half_spread_bps
        skew_bps = pos_qty * self.cfg.inventory_skew_bps_per_contract

        bid_bps = max(0.1, half_spread_bps + skew_bps)
        ask_bps = max(0.1, half_spread_bps - skew_bps)

        bid_px = _clamp(round(snap.mid * (1.0 - bid_bps / 10000.0), 5), 0.001, 0.999)
        ask_px = _clamp(round(snap.mid * (1.0 + ask_bps / 10000.0), 5), 0.001, 0.999)

        if bid_px >= ask_px:
            ask_px = min(0.999, bid_px + 0.0005)

        return [
            QuoteIntent(market_id=snap.market_id, side="buy", price=bid_px, size=size, reason="mm_bid"),
            QuoteIntent(market_id=snap.market_id, side="sell", price=ask_px, size=size, reason="mm_ask"),
        ]


def _clamp(value: float, low: float, high: float) -> float:
    return min(high, max(low, value))
