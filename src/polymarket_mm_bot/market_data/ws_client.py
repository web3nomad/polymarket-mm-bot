from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any

from polymarket_mm_bot.config.models import MarketSelectionConfig
from polymarket_mm_bot.models import MarketSnapshot

LOGGER = logging.getLogger(__name__)

try:
    import requests  # type: ignore
    from requests import Session
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
except ModuleNotFoundError:  # pragma: no cover - environment dependent
    requests = None
    Session = Any  # type: ignore
    HTTPAdapter = None  # type: ignore
    Retry = None  # type: ignore


class MarketDataClient(ABC):
    @abstractmethod
    def get_snapshots(self) -> list[MarketSnapshot]:
        """Return normalized snapshots for selected markets."""


class GammaPollingMarketDataClient(MarketDataClient):
    def __init__(
        self,
        selection_cfg: MarketSelectionConfig,
        *,
        timeout_sec: float = 6.0,
        retries: int = 2,
        base_url: str = "https://gamma-api.polymarket.com",
    ) -> None:
        self.selection_cfg = selection_cfg
        self.timeout_sec = timeout_sec
        self.base_url = base_url.rstrip("/")
        self.session = _build_session(retries)

    def get_snapshots(self) -> list[MarketSnapshot]:
        if self.session is None:
            LOGGER.warning("'requests' is not installed; market polling disabled for this run.")
            return []

        try:
            events = self._request_json("/events", params={"limit": 500, "active": "true"})
            event_theme_by_id = self._normalize_event_themes(events)
            markets = self._request_json("/markets", params={"limit": 500, "active": "true", "closed": "false"})
            snapshots = self._normalize_markets(markets, event_theme_by_id)
        except Exception as exc:  # noqa: BLE001
            if requests is not None and isinstance(exc, requests.RequestException):
                LOGGER.warning("Gamma API unavailable, skipping this loop: %s", exc)
            else:
                LOGGER.warning("Gamma API parse issue, skipping this loop: %s", exc)
            return []

        filtered = [
            s
            for s in snapshots
            if s.liquidity >= self.selection_cfg.min_liquidity
            and s.spread_bps <= self.selection_cfg.max_spread_bps
            and s.minutes_to_expiry >= self.selection_cfg.min_minutes_to_expiry
        ]

        filtered.sort(key=lambda s: (s.liquidity, -s.spread_bps), reverse=True)
        return filtered[: self.selection_cfg.top_n]

    def _request_json(self, path: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        response = self.session.get(
            f"{self.base_url}{path}",
            params=params,
            timeout=self.timeout_sec,
        )
        response.raise_for_status()
        data = response.json()
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
        if isinstance(data, dict) and isinstance(data.get("data"), list):
            return [x for x in data["data"] if isinstance(x, dict)]
        return []

    def _normalize_event_themes(self, events: list[dict[str, Any]]) -> dict[str, str]:
        mapping: dict[str, str] = {}
        for event in events:
            event_id = str(event.get("id", "")).strip()
            if not event_id:
                continue
            theme = str(
                event.get("seriesSlug")
                or event.get("category")
                or event.get("slug")
                or event.get("title")
                or "misc"
            )
            mapping[event_id] = theme[:128]
        return mapping

    def _normalize_markets(
        self,
        markets: list[dict[str, Any]],
        event_theme_by_id: dict[str, str],
    ) -> list[MarketSnapshot]:
        out: list[MarketSnapshot] = []
        now = datetime.now(tz=UTC)

        for row in markets:
            market_id = str(row.get("id") or row.get("marketId") or "").strip()
            if not market_id:
                continue

            bid = _to_float(row.get("bestBid") or row.get("best_bid"))
            ask = _to_float(row.get("bestAsk") or row.get("best_ask"))
            if bid <= 0.0 or ask <= 0.0 or ask <= bid:
                continue

            mid = (bid + ask) / 2.0
            spread_bps = ((ask - bid) / mid) * 10000.0 if mid > 0 else float("inf")

            liquidity = _to_float(
                row.get("liquidity")
                or row.get("liquidityClob")
                or row.get("liquidityNum")
                or row.get("volume")
            )

            expiry = _parse_dt(
                row.get("endDate")
                or row.get("end_date")
                or row.get("endTime")
                or row.get("gameStartTime")
            )
            if expiry is None:
                continue
            minutes_to_expiry = max((expiry - now).total_seconds() / 60.0, 0.0)

            event_id = str(row.get("eventId") or row.get("event_id") or "").strip()
            theme = event_theme_by_id.get(event_id, "misc")
            question = str(row.get("question") or row.get("title") or row.get("slug") or market_id)

            out.append(
                MarketSnapshot(
                    ts=now,
                    market_id=market_id,
                    question=question,
                    theme=theme,
                    liquidity=liquidity,
                    best_bid=bid,
                    best_ask=ask,
                    mid=mid,
                    spread_bps=spread_bps,
                    minutes_to_expiry=minutes_to_expiry,
                )
            )
        return out


class SnapshotReplayClient(MarketDataClient):
    def __init__(self, snapshots_path: str) -> None:
        self.frames = self._load_file(snapshots_path)
        self.index = 0

    def get_snapshots(self) -> list[MarketSnapshot]:
        if self.index >= len(self.frames):
            return []
        frame = self.frames[self.index]
        self.index += 1
        return frame

    @staticmethod
    def _load_file(path: str) -> list[list[MarketSnapshot]]:
        import json
        from pathlib import Path

        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Snapshots file not found: {path}")

        text = p.read_text(encoding="utf-8").strip()
        if not text:
            return []

        rows: list[Any]
        if text.startswith("["):
            rows = json.loads(text)
        else:
            rows = [json.loads(line) for line in text.splitlines() if line.strip()]

        frames: list[list[MarketSnapshot]] = []
        for row in rows:
            if isinstance(row, dict) and isinstance(row.get("markets"), list):
                ts = _parse_dt(row.get("ts")) or datetime.now(tz=UTC)
                markets = [
                    _snapshot_from_any(item, ts)
                    for item in row["markets"]
                    if isinstance(item, dict)
                ]
                frames.append([s for s in markets if s is not None])
            elif isinstance(row, list):
                ts = datetime.now(tz=UTC)
                markets = [_snapshot_from_any(item, ts) for item in row if isinstance(item, dict)]
                frames.append([s for s in markets if s is not None])
        return frames


def _snapshot_from_any(item: dict[str, Any], ts: datetime) -> MarketSnapshot | None:
    market_id = str(item.get("market_id") or item.get("id") or "").strip()
    if not market_id:
        return None

    best_bid = _to_float(item.get("best_bid") or item.get("bestBid"))
    best_ask = _to_float(item.get("best_ask") or item.get("bestAsk"))
    if best_bid <= 0 or best_ask <= best_bid:
        return None

    mid = (best_bid + best_ask) / 2.0
    spread_bps = ((best_ask - best_bid) / mid) * 10000.0
    return MarketSnapshot(
        ts=ts,
        market_id=market_id,
        question=str(item.get("question") or market_id),
        theme=str(item.get("theme") or "misc"),
        liquidity=_to_float(item.get("liquidity") or 0.0),
        best_bid=best_bid,
        best_ask=best_ask,
        mid=mid,
        spread_bps=spread_bps,
        minutes_to_expiry=float(item.get("minutes_to_expiry") or 60.0),
    )


def _build_session(retries: int) -> Session | None:
    if requests is None or Retry is None or HTTPAdapter is None:
        return None

    retry_cfg = Retry(
        total=retries,
        read=retries,
        connect=retries,
        backoff_factor=0.35,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=frozenset(["GET"]),
    )
    adapter = HTTPAdapter(max_retries=retry_cfg)

    session = requests.Session()
    session.headers.update({"User-Agent": "polymarket-mm-bot/0.1"})
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)

    text = str(value).strip()
    if not text:
        return None

    for candidate in (text, text.replace("Z", "+00:00")):
        try:
            parsed = datetime.fromisoformat(candidate)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
