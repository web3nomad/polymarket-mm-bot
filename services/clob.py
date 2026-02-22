"""CLOB client wrapper — order execution (paper + live)."""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any

from core.events import write_event
from core.models import Market, OrderIntent, PortfolioState, Position

LOGGER = logging.getLogger("polymarket.clob")


def create_live_client(config: dict[str, Any]) -> Any:
    """Initialize and authenticate the CLOB client."""
    from py_clob_client.client import ClobClient

    live = config.get("live", {})
    private_key = os.getenv(live.get("private_key_env", "POLYMARKET_PRIVATE_KEY"), "").strip()
    funder = os.getenv(live.get("funder_env", "POLYMARKET_FUNDER"), "").strip()

    if not private_key:
        raise RuntimeError(f"Missing env: {live.get('private_key_env')}")
    if not funder:
        raise RuntimeError(f"Missing env: {live.get('funder_env')}")

    client = ClobClient(
        host=live.get("host", "https://clob.polymarket.com"),
        chain_id=int(live.get("chain_id", 137)),
        key=private_key,
        signature_type=int(live.get("signature_type", 1)),
        funder=funder,
    )
    creds = client.create_or_derive_api_creds()
    client.set_api_creds(creds)
    return client


def _normalize_order_type(value: str) -> Any:
    from py_clob_client.clob_types import OrderType
    mapping = {
        "FOK": getattr(OrderType, "FOK", None),
        "GTC": getattr(OrderType, "GTC", None),
        "GTD": getattr(OrderType, "GTD", None),
    }
    picked = mapping.get(value.upper())
    if picked is None:
        raise ValueError(f"Unsupported order type: {value}")
    return picked


def _side_constant(side: str) -> Any:
    from py_clob_client.order_builder.constants import BUY, SELL
    return BUY if side == "buy" else SELL


def _classify_error(error: Any = None, response: dict | None = None) -> str:
    parts = []
    if error is not None:
        parts.append(str(error))
    if response:
        parts.extend(str(response.get(k, "")) for k in ("error", "message", "status"))
    text = " ".join(parts).lower()

    if any(x in text for x in ("geo", "geoblock", "forbidden", "403")):
        return "geoblock"
    if any(x in text for x in ("allowance", "balance", "insufficient")):
        return "allowance/balance"
    if any(x in text for x in ("minimum", "min size", "too small", "notional")):
        return "min-size"
    if any(x in text for x in ("killed", "unfilled", "fok", "cancelled", "rejected")):
        return "fill-killed"
    return "unknown"


def get_usdc_balance(client: Any) -> float:
    """Get USDC balance in dollars (handles micro-USDC conversion)."""
    from py_clob_client.clob_types import BalanceAllowanceParams, AssetType
    try:
        result = client.get_balance_allowance(
            BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
        )
        raw = float(result.get("balance", 0))
        # Balance is in micro-USDC (6 decimals) if > 1000, else already dollars
        return raw / 1e6 if raw > 1000 else raw
    except Exception as e:
        LOGGER.warning("Failed to get USDC balance: %s", e)
        return 0.0


def _precheck(client: Any, intent: OrderIntent) -> tuple[bool, str, dict]:
    """Check USDC balance before placing order. Returns (ok, status, details)."""
    required = intent.price * intent.size if intent.side == "buy" else intent.size

    try:
        balance = get_usdc_balance(client)
        if balance + 1e-6 < required:
            return False, "insufficient_balance", {
                "required": round(required, 4), "balance": round(balance, 4)
            }
        return True, "ok", {"required": round(required, 4), "balance": round(balance, 4)}
    except Exception as e:
        return False, "probe_error", {"error": str(e)}


def execute_paper(
    intents: list[OrderIntent],
    markets: list[Market],
    portfolio: PortfolioState,
    settlement: Path,
) -> int:
    """Simulate order execution in paper mode."""
    by_token = {m.token_id: m for m in markets}
    fills = 0

    for intent in intents:
        write_event(settlement, {
            "type": "order_open",
            "exec_mode": "paper",
            "token_id": intent.token_id,
            "side": intent.side,
            "price": round(intent.price, 6),
            "size": intent.size,
            "strategy": intent.strategy,
            "confidence": round(intent.confidence, 4),
        })

        m = by_token.get(intent.token_id)
        if not m:
            continue

        filled = (
            (intent.side == "buy" and intent.price >= m.best_ask)
            or (intent.side == "sell" and intent.price <= m.best_bid)
        )
        if not filled:
            continue

        pos = portfolio.positions.setdefault(intent.token_id, Position())
        pos.apply_fill(intent.side, intent.price, intent.size)
        fills += 1

        write_event(settlement, {
            "type": "fill",
            "exec_mode": "paper",
            "token_id": intent.token_id,
            "side": intent.side,
            "price": round(intent.price, 6),
            "size": intent.size,
            "strategy": intent.strategy,
        })

    return fills


def cancel_stale_orders(client: Any, intents: list[OrderIntent]) -> int:
    """Cancel existing open orders for tokens we're about to re-quote."""
    token_ids = {i.token_id for i in intents}
    cancelled = 0
    for token_id in token_ids:
        try:
            client.cancel_market_orders(asset_id=str(token_id))
            cancelled += 1
        except Exception as exc:
            LOGGER.debug("Cancel orders for %s: %s", token_id[:12], exc)
    if cancelled:
        LOGGER.info("Cancelled open orders for %d markets", cancelled)
    return cancelled


def execute_live(
    intents: list[OrderIntent],
    client: Any,
    config: dict[str, Any],
    portfolio: PortfolioState,
    settlement: Path,
    cooldowns: dict[str, float],
) -> int:
    """Submit real orders via the CLOB API."""
    from py_clob_client.clob_types import OrderArgs

    live_cfg = config.get("live", {})
    order_type = _normalize_order_type(str(live_cfg.get("order_type", "GTC")))
    cooldown_sec = float(live_cfg.get("market_cooldown_sec", 45))
    posted = 0

    # Cancel existing orders for tokens we're about to re-quote
    cancel_stale_orders(client, intents)

    # Get available balance ONCE, then budget across all orders
    available = get_usdc_balance(client)
    spent = 0.0
    LOGGER.info("Loop budget: $%.2f available", available)

    for intent in intents:
        now = time.time()

        # Cooldown check
        if cooldowns.get(intent.token_id, 0) > now:
            write_event(settlement, {
                "type": "live_order_skip",
                "token_id": intent.token_id,
                "side": intent.side,
                "reason": "cooldown",
            })
            continue

        # Budget check: buy orders cost money, sell orders don't
        if intent.side == "buy":
            cost = intent.price * intent.size
            if spent + cost > available:
                write_event(settlement, {
                    "type": "live_order_skip",
                    "token_id": intent.token_id,
                    "side": intent.side,
                    "reason": "budget_exhausted",
                    "details": {"cost": round(cost, 2), "spent": round(spent, 2), "available": round(available, 2)},
                })
                continue

        write_event(settlement, {
            "type": "order_open",
            "exec_mode": "live",
            "token_id": intent.token_id,
            "side": intent.side,
            "price": round(intent.price, 6),
            "size": intent.size,
            "strategy": intent.strategy,
            "confidence": round(intent.confidence, 4),
        })

        try:
            signed_order = client.create_order(OrderArgs(
                price=float(intent.price),
                size=float(intent.size),
                side=_side_constant(intent.side),
                token_id=str(intent.token_id),
            ))
            resp = client.post_order(signed_order, order_type)
            posted += 1
            if intent.side == "buy":
                spent += intent.price * intent.size

            write_event(settlement, {
                "type": "live_order_result",
                "token_id": intent.token_id,
                "side": intent.side,
                "price": round(intent.price, 6),
                "size": intent.size,
                "strategy": intent.strategy,
                "result": resp,
            })

            success = bool(resp.get("success"))
            status = str(resp.get("status", "")).lower()

            if success and status == "matched":
                pos = portfolio.positions.setdefault(intent.token_id, Position())
                pos.apply_fill(intent.side, intent.price, intent.size)
                write_event(settlement, {
                    "type": "fill",
                    "exec_mode": "live",
                    "token_id": intent.token_id,
                    "side": intent.side,
                    "price": round(intent.price, 6),
                    "size": intent.size,
                    "strategy": intent.strategy,
                })
            elif success:
                # GTC order accepted but not immediately matched —
                # count as pending exposure so next loop won't double up
                pos = portfolio.positions.setdefault(intent.token_id, Position())
                pos.apply_fill(intent.side, intent.price, intent.size)
                write_event(settlement, {
                    "type": "pending_order",
                    "exec_mode": "live",
                    "token_id": intent.token_id,
                    "side": intent.side,
                    "price": round(intent.price, 6),
                    "size": intent.size,
                    "strategy": intent.strategy,
                    "status": status,
                })
            elif not success or status in ("killed", "cancelled", "rejected"):
                error_class = _classify_error(response=resp)
                write_event(settlement, {
                    "type": "live_order_error",
                    "token_id": intent.token_id,
                    "side": intent.side,
                    "error_class": error_class,
                    "error": str(resp.get("error") or resp.get("message") or status),
                })
                cooldowns[intent.token_id] = now + cooldown_sec

        except Exception as exc:
            error_class = _classify_error(error=exc)
            LOGGER.warning("Live order failed: token=%s class=%s err=%s", intent.token_id, error_class, exc)
            write_event(settlement, {
                "type": "live_order_error",
                "token_id": intent.token_id,
                "side": intent.side,
                "error_class": error_class,
                "error": str(exc),
            })
            cooldowns[intent.token_id] = now + cooldown_sec

    return posted


def sync_positions(client: Any, config: dict[str, Any], markets: list[Market]) -> dict[str, Position]:
    """Reconstruct positions from live trade history."""
    from py_clob_client.clob_types import TradeParams

    pages = max(1, int(config.get("live", {}).get("sync_trade_pages", 3)))
    token_set = {m.token_id for m in markets}

    all_trades: list[dict[str, Any]] = []
    for _ in range(pages):
        resp = client.get_trades(TradeParams())
        if not isinstance(resp, list) or not resp:
            break
        all_trades.extend(x for x in resp if isinstance(x, dict))
        break  # py-clob-client returns all in one call

    all_trades.sort(key=lambda x: int(str(x.get("match_time", "0")) or "0"))

    positions: dict[str, Position] = {}
    for tr in all_trades:
        if str(tr.get("status", "")).upper() != "CONFIRMED":
            continue
        token_id = str(tr.get("asset_id") or "").strip()
        if not token_id:
            continue
        side_raw = str(tr.get("side", "")).upper()
        side = "buy" if side_raw == "BUY" else "sell" if side_raw == "SELL" else ""
        if not side:
            continue
        size = float(tr.get("size", 0))
        price = float(tr.get("price", 0))
        if not size or not price:
            continue
        pos = positions.setdefault(token_id, Position())
        pos.apply_fill(side, price, size)

    return positions
