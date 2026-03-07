"""
Signal evidence generators for Bayesian strategy.

Based on:
  - LMSR inefficiency detection (price vs posterior divergence)
  - Order flow imbalance
  - Volume anomaly detection
  - Cross-market correlation

Each signal returns a SignalEvidence with a signed weight in log-odds space.
Positive weight = evidence for YES. Negative = evidence for NO.
"""
from __future__ import annotations

import logging
import math
from decimal import Decimal

from .models import BookLevel, OrderBookSnapshot, SignalEvidence

log = logging.getLogger("polymarket-bot")


def signal_flow_imbalance(book: OrderBookSnapshot, depth: int = 3) -> SignalEvidence:
    """
    Order flow imbalance signal.

    Compares total bid size vs ask size in top N levels.
    Heavy bids → evidence for YES (buyers aggressive).
    Heavy asks → evidence for NO (sellers aggressive).

    Weight scaled to ±0.15 log-odds.
    """
    bid_size = sum(
        float(l.size) for l in book.bids[:depth]
    ) if book.bids else 0.0
    ask_size = sum(
        float(l.size) for l in book.asks[:depth]
    ) if book.asks else 0.0

    total = bid_size + ask_size
    if total <= 0:
        return SignalEvidence(name="flow_imbalance", weight=Decimal("0"), positive=True)

    # Imbalance: -1 (all asks) to +1 (all bids)
    imbalance = (bid_size - ask_size) / total

    # Scale to max ±0.15 log-odds
    weight = Decimal(str(round(abs(imbalance) * 0.15, 4)))
    positive = imbalance > 0

    return SignalEvidence(name="flow_imbalance", weight=weight, positive=positive)


def signal_spread_tightness(book: OrderBookSnapshot) -> SignalEvidence:
    """
    Tight spread = confident market, wide spread = uncertain.

    Tight spread on YES side (ask near mid) with bid support = mild YES evidence.
    This is weak signal — max ±0.05 log-odds.
    """
    spread = float(book.best_ask - book.best_bid)
    mid = float(book.best_bid + book.best_ask) / 2.0

    if mid <= 0:
        return SignalEvidence(name="spread", weight=Decimal("0"), positive=True)

    relative_spread = spread / mid

    # Tight spread (<2%) = positive signal, wide (>8%) = negative
    if relative_spread < 0.02:
        weight = Decimal("0.05")
        positive = True
    elif relative_spread > 0.08:
        weight = Decimal("0.03")
        positive = False
    else:
        weight = Decimal("0")
        positive = True

    return SignalEvidence(name="spread", weight=weight, positive=positive)


def signal_lmsr_inefficiency(
    book: OrderBookSnapshot,
    external_probability: Decimal,
) -> SignalEvidence:
    """
    LMSR inefficiency detection.

    From the research doc (eq. 4): if our Bayesian posterior diverges
    from the LMSR-implied price by more than the spread, there's an
    exploitable inefficiency.

    Compares external_probability (our belief) vs market ask price.
    If our belief >> ask → strong buy signal.
    If our belief << ask → no signal (we don't short in v1).

    Weight = log-odds of (belief - ask) scaled by confidence.
    """
    ask = book.best_ask
    belief = external_probability

    edge = float(belief - ask)

    if edge <= 0:
        return SignalEvidence(name="lmsr_ineff", weight=Decimal("0"), positive=True)

    # Scale: 2% edge → 0.05, 5% → 0.12, 10% → 0.20, 20% → 0.30
    # Using log scaling: weight = 0.15 * ln(1 + edge/0.02)
    raw = 0.15 * math.log(1.0 + edge / 0.02)
    weight = Decimal(str(round(min(raw, 0.35), 4)))

    return SignalEvidence(name="lmsr_ineff", weight=weight, positive=True)


def signal_volume_momentum(
    current_volume: float,
    avg_volume: float,
) -> SignalEvidence:
    """
    Volume anomaly: unusually high volume = something is happening.

    Not directional by itself — combine with flow_imbalance for direction.
    Acts as a confidence multiplier: high volume → amplify other signals.
    """
    if avg_volume <= 0 or current_volume <= 0:
        return SignalEvidence(name="volume_momentum", weight=Decimal("0"), positive=True)

    ratio = current_volume / avg_volume

    if ratio > 3.0:
        weight = Decimal("0.10")
    elif ratio > 2.0:
        weight = Decimal("0.05")
    elif ratio > 1.5:
        weight = Decimal("0.02")
    else:
        weight = Decimal("0")

    return SignalEvidence(name="volume_momentum", weight=weight, positive=True)


def generate_signals(
    book: OrderBookSnapshot,
    prior_probability: Decimal | None = None,
) -> list[SignalEvidence]:
    """
    Generate all available signals from an orderbook snapshot.

    Returns list of SignalEvidence ready to feed into BayesianKellyStrategy.
    """
    signals = [
        signal_flow_imbalance(book),
        signal_spread_tightness(book),
    ]

    if prior_probability is not None:
        signals.append(signal_lmsr_inefficiency(book, prior_probability))

    # Filter out zero-weight signals
    return [s for s in signals if s.weight > 0]
