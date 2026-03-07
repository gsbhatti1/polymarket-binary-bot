from decimal import Decimal
from pathlib import Path

from polymarket_bot.config import Settings
from polymarket_bot.db import Database
from polymarket_bot.execution.paper import PaperExchangeAdapter
from polymarket_bot.models import SignalEvidence
from polymarket_bot.replay import ReplaySource
from polymarket_bot.risk import RiskEngine
from polymarket_bot.service import BotService
from polymarket_bot.strategy import BayesianKellyStrategy


def test_service_places_and_records_order(tmp_path: Path):
    db = Database((tmp_path / "bot.db").as_posix())
    settings = Settings()
    adapter = PaperExchangeAdapter(ReplaySource("replay/sample_btc_book.jsonl"), settings)
    strategy = BayesianKellyStrategy(settings)
    risk = RiskEngine(settings, db)
    service = BotService(settings=settings, db=db, adapter=adapter, strategy=strategy, risk=risk)

    result = service.run_once(
        market_id="BTC_UP",
        prior_probability=Decimal("0.57"),
        evidence=[SignalEvidence("flow", Decimal("0.2"), True)],
    )

    assert result.order_id is not None
    assert db.count_rows("orders") == 1
    assert db.count_rows("fills") == 1
    assert db.count_rows("cash_ledger") == 1
