from __future__ import annotations

from .base import ExchangeAdapter
from ..models import OrderBookSnapshot, OrderRequest, FillResult


class LivePolymarketAdapter(ExchangeAdapter):
    """
    Live adapter scaffold.

    Intentionally minimal in this generated repo. Wire the official Polymarket
    client, auth, and venue-specific error handling here. The service path remains
    identical; only the adapter changes.
    """
    mode = "live"

    def get_orderbook(self, market_id: str) -> OrderBookSnapshot:
        raise NotImplementedError("Wire live Polymarket market data here.")

    def place_order(self, order: OrderRequest) -> FillResult:
        raise NotImplementedError("Wire live Polymarket order placement here.")
