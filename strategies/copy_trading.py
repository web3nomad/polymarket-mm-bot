"""Copy trading strategy: follow top Polymarket traders."""

from __future__ import annotations

import logging
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any

from core.models import Market, PortfolioState, Signal, SignalType
from services.data_api import get_leaderboard, get_trader_activity
from strategies.base import BaseStrategy

LOGGER = logging.getLogger("polymarket.copy_trading")


class CopyTradingStrategy(BaseStrategy):
    name = "copy_trading"

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self.top_n_traders = int(config.get("top_n_traders", 10))
        self.size_multiplier = float(config.get("size_multiplier", 0.25))
        self.min_trader_profit = float(config.get("min_trader_profit", 500))
        self.activity_limit = int(config.get("activity_limit", 20))
        self.refresh_interval = float(config.get("refresh_interval_sec", 300))
        self.max_trade_age_sec = float(config.get("max_trade_age_sec", 3600))
        self.order_size = float(config.get("order_size", 5))

        # Cache
        self._top_traders: list[str] = []
        self._last_refresh: float = 0
        self._seen_trades: deque[str] = deque(maxlen=5000)
        self._seen_set: set[str] = set()

    def _refresh_traders(self) -> None:
        """Refresh top trader list from leaderboard."""
        now = time.time()
        if now - self._last_refresh < self.refresh_interval and self._top_traders:
            return

        LOGGER.info("Refreshing top trader list...")
        leaderboard = get_leaderboard(limit=50)
        if not leaderboard:
            LOGGER.warning("Empty leaderboard response")
            return

        # Leaderboard fields (from docs): rank, proxyWallet, userName, vol, pnl
        qualified = []
        for trader in leaderboard:
            address = trader.get("proxyWallet") or ""
            if not address:
                continue
            profit = float(trader.get("pnl") or 0)
            if profit >= self.min_trader_profit:
                qualified.append((address, profit))

        qualified.sort(key=lambda x: x[1], reverse=True)
        self._top_traders = [addr for addr, _ in qualified[: self.top_n_traders]]
        self._last_refresh = now

        if self._top_traders:
            LOGGER.info("Tracking %d top traders (top PNL: $%.0f)", len(self._top_traders), qualified[0][1] if qualified else 0)
        else:
            LOGGER.warning("No qualified traders found (min_profit=$%.0f)", self.min_trader_profit)

    def _mark_seen(self, trade_id: str) -> bool:
        """Returns True if already seen."""
        if trade_id in self._seen_set:
            return True
        self._seen_trades.append(trade_id)
        self._seen_set.add(trade_id)
        # Keep set in sync with deque maxlen
        if len(self._seen_set) > len(self._seen_trades) + 100:
            self._seen_set = set(self._seen_trades)
        return False

    def analyze(self, markets: list[Market], portfolio: PortfolioState) -> list[Signal]:
        self._refresh_traders()
        if not self._top_traders:
            return []

        signals: list[Signal] = []
        by_token = {m.token_id: m for m in markets}
        now = time.time()

        for trader_addr in self._top_traders:
            activity = get_trader_activity(trader_addr, limit=self.activity_limit)
            if not activity:
                continue

            for trade in activity:
                # Activity fields (from docs): proxyWallet, timestamp, conditionId,
                # type, size, usdcSize, transactionHash, price, asset, side,
                # outcomeIndex, title, slug
                trade_id = str(trade.get("transactionHash") or "")
                if not trade_id or self._mark_seen(trade_id):
                    continue

                # Only follow TRADE type (not SPLIT, MERGE, REDEEM etc.)
                if str(trade.get("type", "")).upper() != "TRADE":
                    continue

                token_id = str(trade.get("asset") or "")
                side_raw = str(trade.get("side") or "").upper()
                price = float(trade.get("price") or 0)
                size = float(trade.get("size") or 0)
                timestamp = trade.get("timestamp") or 0

                if not token_id or side_raw not in ("BUY", "SELL") or not price or not size:
                    continue

                # Only follow recent trades
                if timestamp:
                    try:
                        ts = int(timestamp)
                        age = now - ts
                        if age > self.max_trade_age_sec:
                            continue
                    except (ValueError, TypeError):
                        pass

                # Only follow if we have this market in our universe
                m = by_token.get(token_id)
                if not m:
                    continue

                signal_type = SignalType.BUY if side_raw == "BUY" else SignalType.SELL
                copy_size = min(self.order_size, size * self.size_multiplier)
                copy_size = max(copy_size, 1.0)

                signals.append(
                    Signal(
                        type=signal_type,
                        token_id=token_id,
                        price=m.best_ask if side_raw == "BUY" else m.best_bid,
                        size=copy_size,
                        confidence=0.6,
                        strategy=self.name,
                        metadata={
                            "source_trader": trader_addr[:10] + "...",
                            "original_size": size,
                            "original_price": price,
                            "trade_id": trade_id[:16],
                        },
                    )
                )

        return signals
