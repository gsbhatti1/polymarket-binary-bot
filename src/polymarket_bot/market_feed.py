"""
Real Polymarket data feed.

Connects to Gamma API (market metadata) and CLOB API (orderbooks).
Falls back to replay source if API is unreachable (offline dev on Windows).
"""
from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import Optional

import httpx

from .models import BookLevel, OrderBookSnapshot

log = logging.getLogger("polymarket-bot")

GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"


class MarketInfo:
    """Parsed market metadata from Gamma API."""
    def __init__(self, raw: dict) -> None:
        self.raw = raw
        self.slug: str = raw.get("slug", "")
        self.question: str = raw.get("question", "")
        self.condition_id: str = raw.get("conditionId", "")
        self.active: bool = bool(raw.get("active", False))
        self.closed: bool = bool(raw.get("closed", False))
        self.resolved: bool = bool(raw.get("resolved", False))
        self.volume: float = float(raw.get("volume", 0) or 0)

        # Token IDs for YES/NO outcomes
        self.clob_token_ids: list[str] = []
        self.outcomes: list[str] = []
        ct = raw.get("clobTokenIds", [])
        outs = raw.get("outcomes", [])
        if isinstance(ct, str):
            try:
                ct = json.loads(ct)
            except Exception:
                ct = []
        if isinstance(outs, str):
            try:
                outs = json.loads(outs)
            except Exception:
                outs = []
        self.clob_token_ids = [str(x) for x in ct] if isinstance(ct, list) else []
        self.outcomes = [str(x) for x in outs] if isinstance(outs, list) else []

        # Resolution result
        self._result = raw.get("result") or raw.get("outcome")

    @property
    def yes_token_id(self) -> Optional[str]:
        if len(self.clob_token_ids) >= 1:
            return self.clob_token_ids[0]
        return None

    @property
    def no_token_id(self) -> Optional[str]:
        if len(self.clob_token_ids) >= 2:
            return self.clob_token_ids[1]
        return None

    @property
    def resolution_price(self) -> Optional[Decimal]:
        """Returns 1.0 if YES won, 0.0 if NO won, None if unresolved."""
        if not self.resolved and not self.closed:
            return None
        r = self._result
        if r is None:
            return None
        if r in ("Yes", "yes", True, "1", 1):
            return Decimal("1")
        if r in ("No", "no", False, "0", 0):
            return Decimal("0")
        try:
            return Decimal(str(r))
        except Exception:
            return None


class PolymarketFeed:
    """Fetches live orderbooks and market info from Polymarket APIs."""

    def __init__(self, timeout: float = 10.0) -> None:
        self._timeout = timeout

    def fetch_market_by_slug(self, slug: str) -> Optional[MarketInfo]:
        try:
            with httpx.Client(timeout=self._timeout) as c:
                r = c.get(f"{GAMMA_API}/markets", params={"slug": slug, "limit": 1})
                r.raise_for_status()
                data = r.json()
                if isinstance(data, list) and data:
                    return MarketInfo(data[0])
                return None
        except Exception as e:
            log.warning("fetch_market_by_slug(%s) failed: %r", slug, e)
            return None

    def fetch_active_binary_markets(self, limit: int = 50, min_volume: float = 10_000) -> list[MarketInfo]:
        """Fetch active binary markets sorted by volume."""
        try:
            with httpx.Client(timeout=self._timeout) as c:
                r = c.get(f"{GAMMA_API}/markets", params={
                    "active": True, "closed": False, "limit": limit,
                    "order": "volume", "ascending": False,
                })
                r.raise_for_status()
                data = r.json()
                markets = data if isinstance(data, list) else data.get("markets", [])
                result = []
                for m in markets:
                    info = MarketInfo(m)
                    if info.volume >= min_volume and len(info.clob_token_ids) == 2:
                        result.append(info)
                return result
        except Exception as e:
            log.warning("fetch_active_binary_markets failed: %r", e)
            return []

    def fetch_orderbook(self, token_id: str) -> Optional[OrderBookSnapshot]:
        """Fetch CLOB orderbook for a specific token ID."""
        paths = [
            (f"{CLOB_API}/book", {"token_id": token_id}),
            (f"{CLOB_API}/orderbook/{token_id}", None),
        ]
        for url, params in paths:
            try:
                with httpx.Client(timeout=self._timeout) as c:
                    r = c.get(url, params=params)
                    if r.status_code != 200:
                        continue
                    data = r.json()
                    return self._parse_book(data, token_id)
            except Exception:
                continue
        return None

    def fetch_orderbook_for_market(self, market: MarketInfo) -> Optional[OrderBookSnapshot]:
        """Fetch YES token orderbook for a market."""
        if not market.yes_token_id:
            return None
        book = self.fetch_orderbook(market.yes_token_id)
        if book is not None:
            # Override market_id with slug for consistency
            return OrderBookSnapshot(
                ts=book.ts,
                market_id=market.slug,
                best_bid=book.best_bid,
                best_ask=book.best_ask,
                bids=book.bids,
                asks=book.asks,
            )
        return None

    def check_resolution(self, slug: str) -> Optional[Decimal]:
        """Check if market resolved. Returns YES price (1.0 or 0.0) or None."""
        info = self.fetch_market_by_slug(slug)
        if info is None:
            return None
        return info.resolution_price

    @staticmethod
    def _parse_book(data: dict, token_id: str) -> Optional[OrderBookSnapshot]:
        from datetime import datetime, timezone

        raw_bids = data.get("bids") or data.get("buy") or []
        raw_asks = data.get("asks") or data.get("sell") or []

        def parse_levels(levels: list, is_bid: bool) -> list[BookLevel]:
            result = []
            for lvl in levels:
                try:
                    if isinstance(lvl, dict):
                        px = Decimal(str(lvl.get("price", lvl.get("p", "0"))))
                        sz = Decimal(str(lvl.get("size", lvl.get("s", "0"))))
                    elif isinstance(lvl, (list, tuple)) and len(lvl) >= 2:
                        px = Decimal(str(lvl[0]))
                        sz = Decimal(str(lvl[1]))
                    else:
                        continue
                    if px > 0 and sz > 0:
                        result.append(BookLevel(price=px, size=sz))
                except Exception:
                    continue
            result.sort(key=lambda l: l.price, reverse=is_bid)
            return result

        bids = parse_levels(raw_bids, is_bid=True)
        asks = parse_levels(raw_asks, is_bid=False)

        if not bids or not asks:
            # Try bestBid/bestAsk fallback
            bb = data.get("bestBid") or data.get("bid")
            ba = data.get("bestAsk") or data.get("ask")
            if bb is not None and ba is not None:
                bids = [BookLevel(price=Decimal(str(bb)), size=Decimal("100"))]
                asks = [BookLevel(price=Decimal(str(ba)), size=Decimal("100"))]
            else:
                return None

        return OrderBookSnapshot(
            ts=datetime.now(timezone.utc).isoformat(),
            market_id=token_id,
            best_bid=bids[0].price,
            best_ask=asks[0].price,
            bids=bids,
            asks=asks,
        )
