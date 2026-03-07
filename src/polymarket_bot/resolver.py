"""
Market resolution and position exit management.

Handles:
  - Checking if open positions' markets have resolved
  - Closing positions and realizing PnL
  - Stop-loss / take-profit exits via live price
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from .db import Database
from .market_feed import PolymarketFeed

log = logging.getLogger("polymarket-bot")


@dataclass(frozen=True)
class CloseResult:
    market_id: str
    yes_qty: Decimal
    avg_cost: Decimal
    exit_price: Decimal
    pnl: Decimal
    reason: str


class Resolver:
    def __init__(self, db: Database, feed: PolymarketFeed) -> None:
        self.db = db
        self.feed = feed

    def check_and_close_resolved(self) -> list[CloseResult]:
        """Check all open positions for resolution. Close any that resolved."""
        closed = []
        rows = self.db.conn.execute(
            "SELECT market_id, yes_qty, avg_yes_cost FROM positions WHERE CAST(yes_qty AS REAL) > 0"
        ).fetchall()

        for row in rows:
            market_id = row["market_id"]
            yes_qty = Decimal(row["yes_qty"])
            avg_cost = Decimal(row["avg_yes_cost"])

            if yes_qty <= 0:
                continue

            resolution = self.feed.check_resolution(market_id)
            if resolution is None:
                continue

            result = self._close_position(market_id, yes_qty, avg_cost, resolution, "market_resolved")
            if result:
                closed.append(result)
                log.info(
                    "[RESOLVED] %s → exit=%.2f pnl=$%.4f (%s)",
                    market_id, float(resolution), float(result.pnl),
                    "WIN" if result.pnl > 0 else "LOSS"
                )

        return closed

    def check_exit_conditions(
        self,
        stop_loss_pct: Decimal = Decimal("0.30"),
        take_profit_pct: Decimal = Decimal("0.50"),
    ) -> list[CloseResult]:
        """Check open positions for SL/TP exits using live mid price."""
        closed = []
        rows = self.db.conn.execute(
            "SELECT market_id, yes_qty, avg_yes_cost FROM positions WHERE CAST(yes_qty AS REAL) > 0"
        ).fetchall()

        for row in rows:
            market_id = row["market_id"]
            yes_qty = Decimal(row["yes_qty"])
            avg_cost = Decimal(row["avg_yes_cost"])

            if yes_qty <= 0:
                continue

            book = self._get_mid_price(market_id)
            if book is None:
                continue

            mid = book
            if avg_cost <= 0:
                continue

            pct_change = (mid - avg_cost) / avg_cost

            # Stop-loss
            if stop_loss_pct > 0 and pct_change <= -stop_loss_pct:
                result = self._close_position(market_id, yes_qty, avg_cost, mid, "stop_loss")
                if result:
                    closed.append(result)
                    log.info("[SL] %s pct=%.1f%% mid=%.4f entry=%.4f", market_id, float(pct_change * 100), float(mid), float(avg_cost))

            # Take-profit
            elif take_profit_pct > 0 and pct_change >= take_profit_pct:
                result = self._close_position(market_id, yes_qty, avg_cost, mid, "take_profit")
                if result:
                    closed.append(result)
                    log.info("[TP] %s pct=%.1f%% mid=%.4f entry=%.4f", market_id, float(pct_change * 100), float(mid), float(avg_cost))

        return closed

    def _get_mid_price(self, market_id: str) -> Decimal | None:
        """Get current mid price for a market slug."""
        market = self.feed.fetch_market_by_slug(market_id)
        if market is None or not market.yes_token_id:
            return None
        book = self.feed.fetch_orderbook(market.yes_token_id)
        if book is None:
            return None
        return (book.best_bid + book.best_ask) / 2

    def _close_position(
        self,
        market_id: str,
        yes_qty: Decimal,
        avg_cost: Decimal,
        exit_price: Decimal,
        reason: str,
    ) -> CloseResult | None:
        """Close a position: zero out qty, credit cash, record PnL."""
        ts = datetime.now(timezone.utc).isoformat()

        # PnL for binary YES: (exit_price - avg_cost) × qty
        pnl = (exit_price - avg_cost) * yes_qty

        # Zero out the position
        self.db.conn.execute(
            """
            UPDATE positions
            SET yes_qty = '0', realized_pnl = CAST(
                CAST(realized_pnl AS REAL) + ? AS TEXT
            ), updated_ts = ?
            WHERE market_id = ?
            """,
            (str(pnl), ts, market_id),
        )

        # Credit cash: return principal + pnl
        proceeds = (exit_price * yes_qty)
        self.db.add_cash_entry(ts, f"sell_{reason}", proceeds, market_id=market_id, note=reason)

        # Record realized PnL
        self.db.add_realized_pnl(ts, market_id, pnl, note=reason)
        self.db.conn.commit()

        return CloseResult(
            market_id=market_id,
            yes_qty=yes_qty,
            avg_cost=avg_cost,
            exit_price=exit_price,
            pnl=pnl,
            reason=reason,
        )
