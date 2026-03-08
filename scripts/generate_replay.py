"""
Generate realistic multi-market replay data for testing.

Creates JSONL orderbook snapshots with:
  - Multiple markets (political, crypto, sports)
  - Price movements over time (random walk)
  - Volume variation
  - Some markets resolve during the sequence

Usage:
    python scripts/generate_replay.py
    python scripts/generate_replay.py --markets 5 --ticks 500 --output replay/multi_market.jsonl
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

MARKET_TEMPLATES = [
    {"market_id": "will-btc-hit-100k-2026", "start_price": 0.62, "volatility": 0.015, "resolve_at": None},
    {"market_id": "will-fed-cut-rates-june", "start_price": 0.45, "volatility": 0.008, "resolve_at": 400},
    {"market_id": "will-trump-win-2028", "start_price": 0.38, "volatility": 0.005, "resolve_at": None},
    {"market_id": "will-eth-flip-btc-2026", "start_price": 0.12, "volatility": 0.020, "resolve_at": None},
    {"market_id": "will-ai-pass-bar-exam", "start_price": 0.71, "volatility": 0.010, "resolve_at": 300},
    {"market_id": "will-spacex-mars-2026", "start_price": 0.08, "volatility": 0.012, "resolve_at": None},
    {"market_id": "will-inflation-below-3pct", "start_price": 0.55, "volatility": 0.007, "resolve_at": 450},
    {"market_id": "will-nfl-ravens-win-sb", "start_price": 0.22, "volatility": 0.018, "resolve_at": 200},
]


def generate_book(market_id: str, price: float, tick: int, base_time: datetime) -> dict:
    """Generate a single orderbook snapshot."""
    ts = base_time + timedelta(seconds=tick * 30)

    spread = random.uniform(0.02, 0.06)
    bid = max(0.01, price - spread / 2)
    ask = min(0.99, price + spread / 2)

    # Generate depth (3-5 levels per side)
    n_levels = random.randint(3, 5)
    bids = []
    asks = []

    for i in range(n_levels):
        bid_px = round(bid - i * random.uniform(0.01, 0.03), 4)
        ask_px = round(ask + i * random.uniform(0.01, 0.03), 4)
        bid_sz = random.randint(50, 800)
        ask_sz = random.randint(50, 800)
        if bid_px > 0.01:
            bids.append([str(bid_px), str(bid_sz)])
        if ask_px < 0.99:
            asks.append([str(ask_px), str(ask_sz)])

    return {
        "ts": ts.isoformat().replace("+00:00", "Z"),
        "market_id": market_id,
        "best_bid": str(round(bid, 4)),
        "best_ask": str(round(ask, 4)),
        "bids": bids,
        "asks": asks,
    }


def generate_replay(n_markets: int = 5, n_ticks: int = 500, seed: int = 42) -> list[dict]:
    """Generate interleaved multi-market replay data."""
    random.seed(seed)
    base_time = datetime(2026, 3, 8, 12, 0, 0, tzinfo=timezone.utc)

    markets = MARKET_TEMPLATES[:n_markets]
    prices = {m["market_id"]: m["start_price"] for m in markets}
    resolved = set()
    books = []

    for tick in range(n_ticks):
        for m in markets:
            mid = m["market_id"]
            if mid in resolved:
                continue

            # Check resolution
            if m["resolve_at"] and tick >= m["resolve_at"]:
                resolved.add(mid)
                # Final book at resolution price (0 or 1)
                final_price = 1.0 if prices[mid] > 0.5 else 0.0
                prices[mid] = final_price
                book = generate_book(mid, final_price, tick, base_time)
                books.append(book)
                continue

            # Random walk price
            change = random.gauss(0, m["volatility"])
            prices[mid] = max(0.02, min(0.98, prices[mid] + change))

            book = generate_book(mid, prices[mid], tick, base_time)
            books.append(book)

    return books


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--markets", type=int, default=5)
    parser.add_argument("--ticks", type=int, default=500)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", default="replay/multi_market.jsonl")
    args = parser.parse_args()

    books = generate_replay(args.markets, args.ticks, args.seed)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w") as f:
        for b in books:
            f.write(json.dumps(b) + "\n")

    # Stats
    market_ids = set(b["market_id"] for b in books)
    print(f"Generated {len(books)} orderbook snapshots")
    print(f"Markets: {len(market_ids)}")
    for mid in sorted(market_ids):
        count = sum(1 for b in books if b["market_id"] == mid)
        print(f"  {mid}: {count} ticks")
    print(f"Output: {args.output}")


if __name__ == "__main__":
    main()
