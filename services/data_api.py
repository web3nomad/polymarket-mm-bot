"""Polymarket Data API — leaderboard and trader activity."""

from __future__ import annotations

import logging
from typing import Any

import requests

LOGGER = logging.getLogger("polymarket.data_api")

BASE_URL = "https://data-api.polymarket.com"


def get_leaderboard(limit: int = 50, timeout: float = 10) -> list[dict[str, Any]]:
    """Fetch top traders by PNL. Max 50 per request, use offset to paginate."""
    try:
        resp = requests.get(
            f"{BASE_URL}/v1/leaderboard",
            params={
                "timePeriod": "ALL",
                "orderBy": "PNL",
                "limit": min(limit, 50),
                "offset": 0,
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else []
    except Exception as e:
        LOGGER.warning("Leaderboard fetch failed: %s", e)
        return []


def get_trader_activity(
    address: str, limit: int = 50, timeout: float = 10
) -> list[dict[str, Any]]:
    """Fetch recent trading activity for a trader."""
    try:
        resp = requests.get(
            f"{BASE_URL}/activity",
            params={
                "user": address,
                "limit": min(limit, 500),
                "type": "TRADE",
                "sortBy": "TIMESTAMP",
                "sortDirection": "DESC",
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else []
    except Exception as e:
        LOGGER.warning("Trader activity fetch failed for %s: %s", address[:10], e)
        return []
