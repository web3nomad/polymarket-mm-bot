"""WebSocket client for real-time market data (optional, falls back to polling)."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator

LOGGER = logging.getLogger("polymarket.ws")

WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"


async def subscribe(token_ids: list[str]) -> AsyncIterator[dict[str, Any]]:
    """Subscribe to real-time market updates for given tokens.

    Yields parsed message dicts. Falls back gracefully if websockets
    is not installed or connection fails.
    """
    try:
        import websockets
    except ImportError:
        LOGGER.warning("websockets not installed, skipping real-time feed")
        return

    try:
        async with websockets.connect(WS_URL) as ws:
            await ws.send(json.dumps({
                "type": "subscribe",
                "markets": token_ids,
            }))
            LOGGER.info("WebSocket subscribed to %d tokens", len(token_ids))

            async for raw in ws:
                try:
                    data = json.loads(raw)
                    yield data
                except json.JSONDecodeError:
                    continue

    except Exception as exc:
        LOGGER.warning("WebSocket connection failed: %s", exc)


async def subscribe_with_callback(
    token_ids: list[str],
    callback: Any,
    duration_sec: float = 0,
) -> None:
    """Subscribe and invoke callback for each message.

    If duration_sec > 0, auto-disconnect after that many seconds.
    """
    deadline = asyncio.get_event_loop().time() + duration_sec if duration_sec > 0 else float("inf")

    async for msg in subscribe(token_ids):
        await callback(msg)
        if asyncio.get_event_loop().time() >= deadline:
            break
