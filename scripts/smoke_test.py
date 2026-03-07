from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from polymarket_bot.config import Settings
from polymarket_bot.db import Database
from polymarket_bot.execution.paper import PaperExchangeAdapter
from polymarket_bot.replay import ReplaySource
from polymarket_bot.risk import RiskEngine
from polymarket_bot.service import BotService
from polymarket_bot.strategy import BayesianKellyStrategy
from polymarket_bot.models import SignalEvidence


def main() -> None:
    db_path = ROOT / "data" / "smoke.db"
    if db_path.exists():
        db_path.unlink()

    settings = Settings()
    db = Database(db_path.as_posix())
    adapter = PaperExchangeAdapter(ReplaySource((ROOT / "replay" / "sample_btc_book.jsonl").as_posix()), settings)
    strategy = BayesianKellyStrategy(settings)
    risk = RiskEngine(settings, db)
    service = BotService(settings=settings, db=db, adapter=adapter, strategy=strategy, risk=risk)

    result = service.run_once(
        market_id="BTC_UP",
        prior_probability=Decimal("0.57"),
        evidence=[
            SignalEvidence("flow", Decimal("0.18"), True),
            SignalEvidence("news", Decimal("0.07"), True),
        ],
    )
    print("SMOKE_OK", result)


if __name__ == "__main__":
    main()
