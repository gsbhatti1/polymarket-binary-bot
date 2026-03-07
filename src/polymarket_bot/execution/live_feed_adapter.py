"""
Exchange adapter that uses real Polymarket CLOB for orderbook data
but paper-simulates fills (for testing with live data before going fully live).

Sequence: replay → live_feed (paper fills) → live (real fills)
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from itertools import count

from ..config import Settings
from ..market_feed import PolymarketFeed
from ..models import FillResult, OrderBookSnapshot, OrderRequest
from .base import ExchangeAdapter


def q8(x: Decimal) -> Decimal:
    return x.quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)


class LiveFeedPaperAdapter(ExchangeAdapter):
    """
    Gets REAL orderbooks from Polymarket CLOB API.
    Simulates fills locally (paper mode with live data).

    This is the bridge between pure replay and fully live.
    """
    mode = "live_feed_paper"

    def __init__(self, feed: PolymarketFeed, settings: Settings) -> None:
        self.feed = feed
        self.settings = settings
        self._last_book: OrderBookSnapshot | None = None
        self._id_counter = count(1)
        # Cache: slug → MarketInfo (so we don't re-fetch metadata each tick)
        self._market_cache: dict = {}

    def get_orderbook(self, market_id: str) -> OrderBookSnapshot:
        """Fetch real orderbook from Polymarket CLOB for the given market slug."""
        from ..market_feed import MarketInfo

        # Resolve slug → token_id
        if market_id not in self._market_cache:
            info = self.feed.fetch_market_by_slug(market_id)
            if info is None:
                raise RuntimeError(f"Market not found on Polymarket: {market_id}")
            self._market_cache[market_id] = info

        market_info: MarketInfo = self._market_cache[market_id]
        book = self.feed.fetch_orderbook_for_market(market_info)
        if book is None:
            raise RuntimeError(f"Could not fetch orderbook for {market_id}")

        self._last_book = book
        return book

    def place_order(self, order: OrderRequest) -> FillResult:
        """Simulate fill against the real orderbook (paper execution with live data)."""
        if self._last_book is None:
            raise RuntimeError("orderbook must be fetched before order placement")

        book = self._last_book
        asks = [level for level in book.asks if level.price <= order.limit_price]
        remaining = order.quantity
        spent = Decimal("0")
        filled = Decimal("0")

        for level in asks:
            if remaining <= 0:
                break
            take = min(level.size, remaining)
            spent += take * level.price
            filled += take
            remaining -= take

        status = "filled" if remaining <= 0 and filled > 0 else "partial" if filled > 0 else "unfilled"
        avg_price = spent / filled if filled > 0 else order.limit_price
        fee_paid = (spent * self.settings.paper_fee_bps / Decimal("10000")) if filled > 0 else Decimal("0")
        ts = datetime.now(timezone.utc).isoformat()
        order_id = f"lfp-{next(self._id_counter):06d}"
        note = f"live_book_walked_{len(asks)}_levels"

        return FillResult(
            order_id=order_id,
            market_id=order.market_id,
            side=order.side,
            requested_qty=q8(order.quantity),
            filled_qty=q8(filled),
            avg_price=q8(avg_price),
            fee_paid=q8(fee_paid),
            status=status,
            ts=ts,
            venue="live_feed_paper",
            note=note,
        )
