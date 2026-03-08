from __future__ import annotations

import sqlite3
from decimal import Decimal
from pathlib import Path


SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS runs (
        run_id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT NOT NULL,
        mode TEXT NOT NULL,
        market_id TEXT NOT NULL,
        note TEXT DEFAULT ''
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS orders (
        order_id TEXT PRIMARY KEY,
        ts TEXT NOT NULL,
        mode TEXT NOT NULL,
        market_id TEXT NOT NULL,
        side TEXT NOT NULL,
        quantity TEXT NOT NULL,
        limit_price TEXT NOT NULL,
        strategy_name TEXT NOT NULL,
        client_order_id TEXT NOT NULL,
        status TEXT NOT NULL,
        note TEXT DEFAULT ''
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS fills (
        fill_id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id TEXT NOT NULL,
        ts TEXT NOT NULL,
        venue TEXT NOT NULL,
        market_id TEXT NOT NULL,
        side TEXT NOT NULL,
        requested_qty TEXT NOT NULL,
        filled_qty TEXT NOT NULL,
        avg_price TEXT NOT NULL,
        fee_paid TEXT NOT NULL,
        status TEXT NOT NULL,
        note TEXT DEFAULT ''
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS positions (
        market_id TEXT PRIMARY KEY,
        yes_qty TEXT NOT NULL,
        avg_yes_cost TEXT NOT NULL,
        realized_pnl TEXT NOT NULL,
        updated_ts TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS cash_ledger (
        entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT NOT NULL,
        kind TEXT NOT NULL,
        market_id TEXT,
        amount_usdc TEXT NOT NULL,
        note TEXT DEFAULT ''
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS realized_pnl (
        pnl_id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT NOT NULL,
        market_id TEXT NOT NULL,
        amount_usdc TEXT NOT NULL,
        note TEXT DEFAULT ''
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS kill_events (
        event_id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT NOT NULL,
        kill_name TEXT NOT NULL,
        market_id TEXT,
        reason TEXT NOT NULL
    )
    """,
]


class Database:
    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path.as_posix())
        self.conn.row_factory = sqlite3.Row
        self.init_schema()

    def init_schema(self) -> None:
        for stmt in SCHEMA:
            self.conn.execute(stmt)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def log_run(self, ts: str, mode: str, market_id: str, note: str = "") -> None:
        self.conn.execute(
            "INSERT INTO runs (ts, mode, market_id, note) VALUES (?, ?, ?, ?)",
            (ts, mode, market_id, note),
        )
        self.conn.commit()

    def insert_order(self, *, order_id: str, ts: str, mode: str, market_id: str, side: str,
                     quantity: Decimal, limit_price: Decimal, strategy_name: str,
                     client_order_id: str, status: str, note: str = "") -> None:
        self.conn.execute(
            """
            INSERT OR REPLACE INTO orders
            (order_id, ts, mode, market_id, side, quantity, limit_price, strategy_name, client_order_id, status, note)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                order_id, ts, mode, market_id, side, str(quantity), str(limit_price),
                strategy_name, client_order_id, status, note
            ),
        )
        self.conn.commit()

    def insert_fill(self, *, order_id: str, ts: str, venue: str, market_id: str, side: str,
                    requested_qty: Decimal, filled_qty: Decimal, avg_price: Decimal,
                    fee_paid: Decimal, status: str, note: str = "") -> None:
        self.conn.execute(
            """
            INSERT INTO fills
            (order_id, ts, venue, market_id, side, requested_qty, filled_qty, avg_price, fee_paid, status, note)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                order_id, ts, venue, market_id, side, str(requested_qty), str(filled_qty),
                str(avg_price), str(fee_paid), status, note
            ),
        )
        self.conn.commit()

    def get_position(self, market_id: str):
        cur = self.conn.execute("SELECT * FROM positions WHERE market_id = ?", (market_id,))
        return cur.fetchone()

    def upsert_yes_position(self, ts: str, market_id: str, filled_qty: Decimal, avg_price: Decimal) -> None:
        current = self.get_position(market_id)
        if current is None:
            new_qty = filled_qty
            new_cost = avg_price if filled_qty > 0 else Decimal("0")
            realized = Decimal("0")
        else:
            old_qty = Decimal(current["yes_qty"])
            old_cost = Decimal(current["avg_yes_cost"])
            realized = Decimal(current["realized_pnl"])
            new_qty = old_qty + filled_qty
            if new_qty <= 0:
                new_cost = Decimal("0")
            else:
                new_cost = ((old_qty * old_cost) + (filled_qty * avg_price)) / new_qty
        self.conn.execute(
            """
            INSERT OR REPLACE INTO positions (market_id, yes_qty, avg_yes_cost, realized_pnl, updated_ts)
            VALUES (?, ?, ?, ?, ?)
            """,
            (market_id, str(new_qty), str(new_cost), str(realized), ts),
        )
        self.conn.commit()

    def add_cash_entry(self, ts: str, kind: str, amount_usdc: Decimal, market_id: str | None = None, note: str = "") -> None:
        self.conn.execute(
            "INSERT INTO cash_ledger (ts, kind, market_id, amount_usdc, note) VALUES (?, ?, ?, ?, ?)",
            (ts, kind, market_id, str(amount_usdc), note),
        )
        self.conn.commit()

    def add_realized_pnl(self, ts: str, market_id: str, amount_usdc: Decimal, note: str = "") -> None:
        self.conn.execute(
            "INSERT INTO realized_pnl (ts, market_id, amount_usdc, note) VALUES (?, ?, ?, ?)",
            (ts, market_id, str(amount_usdc), note),
        )
        self.conn.commit()

    def add_kill_event(self, ts: str, kill_name: str, reason: str, market_id: str | None = None) -> None:
        self.conn.execute(
            "INSERT INTO kill_events (ts, kill_name, market_id, reason) VALUES (?, ?, ?, ?)",
            (ts, kill_name, market_id, reason),
        )
        self.conn.commit()

    def sum_open_notional(self) -> Decimal:
        cur = self.conn.execute("SELECT yes_qty, avg_yes_cost FROM positions")
        total = Decimal("0")
        for row in cur.fetchall():
            total += Decimal(row["yes_qty"]) * Decimal(row["avg_yes_cost"])
        return total

    def market_open_notional(self, market_id: str) -> Decimal:
        row = self.get_position(market_id)
        if row is None:
            return Decimal("0")
        return Decimal(row["yes_qty"]) * Decimal(row["avg_yes_cost"])

    def cash_balance(self, initial_bankroll: Decimal) -> Decimal:
        cur = self.conn.execute("SELECT COALESCE(SUM(CAST(amount_usdc AS REAL)), 0) AS total FROM cash_ledger")
        ledger_sum = Decimal(str(cur.fetchone()["total"]))
        return initial_bankroll + ledger_sum

    def realized_pnl_today(self, date_prefix: str) -> Decimal:
        cur = self.conn.execute(
            """
            SELECT COALESCE(SUM(CAST(amount_usdc AS REAL)), 0) AS total
            FROM realized_pnl
            WHERE ts LIKE ?
            """,
            (f"{date_prefix}%",),
        )
        return Decimal(str(cur.fetchone()["total"]))

    def count_rows(self, table: str) -> int:
        cur = self.conn.execute(f"SELECT COUNT(*) AS c FROM {table}")
        return int(cur.fetchone()["c"])
    def current_equity(self, initial_bankroll: Decimal) -> Decimal:
        """Calculate current equity = cash + open notional."""
        return self.cash_balance(initial_bankroll) + self.sum_open_notional()

    def get_open_positions(self) -> list[dict]:
        """Get all positions with qty > 0."""
        rows = self.conn.execute(
            "SELECT market_id, yes_qty, avg_yes_cost, realized_pnl, updated_ts "
            "FROM positions WHERE CAST(yes_qty AS REAL) > 0"
        ).fetchall()
        return [dict(r) for r in rows]
