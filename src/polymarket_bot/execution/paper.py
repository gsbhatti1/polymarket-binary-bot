from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from itertools import count

from ..config import Settings
from ..models import FillResult, OrderBookSnapshot, OrderRequest
from ..replay import ReplaySource
from .base import ExchangeAdapter


def q8(x: Decimal) -> Decimal:
    return x.quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)


class PaperExchangeAdapter(ExchangeAdapter):
    mode = "paper"

    def __init__(self, replay_source: ReplaySource, settings: Settings) -> None:
        self.replay = replay_source
        self.settings = settings
        self._last_book: OrderBookSnapshot | None = None
        self._id_counter = count(1)

    def get_orderbook(self, market_id: str) -> OrderBookSnapshot:
        book = self.replay.next()
        self._last_book = book
        return book

    def place_order(self, order: OrderRequest) -> FillResult:
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
        order_id = f"paper-{next(self._id_counter):06d}"
        note = f"walked_{len(asks)}_levels"
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
            venue="paper",
            note=note,
        )
