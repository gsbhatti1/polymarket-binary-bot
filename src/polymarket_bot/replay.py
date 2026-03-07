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
        self._items = list(load_jsonl_books(path))
        self._idx = 0

    def next(self) -> OrderBookSnapshot:
        if not self._items:
            raise RuntimeError("replay source is empty")
        item = self._items[self._idx % len(self._items)]
        self._idx += 1
        return item
