"""Narrative-driven trading: monitor Twitter for macro news, trade before event-driven moves."""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any

import requests

from core.events import write_event
from core.models import Market, PortfolioState, Signal, SignalType
from services.gamma import _parse_market
from strategies.base import BaseStrategy

LOGGER = logging.getLogger("polymarket.narrative_driven")

BULLISH_WORDS = frozenset([
    "higher", "above", "surge", "hot", "increase", "accelerate",
    "spike", "rise", "beat", "exceed", "hawkish",
])
BEARISH_WORDS = frozenset([
    "lower", "below", "cool", "decrease", "drop", "decline",
    "slow", "fall", "miss", "dovish", "cut",
])


def _score_text(text: str) -> tuple[float, int]:
    """Return (sentiment_score, word_hits) for a piece of text.

    Score in [-1, 1].  positive = bullish, negative = bearish.
    """
    words = text.lower().split()
    bull = sum(1 for w in words if w in BULLISH_WORDS)
    bear = sum(1 for w in words if w in BEARISH_WORDS)
    total = bull + bear
    if total == 0:
        return 0.0, 0
    return (bull - bear) / total, total


class NarrativeDrivenStrategy(BaseStrategy):
    name = "narrative_driven"

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self.keywords: list[str] = config.get("keywords", [])
        self.refresh_markets_sec = float(config.get("refresh_markets_sec", 600))
        self.refresh_tweets_sec = float(config.get("refresh_tweets_sec", 120))
        self.min_tweet_count = int(config.get("min_tweet_count", 3))
        self.min_sentiment_score = float(config.get("min_sentiment_score", 0.3))
        self.order_size = float(config.get("order_size", 5))
        self.manual_confirm = bool(config.get("manual_confirm", False))
        self.settlement_file = Path(config.get("settlement_file", "data/settlement.jsonl"))

        token_env = config.get("twitter_token_env", "X_BEARER_TOKEN")
        self._twitter_token: str | None = os.environ.get(token_env)

        # Caches
        self._narrative_markets: dict[str, Market] = {}  # token_id -> Market
        self._keyword_to_tokens: dict[str, list[str]] = {}  # keyword -> [token_ids]
        self._last_market_refresh: float = 0
        self._last_tweet_refresh: float = 0
        self._tweet_sentiment: dict[str, float] = {}  # keyword -> score
        self._tweet_count: dict[str, int] = {}  # keyword -> count

    # ── Market discovery ─────────────────────────────────────────────

    def _refresh_narrative_markets(self, engine_markets: list[Market]) -> None:
        now = time.time()
        if now - self._last_market_refresh < self.refresh_markets_sec and self._narrative_markets:
            return

        self._narrative_markets.clear()
        self._keyword_to_tokens.clear()

        # 1) Scan engine-provided markets
        for m in engine_markets:
            q_lower = m.question.lower()
            for kw in self.keywords:
                if kw.lower() in q_lower:
                    self._narrative_markets[m.token_id] = m
                    self._keyword_to_tokens.setdefault(kw, []).append(m.token_id)

        # 2) Search Gamma for more keyword-related markets
        for kw in self.keywords:
            try:
                resp = requests.get(
                    "https://gamma-api.polymarket.com/markets",
                    params={"active": "true", "closed": "false", "limit": 500},
                    timeout=8,
                )
                resp.raise_for_status()
                rows = resp.json()
                if not isinstance(rows, list):
                    rows = rows.get("markets", rows.get("data", []))
            except Exception as exc:
                LOGGER.debug("Gamma search failed for '%s': %s", kw, exc)
                continue

            for raw in rows:
                if not isinstance(raw, dict):
                    continue
                question = str(raw.get("question") or raw.get("title") or "").lower()
                if kw.lower() not in question:
                    continue
                m = _parse_market(raw)
                if m and m.token_id not in self._narrative_markets:
                    self._narrative_markets[m.token_id] = m
                    self._keyword_to_tokens.setdefault(kw, []).append(m.token_id)

        self._last_market_refresh = now
        LOGGER.info(
            "Narrative markets: %d markets across %d keywords",
            len(self._narrative_markets),
            len(self._keyword_to_tokens),
        )

    # ── Twitter sentiment ────────────────────────────────────────────

    def _scan_twitter(self) -> None:
        now = time.time()
        if now - self._last_tweet_refresh < self.refresh_tweets_sec and self._tweet_sentiment:
            return

        if not self._twitter_token:
            LOGGER.debug("No Twitter token — skipping sentiment scan")
            return

        headers = {"Authorization": f"Bearer {self._twitter_token}"}

        for kw in self.keywords:
            try:
                resp = requests.get(
                    "https://api.x.com/2/tweets/search/recent",
                    params={
                        "query": f"{kw} -is:retweet lang:en",
                        "max_results": 100,
                        "tweet.fields": "public_metrics",
                    },
                    headers=headers,
                    timeout=10,
                )
                if resp.status_code == 429:
                    LOGGER.debug("Twitter rate-limited on '%s'", kw)
                    continue
                if resp.status_code != 200:
                    LOGGER.debug("Twitter %d on '%s'", resp.status_code, kw)
                    continue

                data = resp.json().get("data", [])
                if not data:
                    self._tweet_sentiment[kw] = 0.0
                    self._tweet_count[kw] = 0
                    continue

                weighted_score = 0.0
                total_weight = 0.0
                for tweet in data:
                    text = tweet.get("text", "")
                    metrics = tweet.get("public_metrics", {})
                    engagement = (
                        int(metrics.get("like_count", 0))
                        + int(metrics.get("retweet_count", 0)) * 2
                        + int(metrics.get("reply_count", 0))
                        + 1  # base weight
                    )
                    score, _ = _score_text(text)
                    weighted_score += score * engagement
                    total_weight += engagement

                avg = weighted_score / total_weight if total_weight > 0 else 0.0
                self._tweet_sentiment[kw] = avg
                self._tweet_count[kw] = len(data)

            except Exception as exc:
                LOGGER.debug("Twitter scan error for '%s': %s", kw, exc)
                continue

        self._last_tweet_refresh = now

    # ── Main analyze ─────────────────────────────────────────────────

    def analyze(self, markets: list[Market], portfolio: PortfolioState) -> list[Signal]:
        if not self.keywords:
            return []

        self._refresh_narrative_markets(markets)
        self._scan_twitter()

        # Inject narrative market prices into portfolio for equity calc
        for tid, m in self._narrative_markets.items():
            portfolio.last_prices[tid] = m.mid_price

        signals: list[Signal] = []

        for kw, token_ids in self._keyword_to_tokens.items():
            score = self._tweet_sentiment.get(kw, 0.0)
            count = self._tweet_count.get(kw, 0)

            if count < self.min_tweet_count:
                continue
            if abs(score) < self.min_sentiment_score:
                continue

            for tid in token_ids:
                m = self._narrative_markets.get(tid)
                if not m:
                    continue

                if score > 0:
                    signal_type = SignalType.BUY
                    price = min(m.best_bid + 0.01, m.best_ask)
                else:
                    signal_type = SignalType.SELL
                    price = max(m.best_ask - 0.01, m.best_bid)

                signal = Signal(
                    type=signal_type,
                    token_id=tid,
                    price=price,
                    size=self.order_size,
                    confidence=min(abs(score), 1.0),
                    strategy=self.name,
                    metadata={
                        "keyword": kw,
                        "sentiment": round(score, 3),
                        "tweet_count": count,
                        "question": m.question[:80],
                    },
                )

                if self.manual_confirm:
                    write_event(self.settlement_file, {
                        "type": "narrative_signal_pending",
                        "strategy": self.name,
                        "signal_type": signal_type.value,
                        "token_id": tid,
                        "keyword": kw,
                        "sentiment": round(score, 3),
                        "tweet_count": count,
                        "question": m.question[:80],
                    })
                    LOGGER.info(
                        "MANUAL CONFIRM: %s %s (kw=%s, sentiment=%.2f, tweets=%d)",
                        signal_type.value, m.question[:60], kw, score, count,
                    )
                else:
                    signals.append(signal)
                    LOGGER.info(
                        "Signal: %s %s @ %.2f (kw=%s, sentiment=%.2f, tweets=%d)",
                        signal_type.value, m.question[:60], price, kw, score, count,
                    )

        return signals
