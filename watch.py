"""
Portfolio watcher — live dashboard for polymarket-binary-bot.

Reads the SQLite database and displays portfolio state in a clean format.
Auto-refreshes every few seconds. Works in PowerShell and Linux terminals.

Usage:
    python watch.py                       # default data/bot.db
    python watch.py --db data/bot.db      # explicit path
    python watch.py --once                # print once and exit
    python watch.py --refresh 3           # refresh every 3 seconds
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from polymarket_bot.config import Settings
from polymarket_bot.db import Database


def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")


def format_pnl(val: float) -> str:
    if val > 0:
        return f"+${val:,.4f}"
    elif val < 0:
        return f"-${abs(val):,.4f}"
    return "$0.0000"


def build_dashboard(db: Database, settings: Settings) -> str:
    lines: list[str] = []
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    bankroll = float(settings.bankroll_usdc)
    cash = float(db.cash_balance(settings.bankroll_usdc))
    open_notional = float(db.sum_open_notional())
    equity = cash + open_notional
    total_return = equity - bankroll
    return_pct = (total_return / bankroll * 100) if bankroll > 0 else 0.0

    # Today's realized PnL
    today_prefix = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    realized_today = float(db.realized_pnl_today(today_prefix))

    # Counts
    total_orders = db.count_rows("orders")
    total_fills = db.count_rows("fills")
    total_runs = db.count_rows("runs")
    total_kills = db.count_rows("kill_events")

    # Header
    lines.append("=" * 60)
    lines.append("  POLYMARKET BINARY BOT — PORTFOLIO DASHBOARD")
    lines.append("=" * 60)
    lines.append(f"  {now}")
    lines.append("")

    # Portfolio summary
    lines.append("  PORTFOLIO")
    lines.append("  " + "-" * 56)
    lines.append(f"  Starting Bankroll:    ${bankroll:>12,.2f}")
    lines.append(f"  Cash Available:       ${cash:>12,.4f}")
    lines.append(f"  Open Notional:        ${open_notional:>12,.4f}")
    lines.append(f"  Equity (cash+open):   ${equity:>12,.4f}")
    lines.append(f"  Total Return:         {format_pnl(total_return):>13}  ({return_pct:+.2f}%)")
    lines.append(f"  Realized PnL Today:   {format_pnl(realized_today):>13}")
    lines.append("")

    # Activity stats
    lines.append("  ACTIVITY")
    lines.append("  " + "-" * 56)
    lines.append(f"  Ticks (runs):         {total_runs:>12,}")
    lines.append(f"  Orders placed:        {total_orders:>12,}")
    lines.append(f"  Fills:                {total_fills:>12,}")
    lines.append(f"  Risk blocks:          {total_kills:>12,}")
    lines.append("")

    # Open positions
    positions = db.conn.execute(
        "SELECT market_id, yes_qty, avg_yes_cost, realized_pnl, updated_ts "
        "FROM positions WHERE CAST(yes_qty AS REAL) > 0 "
        "ORDER BY updated_ts DESC"
    ).fetchall()

    lines.append("  OPEN POSITIONS")
    lines.append("  " + "-" * 56)
    if positions:
        lines.append(f"  {'Market':<28} {'Qty':>8} {'AvgCost':>8} {'Notional':>10}")
        lines.append("  " + "-" * 56)
        for p in positions:
            qty = float(Decimal(p["yes_qty"]))
            cost = float(Decimal(p["avg_yes_cost"]))
            notional = qty * cost
            slug = str(p["market_id"])[:28]
            lines.append(f"  {slug:<28} {qty:>8.2f} {cost:>8.4f} ${notional:>9.4f}")
    else:
        lines.append("  (no open positions)")
    lines.append("")

    # Last 10 fills
    fills = db.conn.execute(
        "SELECT ts, market_id, side, filled_qty, avg_price, fee_paid, status "
        "FROM fills ORDER BY fill_id DESC LIMIT 10"
    ).fetchall()

    lines.append("  LAST 10 FILLS")
    lines.append("  " + "-" * 56)
    if fills:
        lines.append(f"  {'Time':>8} {'Market':<20} {'Side':<8} {'Qty':>8} {'Price':>7} {'Status':<8}")
        lines.append("  " + "-" * 56)
        for f in fills:
            ts = str(f["ts"])
            # Extract HH:MM from ISO timestamp
            try:
                t = ts[11:16] if len(ts) > 16 else ts[-5:]
            except Exception:
                t = "??:??"
            slug = str(f["market_id"])[:20]
            qty = float(Decimal(f["filled_qty"]))
            price = float(Decimal(f["avg_price"]))
            lines.append(f"  {t:>8} {slug:<20} {f['side']:<8} {qty:>8.2f} {price:>7.4f} {f['status']:<8}")
    else:
        lines.append("  (no fills yet)")
    lines.append("")

    # Last 5 risk blocks (kill events)
    kills = db.conn.execute(
        "SELECT ts, kill_name, market_id, reason FROM kill_events ORDER BY event_id DESC LIMIT 5"
    ).fetchall()

    if kills:
        lines.append("  RECENT RISK BLOCKS")
        lines.append("  " + "-" * 56)
        for k in kills:
            ts = str(k["ts"])
            try:
                t = ts[11:16]
            except Exception:
                t = "??:??"
            lines.append(f"  {t} {str(k['market_id'] or '')[:20]:<20} {k['reason']}")
        lines.append("")

    # Realized PnL entries
    pnl_rows = db.conn.execute(
        "SELECT ts, market_id, amount_usdc, note FROM realized_pnl ORDER BY pnl_id DESC LIMIT 10"
    ).fetchall()

    if pnl_rows:
        lines.append("  REALIZED P&L HISTORY")
        lines.append("  " + "-" * 56)
        lines.append(f"  {'Time':>8} {'Market':<24} {'PnL':>12} {'Reason':<12}")
        lines.append("  " + "-" * 56)
        for r in pnl_rows:
            ts = str(r["ts"])
            try:
                t = ts[11:16]
            except Exception:
                t = "??:??"
            pnl = float(Decimal(r["amount_usdc"]))
            slug = str(r["market_id"])[:24]
            note = str(r["note"] or "")[:12]
            lines.append(f"  {t:>8} {slug:<24} {format_pnl(pnl):>12} {note:<12}")
        lines.append("")

    # Cash ledger summary
    ledger = db.conn.execute(
        "SELECT kind, COUNT(*) as n, SUM(CAST(amount_usdc AS REAL)) as total "
        "FROM cash_ledger GROUP BY kind ORDER BY total"
    ).fetchall()

    if ledger:
        lines.append("  CASH LEDGER SUMMARY")
        lines.append("  " + "-" * 56)
        for row in ledger:
            total = float(row["total"])
            lines.append(f"  {row['kind']:<24} {row['n']:>6} entries  {format_pnl(total):>14}")
        lines.append("")

    lines.append("=" * 60)
    lines.append("  Ctrl+C to exit  |  --once for single snapshot")
    lines.append("=" * 60)

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Portfolio watcher dashboard")
    parser.add_argument("--db", default="data/bot.db", help="SQLite database path")
    parser.add_argument("--once", action="store_true", help="Print once and exit")
    parser.add_argument("--refresh", type=int, default=5, help="Refresh interval in seconds")
    args = parser.parse_args()

    if not Path(args.db).exists():
        print(f"Database not found: {args.db}")
        print("Run the bot first to create it: python run_bot.py --mode replay --ticks 50 --prior 0.60")
        sys.exit(1)

    settings = Settings()
    db = Database(args.db)

    if args.once:
        print(build_dashboard(db, settings))
        db.close()
        return

    try:
        while True:
            clear_screen()
            print(build_dashboard(db, settings))
            time.sleep(args.refresh)
    except KeyboardInterrupt:
        print("\nDashboard stopped.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
