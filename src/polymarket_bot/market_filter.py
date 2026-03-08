"""
Market quality filter.

Screens out markets where the bot has no edge:
  - Extreme probabilities (>85% or <15% — consensus already priced in)
  - Wide spreads (>10% — illiquid, high execution cost)
  - Thin books (insufficient depth to fill without impact)
  - Resolved/closed markets

Based on research: "Betting on outcomes above $0.80 usually offers no edge"
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal

from .models import OrderBookSnapshot

log = logging.getLogger("polymarket-bot")


@dataclass(frozen=True)
class FilterResult:
    tradeable: bool
    reason: str


def check_market_quality(
    book: OrderBookSnapshot,
    min_price: Decimal = Decimal("0.15"),
    max_price: Decimal = Decimal("0.85"),
    max_spread_pct: Decimal = Decimal("0.10"),
    min_depth_per_side: Decimal = Decimal("100"),
) -> FilterResult:
    """
    Check if a market is worth trading.

    Returns FilterResult with tradeable=True if it passes all checks.
    """
    mid = (book.best_bid + book.best_ask) / 2

    # Price window: skip extreme probabilities
    if mid < min_price:
        return FilterResult(False, f"price_too_low:{mid:.3f}<{min_price}")
    if mid > max_price:
        return FilterResult(False, f"price_too_high:{mid:.3f}>{max_price}")

    # Spread check: skip illiquid markets
    spread = book.best_ask - book.best_bid
    if mid > 0:
        spread_pct = spread / mid
        if spread_pct > max_spread_pct:
            return FilterResult(False, f"spread_too_wide:{spread_pct:.1%}>{max_spread_pct:.0%}")

    # Depth check: enough size to fill without massive impact
    bid_depth = sum(l.size for l in book.bids[:3]) if book.bids else Decimal("0")
    ask_depth = sum(l.size for l in book.asks[:3]) if book.asks else Decimal("0")

    if bid_depth < min_depth_per_side:
        return FilterResult(False, f"thin_bids:{bid_depth:.0f}<{min_depth_per_side}")
    if ask_depth < min_depth_per_side:
        return FilterResult(False, f"thin_asks:{ask_depth:.0f}<{min_depth_per_side}")

    # Sanity: bid must be below ask
    if book.best_bid >= book.best_ask:
        return FilterResult(False, "crossed_book")

    return FilterResult(True, "ok")
