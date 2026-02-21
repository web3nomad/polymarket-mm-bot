#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
import yaml

LOGGER = logging.getLogger("polymarket_mvp")


@dataclass
class Market:
    market_id: str
    question: str
    best_bid: float
    best_ask: float
    liquidity: float
    end_time: str | None


@dataclass
class OrderIntent:
    market_id: str
    side: str
    price: float
    size: float


@dataclass
class Position:
    size: float = 0.0
    avg_entry: float = 0.0
    realized_pnl: float = 0.0


DEFAULT_CONFIG = {
    "gamma_url": "https://gamma-api.polymarket.com/markets",
    "run_interval_sec": 2.0,
    "top_n": 5,
    "min_liquidity": 1000.0,
    "min_spread": 0.02,
    "order_size": 10.0,
    "order_edge": 0.005,
    "risk": {
        "initial_equity": 1000.0,
        "max_order_notional": 20.0,
        "max_market_exposure": 100.0,
        "daily_loss_limit": 50.0,
    },
    "settlement_file": "settlement.jsonl",
    "request_timeout_sec": 8,
    "fetch_limit": 200,
}


class PaperEngine:
    def __init__(self, initial_equity: float) -> None:
        self.initial_equity = float(initial_equity)
        self.positions: dict[str, Position] = {}
        self.last_prices: dict[str, float] = {}

    def market_exposure(self, market_id: str) -> float:
        pos = self.positions.get(market_id)
        if not pos:
            return 0.0
        ref_price = self.last_prices.get(market_id, pos.avg_entry)
        return abs(pos.size * ref_price)

    def apply_fill(self, market_id: str, side: str, price: float, size: float) -> float:
        pos = self.positions.setdefault(market_id, Position())
        signed = size if side == "buy" else -size

        if pos.size == 0:
            pos.size = signed
            pos.avg_entry = price
            return 0.0

        if (pos.size > 0 and signed > 0) or (pos.size < 0 and signed < 0):
            total_abs = abs(pos.size) + abs(signed)
            pos.avg_entry = ((abs(pos.size) * pos.avg_entry) + (abs(signed) * price)) / max(total_abs, 1e-12)
            pos.size += signed
            return 0.0

        closing_qty = min(abs(pos.size), abs(signed))
        if pos.size > 0:
            realized = (price - pos.avg_entry) * closing_qty
        else:
            realized = (pos.avg_entry - price) * closing_qty

        remaining = pos.size + signed
        pos.realized_pnl += realized
        if remaining == 0:
            pos.size = 0.0
            pos.avg_entry = 0.0
        elif abs(signed) > abs(pos.size):
            pos.size = remaining
            pos.avg_entry = price
        else:
            pos.size = remaining
        return realized

    def update_marks(self, markets: list[Market]) -> None:
        for m in markets:
            self.last_prices[m.market_id] = (m.best_bid + m.best_ask) / 2.0

    def realized_total(self) -> float:
        return sum(p.realized_pnl for p in self.positions.values())

    def unrealized_total(self) -> float:
        total = 0.0
        for market_id, pos in self.positions.items():
            if pos.size == 0:
                continue
            mark = self.last_prices.get(market_id, pos.avg_entry)
            if pos.size > 0:
                total += (mark - pos.avg_entry) * pos.size
            else:
                total += (pos.avg_entry - mark) * abs(pos.size)
        return total

    def equity(self) -> float:
        return self.initial_equity + self.realized_total() + self.unrealized_total()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_config(config_path: Path) -> dict[str, Any]:
    config = json.loads(json.dumps(DEFAULT_CONFIG))
    if not config_path.exists():
        LOGGER.warning("Config file %s not found. Using defaults.", config_path)
        return config

    with config_path.open("r", encoding="utf-8") as f:
        loaded = yaml.safe_load(f) or {}

    for k, v in loaded.items():
        if isinstance(v, dict) and isinstance(config.get(k), dict):
            merged = dict(config[k])
            merged.update(v)
            config[k] = merged
        else:
            config[k] = v
    return config
def write_event(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"ts": utc_now_iso(), **payload}
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _to_float(val: Any) -> float | None:
    try:
        if val is None:
            return None
        return float(val)
    except (TypeError, ValueError):
        return None


def _parse_market(raw: dict[str, Any]) -> Market | None:
    market_id = raw.get("id") or raw.get("market_id") or raw.get("conditionId")
    if market_id is None:
        return None

    bid = _to_float(raw.get("bestBid") if raw.get("bestBid") is not None else raw.get("best_bid"))
    ask = _to_float(raw.get("bestAsk") if raw.get("bestAsk") is not None else raw.get("best_ask"))
    liquidity = _to_float(raw.get("liquidity") or raw.get("liquidityNum") or raw.get("volume24hr"))

    if bid is None or ask is None or liquidity is None:
        return None
    if ask <= 0 or bid < 0 or ask < bid:
        return None

    return Market(
        market_id=str(market_id),
        question=str(raw.get("question") or raw.get("title") or ""),
        best_bid=bid,
        best_ask=ask,
        liquidity=liquidity,
        end_time=raw.get("endDate") or raw.get("endTime") or raw.get("end_time"),
    )


def fetch_markets(config: dict[str, Any]) -> list[Market]:
    params = {
        "active": "true",
        "closed": "false",
        "limit": int(config.get("fetch_limit", 200)),
    }
    timeout = float(config.get("request_timeout_sec", 8))
    resp = requests.get(config["gamma_url"], params=params, timeout=timeout)
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

    markets: list[Market] = []
    min_liquidity = float(config.get("min_liquidity", 0))
    for row in rows:
        parsed = _parse_market(row)
        if not parsed:
            continue
        if parsed.liquidity < min_liquidity:
            continue
        markets.append(parsed)

    markets.sort(key=lambda m: m.liquidity, reverse=True)
    return markets[: int(config.get("top_n", 5))]


def build_intents(markets: list[Market], config: dict[str, Any]) -> list[OrderIntent]:
    intents: list[OrderIntent] = []
    min_spread = float(config.get("min_spread", 0.02))
    order_size = float(config.get("order_size", 10.0))
    edge = float(config.get("order_edge", 0.005))

    for m in markets:
        spread = m.best_ask - m.best_bid
        if spread < min_spread:
            continue

        buy_price = max(0.0, min(1.0, m.best_bid + edge))
        sell_price = max(0.0, min(1.0, m.best_ask - edge))
        intents.append(OrderIntent(market_id=m.market_id, side="buy", price=buy_price, size=order_size))
        intents.append(OrderIntent(market_id=m.market_id, side="sell", price=sell_price, size=order_size))
    return intents


def risk_filter(intents: list[OrderIntent], engine: PaperEngine, cfg: dict[str, Any]) -> tuple[list[OrderIntent], bool]:
    risk = cfg["risk"]
    halted = engine.equity() <= float(risk["initial_equity"]) - float(risk["daily_loss_limit"])
    if halted:
        return [], True

    allowed: list[OrderIntent] = []
    max_order_notional = float(risk["max_order_notional"])
    max_market_exposure = float(risk["max_market_exposure"])

    # Use local projected exposures so multiple intents in same loop stay bounded.
    projected_exposure: dict[str, float] = {}
    for intent in intents:
        notional = intent.price * intent.size
        if notional > max_order_notional:
            continue

        current = projected_exposure.get(intent.market_id, engine.market_exposure(intent.market_id))
        if current + notional > max_market_exposure:
            continue

        projected_exposure[intent.market_id] = current + notional
        allowed.append(intent)

    return allowed, False


def execute_paper(intents: list[OrderIntent], markets: list[Market], engine: PaperEngine, settlement: Path) -> int:
    by_id = {m.market_id: m for m in markets}
    fill_count = 0

    for intent in intents:
        write_event(
            settlement,
            {
                "type": "order_open",
                "market_id": intent.market_id,
                "side": intent.side,
                "price": round(intent.price, 6),
                "size": intent.size,
            },
        )

        m = by_id.get(intent.market_id)
        if m is None:
            continue

        filled = (intent.side == "buy" and intent.price >= m.best_ask) or (
            intent.side == "sell" and intent.price <= m.best_bid
        )
        if not filled:
            continue

        engine.apply_fill(intent.market_id, intent.side, intent.price, intent.size)
        fill_count += 1
        write_event(
            settlement,
            {
                "type": "fill",
                "market_id": intent.market_id,
                "side": intent.side,
                "price": round(intent.price, 6),
                "size": intent.size,
            },
        )
    return fill_count


def run_loop(config: dict[str, Any], once: bool, interval: float | None) -> int:
    settlement = Path(config.get("settlement_file", "settlement.jsonl"))
    settlement.parent.mkdir(parents=True, exist_ok=True)
    settlement.touch(exist_ok=True)
    engine = PaperEngine(initial_equity=float(config["risk"]["initial_equity"]))
    sleep_sec = float(interval if interval is not None else config.get("run_interval_sec", 2.0))

    while True:
        try:
            markets = fetch_markets(config)
        except Exception as exc:
            LOGGER.warning("Failed to fetch market data: %s", exc)
            if once:
                return 0
            time.sleep(max(0.1, sleep_sec))
            continue

        if not markets:
            LOGGER.warning("No markets available after filtering.")
            if once:
                return 0
            time.sleep(max(0.1, sleep_sec))
            continue

        engine.update_marks(markets)
        for m in markets:
            write_event(
                settlement,
                {
                    "type": "tick",
                    "market_id": m.market_id,
                    "question": m.question,
                    "best_bid": m.best_bid,
                    "best_ask": m.best_ask,
                    "liquidity": m.liquidity,
                    "end_time": m.end_time,
                },
            )

        intents = build_intents(markets, config)
        allowed, halted = risk_filter(intents, engine, config)
        if halted:
            write_event(settlement, {"type": "halt", "reason": "daily_loss_limit"})
            LOGGER.warning("Daily loss halt triggered. Stop opening new orders.")
            return 0

        fills = execute_paper(allowed, markets, engine, settlement)

        position_rows = []
        for market_id, pos in engine.positions.items():
            if abs(pos.size) < 1e-12:
                continue
            position_rows.append(
                {
                    "market_id": market_id,
                    "size": round(pos.size, 6),
                    "avg_entry": round(pos.avg_entry, 6),
                    "realized_pnl": round(pos.realized_pnl, 6),
                }
            )

        write_event(settlement, {"type": "position_snapshot", "positions": position_rows})
        write_event(
            settlement,
            {
                "type": "equity_snapshot",
                "equity": round(engine.equity(), 6),
                "realized_pnl": round(engine.realized_total(), 6),
                "unrealized_pnl": round(engine.unrealized_total(), 6),
                "halted": False,
            },
        )

        LOGGER.info(
            "markets=%s intents=%s allowed=%s fills=%s equity=%.2f",
            len(markets),
            len(intents),
            len(allowed),
            fills,
            engine.equity(),
        )

        if once:
            return 0
        time.sleep(max(0.1, sleep_sec))


def _is_today_utc(ts: str) -> bool:
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return False
    return dt.date() == datetime.now(timezone.utc).date()


def _load_events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []

    events: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                events.append(row)
    return events


def report(config: dict[str, Any]) -> int:
    settlement = Path(config.get("settlement_file", "settlement.jsonl"))
    events = _load_events(settlement)

    if not events:
        print(
            json.dumps(
                {
                    "date_utc": datetime.now(timezone.utc).date().isoformat(),
                    "today": {"realized_pnl": 0.0, "unrealized_pnl": 0.0, "equity": None},
                    "current_positions": [],
                    "halted": False,
                    "settlement_file": str(settlement),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    today_events = [e for e in events if _is_today_utc(str(e.get("ts", "")))]
    today_realized = 0.0
    latest_equity = None
    latest_unrealized = 0.0
    halted = False

    for e in today_events:
        t = e.get("type")
        if t == "fill":
            # Realized pnl is updated in snapshot; this keeps report tolerant to future schema changes.
            pass
        elif t == "equity_snapshot":
            latest_equity = _to_float(e.get("equity"))
            latest_unrealized = _to_float(e.get("unrealized_pnl")) or 0.0
            today_realized = _to_float(e.get("realized_pnl")) or today_realized
            halted = bool(e.get("halted", False))
        elif t == "halt":
            halted = True

    current_positions: dict[str, dict[str, Any]] = {}
    for e in events:
        if e.get("type") != "position_snapshot":
            continue
        for p in e.get("positions", []):
            if not isinstance(p, dict):
                continue
            market_id = str(p.get("market_id", ""))
            if not market_id:
                continue
            current_positions[market_id] = {
                "market_id": market_id,
                "size": _to_float(p.get("size")) or 0.0,
                "avg_entry": _to_float(p.get("avg_entry")) or 0.0,
                "realized_pnl": _to_float(p.get("realized_pnl")) or 0.0,
            }

    payload = {
        "date_utc": datetime.now(timezone.utc).date().isoformat(),
        "today": {
            "realized_pnl": round(today_realized, 6),
            "unrealized_pnl": round(latest_unrealized, 6),
            "equity": round(latest_equity, 6) if latest_equity is not None else None,
        },
        "current_positions": [p for p in current_positions.values() if abs(p["size"]) > 1e-12],
        "halted": halted,
        "settlement_file": str(settlement),
    }

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Polymarket MVP paper bot")
    parser.add_argument("--config", type=Path, default=Path("config.yaml"), help="Config YAML path")

    sub = parser.add_subparsers(dest="cmd", required=True)
    run_p = sub.add_parser("run", help="Run strategy loop")
    run_p.add_argument("--once", action="store_true", help="Run only one loop")
    run_p.add_argument("--interval", type=float, default=None, help="Override loop interval seconds")

    sub.add_parser("report", help="Show today's pnl/positions/halt")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = load_config(args.config)

    if args.cmd == "run":
        return run_loop(config=config, once=bool(args.once), interval=args.interval)
    if args.cmd == "report":
        return report(config=config)
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
