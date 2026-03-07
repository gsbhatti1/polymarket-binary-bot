from decimal import Decimal
from pathlib import Path

from polymarket_bot.db import Database


def test_db_schema_and_cash_balance(tmp_path: Path):
    db = Database((tmp_path / "bot.db").as_posix())
    assert db.count_rows("orders") == 0
    db.add_cash_entry("2026-03-07T00:00:00Z", "seed_adjustment", Decimal("-5"))
    cash = db.cash_balance(Decimal("100"))
    assert cash == Decimal("95.0")
