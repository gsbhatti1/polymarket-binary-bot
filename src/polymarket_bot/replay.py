from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Iterator

from .models import BookLevel, OrderBookSnapshot


def load_jsonl_books(path: str) -> Iterator[OrderBookSnapshot]:
    file_path = Path(path)
    with file_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            raw = json.loads(line)
            yield OrderBookSnapshot(
                ts=raw["ts"],
                market_id=raw["market_id"],
                best_bid=Decimal(raw["best_bid"]),
                best_ask=Decimal(raw["best_ask"]),
                bids=[BookLevel(price=Decimal(px), size=Decimal(sz)) for px, sz in raw.get("bids", [])],
                asks=[BookLevel(price=Decimal(px), size=Decimal(sz)) for px, sz in raw.get("asks", [])],
            )


class ReplaySource:
    def __init__(self, path: str) -> None:
        self._all_items = list(load_jsonl_books(path))
        # Index by market_id for multi-market support
        self._by_market: dict[str, list[OrderBookSnapshot]] = {}
        for item in self._all_items:
            self._by_market.setdefault(item.market_id, []).append(item)
        self._idx: dict[str, int] = {}

    def next(self, market_id: str | None = None) -> OrderBookSnapshot:
        if not self._all_items:
            raise RuntimeError("replay source is empty")

        # If market_id specified and we have data for it, use filtered list
        if market_id and market_id in self._by_market:
            items = self._by_market[market_id]
            idx = self._idx.get(market_id, 0)
            item = items[idx % len(items)]
            self._idx[market_id] = idx + 1
            return item

        # Fallback: cycle through all items (original behavior)
        idx = self._idx.get("__all__", 0)
        item = self._all_items[idx % len(self._all_items)]
        self._idx["__all__"] = idx + 1
        return item

    @property
    def market_ids(self) -> list[str]:
        """Return all market IDs available in the replay data."""
        return list(self._by_market.keys())
