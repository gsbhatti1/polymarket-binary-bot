from decimal import Decimal

from polymarket_bot.models import BookLevel, OrderBookSnapshot
from polymarket_bot.signals import (
    signal_flow_imbalance,
    signal_spread_tightness,
    signal_lmsr_inefficiency,
    generate_signals,
)


def _book(bid_sizes=None, ask_sizes=None, best_bid="0.48", best_ask="0.52"):
    bids = [BookLevel(Decimal(best_bid), Decimal(str(s))) for s in (bid_sizes or [100])]
    asks = [BookLevel(Decimal(best_ask), Decimal(str(s))) for s in (ask_sizes or [100])]
    return OrderBookSnapshot(
        ts="2026-01-01T00:00:00Z", market_id="TEST",
        best_bid=Decimal(best_bid), best_ask=Decimal(best_ask),
        bids=bids, asks=asks,
    )


def test_flow_imbalance_heavy_bids():
    book = _book(bid_sizes=[500], ask_sizes=[100])
    sig = signal_flow_imbalance(book)
    assert sig.positive is True
    assert sig.weight > 0


def test_flow_imbalance_heavy_asks():
    book = _book(bid_sizes=[100], ask_sizes=[500])
    sig = signal_flow_imbalance(book)
    assert sig.positive is False
    assert sig.weight > 0


def test_flow_imbalance_balanced():
    book = _book(bid_sizes=[100], ask_sizes=[100])
    sig = signal_flow_imbalance(book)
    assert sig.weight == Decimal("0")


def test_lmsr_inefficiency_with_edge():
    book = _book(best_ask="0.50")
    sig = signal_lmsr_inefficiency(book, external_probability=Decimal("0.60"))
    assert sig.positive is True
    assert sig.weight > 0


def test_lmsr_inefficiency_no_edge():
    book = _book(best_ask="0.60")
    sig = signal_lmsr_inefficiency(book, external_probability=Decimal("0.50"))
    assert sig.weight == Decimal("0")


def test_generate_signals_returns_nonzero():
    book = _book(bid_sizes=[500], ask_sizes=[100])
    signals = generate_signals(book, prior_probability=Decimal("0.60"))
    assert len(signals) > 0
    assert all(s.weight > 0 for s in signals)
