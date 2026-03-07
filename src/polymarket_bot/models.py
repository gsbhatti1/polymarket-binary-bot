from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import List


@dataclass(frozen=True)
class BookLevel:
    price: Decimal
    size: Decimal


@dataclass(frozen=True)
class OrderBookSnapshot:
    ts: str
    market_id: str
    best_bid: Decimal
    best_ask: Decimal
    bids: List[BookLevel] = field(default_factory=list)
    asks: List[BookLevel] = field(default_factory=list)


@dataclass(frozen=True)
class SignalEvidence:
    name: str
    weight: Decimal
    positive: bool = True


@dataclass(frozen=True)
class MarketState:
    market_id: str
    prior_probability: Decimal
    orderbook: OrderBookSnapshot
    evidence: List[SignalEvidence] = field(default_factory=list)


@dataclass(frozen=True)
class SizingDecision:
    posterior_probability: Decimal
    net_edge: Decimal
    kelly_fraction: Decimal
    target_notional_usdc: Decimal
    limit_price: Decimal
    side: str
    reason: str


@dataclass(frozen=True)
class OrderRequest:
    market_id: str
    side: str
    limit_price: Decimal
    quantity: Decimal
    strategy_name: str
    client_order_id: str


@dataclass(frozen=True)
class FillResult:
    order_id: str
    market_id: str
    side: str
    requested_qty: Decimal
    filled_qty: Decimal
    avg_price: Decimal
    fee_paid: Decimal
    status: str
    ts: str
    venue: str
    note: str = ""


@dataclass(frozen=True)
class RiskState:
    bankroll_usdc: Decimal
    cash_usdc: Decimal
    total_open_notional: Decimal
    market_open_notional: Decimal
    realized_pnl_today: Decimal
