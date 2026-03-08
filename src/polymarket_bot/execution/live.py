"""
Live Polymarket CLOB adapter.

Wires py-clob-client for real order placement.
Env vars: POLY_PRIVATE_KEY, POLY_API_KEY, POLY_API_SECRET, POLY_API_PASSPHRASE
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN

from .base import ExchangeAdapter
from ..market_feed import PolymarketFeed
from ..models import BookLevel, FillResult, OrderBookSnapshot, OrderRequest

log = logging.getLogger("polymarket-bot")

try:
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import OrderArgs, OrderType
    from py_clob_client.constants import POLYGON
except ImportError:
    ClobClient = None
    OrderArgs = None
    OrderType = None
    POLYGON = 137


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


class LivePolymarketAdapter(ExchangeAdapter):
    """
    Real Polymarket CLOB execution.

    Uses PolymarketFeed for orderbook data and py-clob-client for order placement.
    """
    mode = "live"

    def __init__(self) -> None:
        if ClobClient is None:
            raise RuntimeError(
                "py_clob_client is not installed. Run: pip install py-clob-client"
            )

        private_key = _env("POLY_PRIVATE_KEY")
        if not private_key:
            raise RuntimeError("POLY_PRIVATE_KEY env var not set")

        chain = int(_env("POLY_CHAIN_ID", str(POLYGON)))
        host = _env("POLY_CLOB_HOST", "https://clob.polymarket.com")

        api_key = _env("POLY_API_KEY") or None
        api_secret = _env("POLY_API_SECRET") or None
        api_passphrase = _env("POLY_API_PASSPHRASE") or None

        if api_key and api_secret and api_passphrase:
            self.client = ClobClient(
                host, chain_id=chain, key=private_key,
                api_key=api_key, api_secret=api_secret,
                api_passphrase=api_passphrase,
            )
        else:
            log.warning("L2 credentials not set — using L1 auth only")
            self.client = ClobClient(host, chain_id=chain, key=private_key)

        self.feed = PolymarketFeed()
        self._market_cache: dict = {}
        self._order_count = 0

        log.info("LivePolymarketAdapter initialized (host=%s chain=%d)", host, chain)

    def get_orderbook(self, market_id: str) -> OrderBookSnapshot:
        """Fetch real CLOB orderbook for a market slug."""
        if market_id not in self._market_cache:
            info = self.feed.fetch_market_by_slug(market_id)
            if info is None:
                raise RuntimeError(f"Market not found: {market_id}")
            self._market_cache[market_id] = info

        market_info = self._market_cache[market_id]
        book = self.feed.fetch_orderbook_for_market(market_info)
        if book is None:
            raise RuntimeError(f"Could not fetch orderbook for {market_id}")
        return book

    def place_order(self, order: OrderRequest) -> FillResult:
        """Place a real order on Polymarket CLOB."""
        self._order_count += 1
        ts = datetime.now(timezone.utc).isoformat()
        order_id = f"live-{self._order_count:06d}"

        # Resolve token_id for the market
        market_info = self._market_cache.get(order.market_id)
        if not market_info:
            market_info = self.feed.fetch_market_by_slug(order.market_id)
            if market_info:
                self._market_cache[order.market_id] = market_info

        if not market_info or not market_info.yes_token_id:
            return FillResult(
                order_id=order_id, market_id=order.market_id, side=order.side,
                requested_qty=order.quantity, filled_qty=Decimal("0"),
                avg_price=order.limit_price, fee_paid=Decimal("0"),
                status="rejected", ts=ts, venue="live",
                note="no_token_id",
            )

        # Determine token based on side
        if "YES" in order.side.upper():
            token_id = market_info.yes_token_id
            clob_side = "BUY"
        elif "NO" in order.side.upper():
            token_id = market_info.no_token_id or market_info.yes_token_id
            clob_side = "SELL"
        else:
            clob_side = "BUY"
            token_id = market_info.yes_token_id

        price = float(order.limit_price)
        size = float(order.quantity)

        if price <= 0 or price >= 1 or size <= 0:
            return FillResult(
                order_id=order_id, market_id=order.market_id, side=order.side,
                requested_qty=order.quantity, filled_qty=Decimal("0"),
                avg_price=order.limit_price, fee_paid=Decimal("0"),
                status="rejected", ts=ts, venue="live",
                note=f"invalid_params:price={price},size={size}",
            )

        try:
            order_args = OrderArgs(
                token_id=str(token_id),
                price=round(price, 4),
                size=round(size, 4),
                side=clob_side,
            )
            signed = self.client.create_order(order_args)
            resp = self.client.post_order(signed, OrderType.GTC)
        except Exception as e:
            log.exception("CLOB order failed: %s", e)
            return FillResult(
                order_id=order_id, market_id=order.market_id, side=order.side,
                requested_qty=order.quantity, filled_qty=Decimal("0"),
                avg_price=order.limit_price, fee_paid=Decimal("0"),
                status="error", ts=ts, venue="live",
                note=f"{e.__class__.__name__}:{e}",
            )

        if resp is None:
            return FillResult(
                order_id=order_id, market_id=order.market_id, side=order.side,
                requested_qty=order.quantity, filled_qty=Decimal("0"),
                avg_price=order.limit_price, fee_paid=Decimal("0"),
                status="rejected", ts=ts, venue="live", note="null_response",
            )

        # Parse CLOB response
        real_id = resp.get("orderID") or resp.get("id") or resp.get("orderId") or order_id
        status = resp.get("status", "unknown")
        error_msg = resp.get("errorMsg") or resp.get("error")

        if error_msg:
            log.error("CLOB rejected: %s", error_msg)
            return FillResult(
                order_id=str(real_id), market_id=order.market_id, side=order.side,
                requested_qty=order.quantity, filled_qty=Decimal("0"),
                avg_price=order.limit_price, fee_paid=Decimal("0"),
                status="rejected", ts=ts, venue="live", note=str(error_msg)[:200],
            )

        filled_size = Decimal(str(resp.get("filledSize", 0) or 0))
        avg_price = Decimal(str(resp.get("avgPrice", price) or price))
        fee = filled_size * avg_price * Decimal("0.001")  # ~10 bps estimate

        fill_status = "filled" if filled_size >= order.quantity else "partial" if filled_size > 0 else "unfilled"

        log.info(
            "LIVE ORDER OK id=%s status=%s filled=%.4f price=%.4f",
            real_id, status, float(filled_size), float(avg_price),
        )

        return FillResult(
            order_id=str(real_id), market_id=order.market_id, side=order.side,
            requested_qty=order.quantity, filled_qty=filled_size,
            avg_price=avg_price, fee_paid=fee,
            status=fill_status, ts=ts, venue="live",
            note=f"clob_status:{status}",
        )
