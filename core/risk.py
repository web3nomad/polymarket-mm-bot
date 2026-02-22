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
        self.cash_reserve_pct = float(risk.get("cash_reserve_pct", 0.30))
        self.max_positions = int(risk.get("max_positions", 5))

        live = config.get("live", {})
        self.mode = str(config.get("mode", "paper")).lower()
        self.allow_sell = bool(live.get("allow_sell", False))
        self.trade_side = str(live.get("trade_side", "buy")).lower()
        self.min_order_usd = max(
            float(live.get("min_order_usd", 0)),
            float(live.get("exchange_min_order_usd", 1.0)),
        )
        self.exchange_min_shares = float(live.get("exchange_min_shares", 5))

        # Live balance — updated by engine each loop before calling signals_to_intents
        self.live_balance: float | None = None

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

        Money management rules (thinking like it's my own money):
        1. Always keep cash_reserve_pct of equity as cash — never spend it all
        2. Don't open new positions if already at max_positions — focus, don't scatter
        3. Exits (sells) always go through — protecting capital is priority #1
        4. Budget for buys = balance - reserve, spent across signals by confidence rank

        Returns (intents, halted).
        """
        if self.is_halted(portfolio):
            return [], True

        # Separate exits (sells from position_manager) from entries
        valid = [s for s in signals if s.type != SignalType.HOLD and s.confidence >= self.min_confidence]
        valid.sort(key=lambda s: s.confidence, reverse=True)

        exits = []
        entries = []
        for s in valid:
            side = s.type.value
            is_exit = s.strategy == "position_manager" and side == "sell"
            if is_exit:
                exits.append(s)
            else:
                entries.append(s)

        intents: list[OrderIntent] = []
        projected_exposure: dict[str, float] = {}

        # --- PHASE 1: Exits first. Always allow. Protecting capital. ---
        for signal in exits:
            size = signal.size
            if size <= 0:
                continue
            intents.append(OrderIntent(
                token_id=signal.token_id,
                side="sell",
                price=signal.price,
                size=round(size, 4),
                strategy=signal.strategy,
                confidence=signal.confidence,
                metadata=signal.metadata,
            ))

        # --- PHASE 2: Entries. Budget-aware. ---
        # Calculate how much we can actually spend this loop
        if self.live_balance is not None:
            total_equity = self.live_balance + sum(
                abs(p.size) * portfolio.last_prices.get(tid, p.avg_entry)
                for tid, p in portfolio.positions.items() if abs(p.size) > 0.01
            )
            reserve = total_equity * self.cash_reserve_pct
            buy_budget = max(0, self.live_balance - reserve)
            LOGGER.info(
                "资金: 余额=$%.2f 总值=$%.2f 保留=$%.2f 可用=$%.2f",
                self.live_balance, total_equity, reserve, buy_budget,
            )
        else:
            # Paper mode or balance unknown — use notional limits only
            buy_budget = float("inf")

        budget_spent = 0.0
        current_positions = sum(
            1 for p in portfolio.positions.values() if abs(p.size) > 0.01
        )

        for signal in entries:
            side = signal.type.value

            # Side gating
            if self.mode == "live":
                if side == "sell" and not self.allow_sell:
                    continue
                if self.trade_side not in (side, "both"):
                    continue

            # Position count limit — don't open new markets if already at max
            if side == "buy" and signal.token_id not in portfolio.positions:
                if current_positions >= self.max_positions:
                    continue

            # Size
            size = self.kelly_size(signal) if self.use_kelly else signal.size
            if size <= 0:
                continue

            if self.mode == "live" and size < self.exchange_min_shares:
                size = self.exchange_min_shares

            notional = signal.price * size

            if notional > self.max_order_notional:
                size = self.max_order_notional / signal.price
                notional = self.max_order_notional

            if self.mode == "live" and size < self.exchange_min_shares:
                continue

            if self.mode == "live" and notional < self.min_order_usd:
                continue

            # Budget check for buys
            if side == "buy":
                if budget_spent + notional > buy_budget:
                    LOGGER.debug("预算不足，跳过: need=$%.2f left=$%.2f", notional, buy_budget - budget_spent)
                    continue

            # Market exposure check
            current_exp = projected_exposure.get(
                signal.token_id, portfolio.market_exposure(signal.token_id)
            )
            if current_exp + notional > self.max_market_exposure:
                continue

            projected_exposure[signal.token_id] = current_exp + notional

            if side == "buy":
                budget_spent += notional

            intents.append(OrderIntent(
                token_id=signal.token_id,
                side=side,
                price=signal.price,
                size=round(size, 4),
                strategy=signal.strategy,
                confidence=signal.confidence,
                metadata=signal.metadata,
            ))

            if len(intents) >= self.max_orders_per_loop:
                break

        if budget_spent > 0:
            LOGGER.info("本轮计划花费: $%.2f / $%.2f", budget_spent, buy_budget)

        return intents, False
