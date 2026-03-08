"""
PolyMarket Binary Bot — Entry Point.

Usage:
    # Replay mode (offline, static books, fast):
    python run_bot.py --mode replay --market BTC_UP --ticks 100

    # Live feed mode (real books from CLOB API, paper fills):
    python run_bot.py --mode live_feed --market will-x-happen --prior 0.55

    # Single-shot (original behavior):
    python run_bot.py --mode paper --market BTC_UP --once

    # Live mode (real books + real fills — production):
    python run_bot.py --mode live --market will-x-happen
"""
from __future__ import annotations

import argparse
import logging
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from polymarket_bot.config import Settings
from polymarket_bot.models import SignalEvidence


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Polymarket Binary Bot")
    parser.add_argument("--mode", choices=["replay", "paper", "live_feed", "live"], default="replay",
                        help="replay=static books | paper=replay+once | live_feed=real books+paper fills | live=production")
    parser.add_argument("--db", default="data/bot.db", help="SQLite database path")
    parser.add_argument("--market", nargs="+", default=["BTC_UP"],
                        help="Market slug(s) to trade (space-separated)")
    parser.add_argument("--prior", default="0.50", help="Default prior probability")
    parser.add_argument("--ticks", type=int, default=0, help="Max ticks (0=forever)")
    parser.add_argument("--once", action="store_true", help="Run single tick and exit (original behavior)")
    parser.add_argument("--evidence", nargs="*", default=None,
                        help="Manual evidence for --once mode: flow:+0.12 news:+0.08")
    parser.add_argument("--auto-discover", action="store_true",
                        help="Auto-discover tradeable markets from Polymarket (live_feed/live modes)")
    parser.add_argument("--log-level", default="INFO", help="Logging level")
    return parser.parse_args()


def parse_evidence(items: list[str]) -> list[SignalEvidence]:
    parsed: list[SignalEvidence] = []
    for item in items:
        name, raw = item.split(":")
        positive = not raw.startswith("-")
        weight = Decimal(raw.replace("+", ""))
        parsed.append(SignalEvidence(name=name, weight=abs(weight), positive=positive))
    return parsed


def run_once(args: argparse.Namespace) -> None:
    """Original single-shot behavior for backward compatibility."""
    from polymarket_bot.db import Database
    from polymarket_bot.execution.paper import PaperExchangeAdapter
    from polymarket_bot.replay import ReplaySource
    from polymarket_bot.risk import RiskEngine
    from polymarket_bot.service import BotService
    from polymarket_bot.strategy import BayesianKellyStrategy

    settings = Settings()
    db = Database(args.db)
    adapter = PaperExchangeAdapter(ReplaySource(settings.replay_path), settings)
    strategy = BayesianKellyStrategy(settings)
    risk = RiskEngine(settings, db)
    service = BotService(settings=settings, db=db, adapter=adapter, strategy=strategy, risk=risk)

    evidence = parse_evidence(args.evidence or ["flow:+0.12", "news:+0.08"])
    market = args.market[0] if isinstance(args.market, list) else args.market

    result = service.run_once(
        market_id=market,
        prior_probability=Decimal(args.prior),
        evidence=evidence,
    )
    print(result)


def run_continuous(args: argparse.Namespace) -> None:
    """Continuous loop mode."""
    from polymarket_bot.runner import run_loop

    run_loop(
        mode=args.mode,
        db_path=args.db,
        markets=args.market if isinstance(args.market, list) else [args.market],
        prior=Decimal(args.prior),
        max_ticks=args.ticks,
        auto_discover=getattr(args, "auto_discover", False),
    )


def main() -> None:
    args = parse_args()
    setup_logging(args.log_level)

    if args.once or args.mode == "paper":
        run_once(args)
    else:
        run_continuous(args)


if __name__ == "__main__":
    main()
