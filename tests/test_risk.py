from decimal import Decimal
from pathlib import Path

from polymarket_bot.config import Settings
from polymarket_bot.db import Database
from polymarket_bot.risk import RiskEngine


def test_risk_blocks_above_per_trade_cap(tmp_path: Path):
    db = Database((tmp_path / "bot.db").as_posix())
    settings = Settings()
    risk = RiskEngine(settings, db)
    decision = risk.pre_trade_check("BTC_UP", settings.per_trade_cap_usdc + Decimal("1"), "2026-03-07")
    assert not decision.allowed
    assert decision.reason == "per_trade_cap_exceeded"
