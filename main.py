#!/usr/bin/env python3
"""Polymarket multi-strategy trading engine."""

from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from core.config import load_config
from core.engine import run_loop
from core.events import load_events


def report(config: dict) -> int:
    """Print today's P&L, positions, and halt status."""
    settlement = Path(config.get("settlement_file", "settlement.jsonl"))
    events = load_events(settlement)

    today = datetime.now(timezone.utc).date()
    today_events = []
    for e in events:
        try:
            ts = e.get("ts", "")
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)
            if dt.date() == today:
                today_events.append(e)
        except Exception:
            continue

    latest_equity = None
    latest_realized = 0.0
    latest_unrealized = 0.0
    latest_drawdown = 0.0
    halted = False

    for e in today_events:
        if e.get("type") == "equity_snapshot":
            latest_equity = e.get("equity")
            latest_realized = e.get("realized_pnl", 0)
            latest_unrealized = e.get("unrealized_pnl", 0)
            latest_drawdown = e.get("drawdown", 0)
            halted = bool(e.get("halted"))
        elif e.get("type") == "halt":
            halted = True

    # Get latest positions
    positions = {}
    for e in events:
        if e.get("type") != "position_snapshot":
            continue
        for p in e.get("positions", []):
            if isinstance(p, dict) and p.get("token_id"):
                positions[p["token_id"]] = p

    # Count today's fills by strategy
    strategy_fills: dict[str, int] = {}
    for e in today_events:
        if e.get("type") == "fill":
            s = e.get("strategy", "unknown")
            strategy_fills[s] = strategy_fills.get(s, 0) + 1

    payload = {
        "date_utc": today.isoformat(),
        "equity": round(latest_equity, 4) if latest_equity is not None else None,
        "realized_pnl": round(latest_realized, 4),
        "unrealized_pnl": round(latest_unrealized, 4),
        "drawdown": round(latest_drawdown, 4),
        "halted": halted,
        "fills_by_strategy": strategy_fills,
        "positions": [p for p in positions.values() if abs(p.get("size", 0)) > 1e-12],
        "settlement_file": str(settlement),
    }

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def watch(config: dict, follow: bool, interval: float, tail: int) -> int:
    """Stream recent settlement events."""
    import time

    settlement = Path(config.get("settlement_file", "settlement.jsonl"))
    if not settlement.exists():
        print(f"Settlement file not found: {settlement}")
        return 1

    def render() -> None:
        events = load_events(settlement)
        recent = events[-max(1, tail):]
        counts: dict[str, int] = {}
        for e in recent:
            t = str(e.get("type", ""))
            counts[t] = counts.get(t, 0) + 1
        print(json.dumps({
            "recent_events": len(recent),
            "counts": counts,
            "latest": recent[-1] if recent else None,
        }, ensure_ascii=False))

    render()
    while follow:
        time.sleep(max(0.2, interval))
        render()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Polymarket multi-strategy trading engine")
    parser.add_argument("--config", type=Path, default=Path("config.yaml"), help="Config YAML path")

    sub = parser.add_subparsers(dest="cmd", required=True)

    run_p = sub.add_parser("run", help="Run trading loop")
    run_p.add_argument("--once", action="store_true", help="Single iteration")
    run_p.add_argument("--interval", type=float, default=None, help="Override loop interval (sec)")
    run_p.add_argument("--confirm-live", action="store_true", help="Required for live mode")

    sub.add_parser("report", help="Show today's P&L and positions")

    watch_p = sub.add_parser("watch", help="Watch settlement events")
    watch_p.add_argument("--follow", action="store_true", help="Keep watching")
    watch_p.add_argument("--interval", type=float, default=2.0, help="Refresh interval")
    watch_p.add_argument("--tail", type=int, default=20, help="Recent events to show")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    load_dotenv()
    config = load_config(args.config)

    if args.cmd == "run":
        return run_loop(
            config=config,
            once=bool(args.once),
            interval=args.interval,
            confirm_live=bool(getattr(args, "confirm_live", False)),
        )
    if args.cmd == "report":
        return report(config)
    if args.cmd == "watch":
        return watch(
            config,
            follow=bool(getattr(args, "follow", False)),
            interval=float(getattr(args, "interval", 2.0)),
            tail=int(getattr(args, "tail", 20)),
        )

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
