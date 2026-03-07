from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

from polymarket_bot.db import Database
from polymarket_bot.resolver import Resolver


def test_close_position_calculates_pnl(tmp_path: Path):
    db = Database((tmp_path / "bot.db").as_posix())

    # Simulate an open position: bought 10 YES at 0.50
    db.upsert_yes_position("2026-01-01T00:00:00Z", "test-market", Decimal("10"), Decimal("0.50"))
    pos = db.get_position("test-market")
    assert Decimal(pos["yes_qty"]) == Decimal("10")

    # Mock feed that returns resolution = YES won (1.0)
    mock_feed = MagicMock()
    mock_feed.check_resolution.return_value = Decimal("1.0")

    resolver = Resolver(db, mock_feed)
    closed = resolver.check_and_close_resolved()

    assert len(closed) == 1
    assert closed[0].market_id == "test-market"
    assert closed[0].exit_price == Decimal("1.0")
    # PnL = (1.0 - 0.50) × 10 = 5.0
    assert closed[0].pnl == Decimal("5.0")

    # Position should be zeroed out
    pos_after = db.get_position("test-market")
    assert Decimal(pos_after["yes_qty"]) == Decimal("0")


def test_no_close_when_unresolved(tmp_path: Path):
    db = Database((tmp_path / "bot.db").as_posix())
    db.upsert_yes_position("2026-01-01T00:00:00Z", "open-market", Decimal("5"), Decimal("0.60"))

    mock_feed = MagicMock()
    mock_feed.check_resolution.return_value = None  # not resolved

    resolver = Resolver(db, mock_feed)
    closed = resolver.check_and_close_resolved()

    assert len(closed) == 0
