from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from polymarket_mm_bot.config.models import RiskConfig
from polymarket_mm_bot.models import MarketSnapshot, QuoteIntent, RiskContext


@dataclass(slots=True)
class RiskDecision:
    allowed: bool
    reason: str


class RiskManager:
    def __init__(self, cfg: RiskConfig) -> None:
        self.cfg = cfg

    def allow_intent(self, intent: QuoteIntent, snapshot: MarketSnapshot, ctx: RiskContext) -> Tuple[bool, str]:
        if self._is_drawdown_halted(ctx):
            return False, "daily_drawdown_stop"

        if ctx.open_order_count >= self.cfg.max_open_orders:
            return False, "max_open_orders"

        trade_notional = abs(intent.price * intent.size)
        per_trade_limit = self.cfg.strategy_capital * self.cfg.per_trade_risk_pct / 100.0
        if trade_notional > per_trade_limit:
            return False, "per_trade_risk_limit"

        market_limit = self.cfg.strategy_capital * self.cfg.market_exposure_pct / 100.0
        market_now = ctx.market_exposure_by_id.get(intent.market_id, 0.0)
        if market_now + trade_notional > market_limit:
            return False, "market_exposure_limit"

        theme_limit = self.cfg.strategy_capital * self.cfg.theme_exposure_pct / 100.0
        theme_now = ctx.theme_exposure_by_name.get(snapshot.theme, 0.0)
        if theme_now + trade_notional > theme_limit:
            return False, "theme_exposure_limit"

        return True, "ok"

    def _is_drawdown_halted(self, ctx: RiskContext) -> bool:
        if ctx.start_of_day_equity <= 0:
            return False
        drawdown_pct = ((ctx.start_of_day_equity - ctx.equity) / ctx.start_of_day_equity) * 100.0
        return drawdown_pct >= self.cfg.daily_drawdown_stop_pct
