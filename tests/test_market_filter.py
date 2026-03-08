"""Tests for market filter and drawdown circuit breaker."""
from decimal import Decimal
from pathlib import Path

from polymarket_bot.models import BookLevel, OrderBookSnapshot
from polymarket_bot.market_filter import check_market_quality
from polymarket_bot.config import Settings
from polymarket_bot.db import Database
from polymarket_bot.risk import RiskEngine


def _book(bid="0.45", ask="0.55", bid_size="200", ask_size="200"):
    return OrderBookSnapshot(
        ts="2026-01-01T00:00:00Z", market_id="TEST",
        best_bid=Decimal(bid), best_ask=Decimal(ask),
        bids=[BookLevel(Decimal(bid), Decimal(bid_size))],
        asks=[BookLevel(Decimal(ask), Decimal(ask_size))],
    )


# ── Market Filter Tests ──────────────────────────────────

def test_filter_passes_normal_market():
    result = check_market_quality(_book("0.48", "0.52", "300", "300"))
    assert result.tradeable
    assert result.reason == "ok"


def test_filter_rejects_extreme_high():
    result = check_market_quality(_book("0.88", "0.92"))
    assert not result.tradeable
    assert "price_too_high" in result.reason


def test_filter_rejects_extreme_low():
    result = check_market_quality(_book("0.05", "0.10"))
    assert not result.tradeable
    assert "price_too_low" in result.reason


def test_filter_rejects_wide_spread():
    result = check_market_quality(_book("0.30", "0.50"))  # 40% spread relative to mid
    assert not result.tradeable
    assert "spread_too_wide" in result.reason


def test_filter_rejects_thin_book():
    result = check_market_quality(_book("0.49", "0.51", "10", "10"))
    assert not result.tradeable
    assert "thin" in result.reason


# ── Drawdown Circuit Breaker Tests ────────────────────────

def test_drawdown_breaker_allows_when_no_drawdown(tmp_path: Path):
    db = Database((tmp_path / "bot.db").as_posix())
    settings = Settings()
    risk = RiskEngine(settings, db)
    # No trades yet, cash = bankroll, no drawdown
    decision = risk.pre_trade_check("TEST", Decimal("5"), "2026-03-08")
    assert decision.allowed


def test_drawdown_breaker_blocks_after_large_loss(tmp_path: Path):
    db = Database((tmp_path / "bot.db").as_posix())
    settings = Settings()
    risk = RiskEngine(settings, db)

    # Simulate: peak was $100 (bankroll), then we lost $20
    db.add_cash_entry("2026-03-08T02:00:00Z", "buy_yes", Decimal("-20"))

    # Set peak equity to bankroll ($100), cash is now $80
    # Drawdown = (100 - 80) / 100 = 20% > 15% threshold
    risk._peak_equity = Decimal("100")
    risk._peak_date = "2026-03-08"
    decision = risk.pre_trade_check("TEST", Decimal("5"), "2026-03-08")
    assert not decision.allowed
    assert "drawdown_circuit_breaker" in decision.reason
