from __future__ import annotations

import argparse
import json
from pathlib import Path

from polymarket_mm_bot.config.loader import load_app_config
from polymarket_mm_bot.logging_setup.setup import configure_logging
from polymarket_mm_bot.runner import report, run_bot


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Polymarket v1 paper MM bot")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run paper bot")
    run_parser.add_argument("--config", type=Path, default=Path("config/default.yaml"), help="YAML config path")
    run_parser.add_argument("--interval", type=float, default=None, help="Loop interval seconds")
    run_parser.add_argument("--once", action="store_true", help="Run only one loop")

    backtest_parser = subparsers.add_parser("backtest-lite", help="Replay sampled snapshots from file")
    backtest_parser.add_argument("--config", type=Path, default=Path("config/default.yaml"), help="YAML config path")
    backtest_parser.add_argument("--snapshots", type=Path, required=True, help="JSON/JSONL snapshots file")
    backtest_parser.add_argument("--interval", type=float, default=0.0, help="Replay loop interval seconds")

    report_parser = subparsers.add_parser("report", help="Show today's PnL and exposure")
    report_parser.add_argument("--config", type=Path, default=Path("config/default.yaml"), help="YAML config path")
    report_parser.add_argument("--db-path", type=str, default=None, help="Override sqlite db path")

    return parser


def main() -> int:
    args = build_parser().parse_args()

    if args.command in {"run", "backtest-lite", "report"}:
        config = load_app_config(args.config)
        configure_logging(config.runtime.log_level)

    if args.command == "run":
        interval = float(args.interval if args.interval is not None else config.strategy.quote_refresh_sec)
        return run_bot(config=config, config_path=args.config, once=bool(args.once), interval_sec=interval)

    if args.command == "backtest-lite":
        return run_bot(
            config=config,
            config_path=args.config,
            once=False,
            interval_sec=max(0.0, float(args.interval)),
            snapshots_file=args.snapshots,
        )

    if args.command == "report":
        db_path = args.db_path or config.telemetry.db_path
        payload = report(db_path)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    return 1
