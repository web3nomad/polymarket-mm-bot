"""Configuration loading and defaults."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import yaml

LOGGER = logging.getLogger("polymarket")

DEFAULT_CONFIG: dict[str, Any] = {
    "mode": "paper",
    "gamma_url": "https://gamma-api.polymarket.com/markets",
    "run_interval_sec": 2.0,
    "top_n": 10,
    "min_liquidity": 1000.0,
    "min_best_ask": 0.03,
    "max_best_ask": 0.97,
    "min_spread": 0.02,
    "min_minutes_to_expiry": 30,
    "fetch_limit": 200,
    "request_timeout_sec": 8,
    "max_orders_per_loop": 20,
    "kill_switch_file": ".halt",
    "settlement_file": "settlement.jsonl",
    "risk": {
        "initial_equity": 1000.0,
        "max_order_notional": 20.0,
        "max_market_exposure": 100.0,
        "daily_loss_limit": 50.0,
        "use_kelly": True,
        "kelly_fraction": 0.5,
        "min_confidence": 0.3,
    },
    "strategies": {
        "market_making": {
            "enabled": True,
            "min_spread": 0.02,
            "edge": 0.005,
            "order_size": 10.0,
        },
        "arbitrage": {
            "enabled": True,
            "threshold": 0.02,
            "order_size": 50.0,
        },
        "momentum": {
            "enabled": True,
            "lookback_trades": 20,
            "buy_threshold": 0.3,
            "sell_threshold": -0.3,
            "order_size": 20.0,
        },
        "mean_reversion": {
            "enabled": False,
            "lookback_trades": 50,
            "std_threshold": 2.0,
            "order_size": 20.0,
        },
    },
    "live": {
        "host": "https://clob.polymarket.com",
        "chain_id": 137,
        "signature_type": 1,
        "private_key_env": "POLYMARKET_PRIVATE_KEY",
        "funder_env": "POLYMARKET_FUNDER",
        "order_type": "GTC",
        "min_order_usd": 1.0,
        "exchange_min_order_usd": 1.0,
        "allow_sell": False,
        "trade_side": "buy",
        "marketable_buffer": 0.0,
        "sync_existing_positions": True,
        "sync_trade_pages": 3,
        "precheck_required": True,
        "market_cooldown_sec": 45,
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    """Merge override into base, recursing into nested dicts."""
    result = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(result.get(k), dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def load_config(config_path: Path) -> dict[str, Any]:
    base = json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy
    if not config_path.exists():
        LOGGER.warning("Config %s not found, using defaults.", config_path)
        return base
    with config_path.open("r", encoding="utf-8") as f:
        loaded = yaml.safe_load(f) or {}
    return _deep_merge(base, loaded)
