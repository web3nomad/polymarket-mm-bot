from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from polymarket_mm_bot.models import Fill, Order, Position


class SqliteStore:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        db_file = Path(db_path)
        db_file.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def close(self) -> None:
        self.conn.close()

    def start_run(self, run_id: str, mode: str, config_path: str) -> None:
        self.conn.execute(
            """
            INSERT OR REPLACE INTO runs(run_id, started_at, mode, config_path)
            VALUES(?, ?, ?, ?)
            """,
            (run_id, _ts(datetime.now(tz=UTC)), mode, config_path),
        )
        self.conn.commit()

    def record_orders(self, run_id: str, orders: list[Order]) -> None:
        if not orders:
            return
        self.conn.executemany(
            """
            INSERT INTO orders(order_id, run_id, ts, market_id, side, price, size, status, reason)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    o.order_id,
                    run_id,
                    _ts(o.ts),
                    o.market_id,
                    o.side,
                    o.price,
                    o.size,
                    o.status,
                    o.reason,
                )
                for o in orders
            ],
        )
        self.conn.commit()

    def record_fills(self, run_id: str, fills: list[Fill]) -> None:
        if not fills:
            return
        self.conn.executemany(
            """
            INSERT INTO fills(fill_id, run_id, ts, order_id, market_id, side, price, size, slippage_bps)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    f.fill_id,
                    run_id,
                    _ts(f.ts),
                    f.order_id,
                    f.market_id,
                    f.side,
                    f.price,
                    f.size,
                    f.slippage_bps,
                )
                for f in fills
            ],
        )
        self.conn.commit()

    def record_positions(self, run_id: str, positions: dict[str, Position]) -> None:
        if not positions:
            return
        ts = _ts(datetime.now(tz=UTC))
        self.conn.executemany(
            """
            INSERT INTO positions(run_id, ts, market_id, qty, avg_price, realized_pnl)
            VALUES(?, ?, ?, ?, ?, ?)
            """,
            [
                (run_id, ts, p.market_id, p.qty, p.avg_price, p.realized_pnl)
                for p in positions.values()
            ],
        )
        self.conn.commit()

    def record_equity(self, run_id: str, equity: float, cash: float, realized_pnl: float, unrealized_pnl: float) -> None:
        self.conn.execute(
            """
            INSERT INTO equity_curve(run_id, ts, equity, cash, realized_pnl, unrealized_pnl)
            VALUES(?, ?, ?, ?, ?, ?)
            """,
            (run_id, _ts(datetime.now(tz=UTC)), equity, cash, realized_pnl, unrealized_pnl),
        )
        self.conn.commit()

    def report_today(self) -> dict:
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT equity FROM equity_curve
            WHERE date(ts, 'localtime') = date('now', 'localtime')
            ORDER BY ts ASC LIMIT 1
            """
        )
        first = cur.fetchone()

        cur.execute(
            """
            SELECT equity, cash, realized_pnl, unrealized_pnl, ts FROM equity_curve
            WHERE date(ts, 'localtime') = date('now', 'localtime')
            ORDER BY ts DESC LIMIT 1
            """
        )
        last = cur.fetchone()

        cur.execute(
            """
            SELECT market_id, qty, avg_price, ts
            FROM positions
            WHERE ts = (SELECT MAX(ts) FROM positions)
            ORDER BY ABS(qty * avg_price) DESC
            LIMIT 20
            """
        )
        rows = cur.fetchall()

        pnl_today = 0.0
        if first and last:
            pnl_today = float(last["equity"]) - float(first["equity"])

        exposure = [
            {
                "market_id": r["market_id"],
                "qty": float(r["qty"]),
                "avg_price": float(r["avg_price"]),
                "notional": abs(float(r["qty"]) * float(r["avg_price"])),
            }
            for r in rows
        ]

        return {
            "pnl_today": pnl_today,
            "latest": dict(last) if last else None,
            "exposure": exposure,
        }

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                started_at TEXT NOT NULL,
                mode TEXT NOT NULL,
                config_path TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS orders (
                order_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                ts TEXT NOT NULL,
                market_id TEXT NOT NULL,
                side TEXT NOT NULL,
                price REAL NOT NULL,
                size REAL NOT NULL,
                status TEXT NOT NULL,
                reason TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS fills (
                fill_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                ts TEXT NOT NULL,
                order_id TEXT NOT NULL,
                market_id TEXT NOT NULL,
                side TEXT NOT NULL,
                price REAL NOT NULL,
                size REAL NOT NULL,
                slippage_bps REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                ts TEXT NOT NULL,
                market_id TEXT NOT NULL,
                qty REAL NOT NULL,
                avg_price REAL NOT NULL,
                realized_pnl REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS equity_curve (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                ts TEXT NOT NULL,
                equity REAL NOT NULL,
                cash REAL NOT NULL,
                realized_pnl REAL NOT NULL,
                unrealized_pnl REAL NOT NULL
            );
            """
        )
        self.conn.commit()


def _ts(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()
