from __future__ import annotations

import argparse
from decimal import Decimal
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from polymarket_bot.config import Settings
from polymarket_bot.db import Database
from polymarket_bot.execution.live import LivePolymarketAdapter
from polymarket_bot.execution.paper import PaperExchangeAdapter
from polymarket_bot.replay import ReplaySource
from polymarket_bot.risk import RiskEngine
from polymarket_bot.service import BotService
from polymarket_bot.strategy import BayesianKellyStrategy
from polymarket_bot.models import SignalEvidence


def build_service(mode: str, db_path: str) -> BotService:
    settings = Settings()
    db = Database(db_path)
    strategy = BayesianKellyStrategy(settings)
    risk = RiskEngine(settings, db)

    if mode == "paper":
        adapter = PaperExchangeAdapter(ReplaySource(settings.replay_path), settings)
    elif mode == "live":
        adapter = LivePolymarketAdapter()
    else:
        raise ValueError(f"unknown mode: {mode}")

    return BotService(settings=settings, db=db, adapter=adapter, strategy=strategy, risk=risk)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["paper", "live"], default="paper")
    parser.add_argument("--db", default="data/bot.db")
    parser.add_argument("--market", default="BTC_UP")
    parser.add_argument("--prior", default="0.55")
    parser.add_argument("--evidence", nargs="*", default=["flow:+0.12", "news:+0.08"])
    return parser.parse_args()


def parse_evidence(items: list[str]) -> list[SignalEvidence]:
    parsed: list[SignalEvidence] = []
    for item in items:
        name, raw = item.split(":")
        positive = not raw.startswith("-")
        weight = Decimal(raw.replace("+", ""))
        parsed.append(SignalEvidence(name=name, weight=abs(weight), positive=positive))
    return parsed


def main() -> None:
    args = parse_args()
    service = build_service(args.mode, args.db)
    result = service.run_once(
        market_id=args.market,
        prior_probability=Decimal(args.prior),
        evidence=parse_evidence(args.evidence),
    )
    print(result)


if __name__ == "__main__":
    main()
