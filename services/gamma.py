"""Gamma API client — market data fetching."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

import requests

from core.events import parse_iso_to_utc
from core.models import Market

LOGGER = logging.getLogger("polymarket.gamma")


def _to_float(val: Any) -> float | None:
    try:
        return float(val) if val is not None else None
    except (TypeError, ValueError):
        return None


def _extract_token_id(raw: dict[str, Any]) -> str | None:
    direct = raw.get("token_id") or raw.get("tokenId")
    if isinstance(direct, str) and direct:
        return direct

    tokens = raw.get("clobTokenIds") or raw.get("clobTokenIdsRaw")
    if isinstance(tokens, list) and tokens:
        return str(tokens[0])
    if isinstance(tokens, str):
        stripped = tokens.strip()
        if stripped.startswith("["):
            try:
                parsed = json.loads(stripped)
                if isinstance(parsed, list) and parsed:
                    return str(parsed[0])
            except json.JSONDecodeError:
                pass
        if stripped:
            return stripped
    return None


def _extract_complement_token_id(raw: dict[str, Any]) -> str | None:
    tokens = raw.get("clobTokenIds") or raw.get("clobTokenIdsRaw")
    if isinstance(tokens, list) and len(tokens) >= 2:
        return str(tokens[1])
    if isinstance(tokens, str):
        try:
            parsed = json.loads(tokens.strip())
            if isinstance(parsed, list) and len(parsed) >= 2:
                return str(parsed[1])
        except (json.JSONDecodeError, ValueError):
            pass
    return None


def _parse_market(raw: dict[str, Any]) -> Market | None:
    condition_id = raw.get("conditionId") or raw.get("condition_id") or raw.get("id") or ""
    market_id = raw.get("id") or raw.get("market_id") or condition_id
    if not market_id:
        return None

    bid = _to_float(raw.get("bestBid") or raw.get("best_bid"))
    ask = _to_float(raw.get("bestAsk") or raw.get("best_ask"))
    liquidity = _to_float(raw.get("liquidity") or raw.get("liquidityNum") or raw.get("volume24hr"))
    volume = _to_float(raw.get("volume24hr") or raw.get("volume_24h")) or liquidity or 0

    if bid is None or ask is None or liquidity is None:
        return None
    if ask <= 0 or bid < 0 or ask < bid:
        return None

    end_time = raw.get("endDate") or raw.get("endTime") or raw.get("end_time")
    end_dt = parse_iso_to_utc(end_time)
    minutes_to_expiry = None
    if end_dt is not None:
        minutes_to_expiry = (end_dt - datetime.now(timezone.utc)).total_seconds() / 60.0

    token_id = _extract_token_id(raw)
    if not token_id:
        return None

    return Market(
        token_id=token_id,
        condition_id=str(condition_id),
        question=str(raw.get("question") or raw.get("title") or ""),
        best_bid=bid,
        best_ask=ask,
        volume_24h=volume,
        liquidity=liquidity,
        end_time=end_time,
        minutes_to_expiry=minutes_to_expiry,
        complement_token_id=_extract_complement_token_id(raw),
    )


def fetch_markets(config: dict[str, Any]) -> list[Market]:
    """Fetch and filter markets from the Gamma API."""
    url = config.get("gamma_url", "https://gamma-api.polymarket.com/markets")
    timeout = float(config.get("request_timeout_sec", 8))
    params = {
        "active": "true",
        "closed": "false",
        "limit": int(config.get("fetch_limit", 200)),
    }

    resp = requests.get(url, params=params, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()

    rows: list[dict[str, Any]] = []
    if isinstance(data, list):
        rows = [x for x in data if isinstance(x, dict)]
    elif isinstance(data, dict):
        for key in ("markets", "data"):
            chunk = data.get(key)
            if isinstance(chunk, list):
                rows = [x for x in chunk if isinstance(x, dict)]
                break

    min_liquidity = float(config.get("min_liquidity", 0))
    min_ask = float(config.get("min_best_ask", 0.03))
    max_ask = float(config.get("max_best_ask", 0.97))
    min_spread = float(config.get("min_spread", 0.02))
    min_expiry = float(config.get("min_minutes_to_expiry", 0))

    markets: list[Market] = []
    for raw in rows:
        m = _parse_market(raw)
        if not m:
            continue
        if m.liquidity < min_liquidity:
            continue
        if m.best_ask < min_ask or m.best_ask > max_ask:
            continue
        if m.spread < min_spread:
            continue
        if m.minutes_to_expiry is not None and m.minutes_to_expiry < min_expiry:
            continue
        markets.append(m)

    markets.sort(key=lambda x: x.liquidity, reverse=True)
    top_n = int(config.get("top_n", 10))
    return markets[:top_n]
