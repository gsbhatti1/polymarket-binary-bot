"""
Continuous bot runner.

Ties together: market discovery → signal generation → strategy →
risk check → execution → resolution checking → exit management.

Modes:
  replay       — static JSONL books, paper fills (offline testing)
  live_feed    — real CLOB books, paper fills (validate with real data)
  live         — real CLOB books, real CLOB fills (production)
"""
from __future__ import annotations

import logging
import signal
import sys
import time
from decimal import Decimal

from .config import Settings
from .db import Database
from .execution.paper import PaperExchangeAdapter
from .market_feed import PolymarketFeed
from .models import SignalEvidence
from .replay import ReplaySource
from .resolver import Resolver
from .risk import RiskEngine
from .service import BotService
from .signals import generate_signals
from .strategy import BayesianKellyStrategy

log = logging.getLogger("polymarket-bot")

RUNNING = True


def _handle_signal(sig, frame):
    global RUNNING
    RUNNING = False
    log.info("Shutdown signal received")


def build_service(mode: str, db_path: str, settings: Settings) -> BotService:
    db = Database(db_path)
    strategy = BayesianKellyStrategy(settings)
    risk = RiskEngine(settings, db)

    if mode == "replay":
        from .execution.paper import PaperExchangeAdapter
        from .replay import ReplaySource
        adapter = PaperExchangeAdapter(ReplaySource(settings.replay_path), settings)
    elif mode == "live_feed":
        from .execution.live_feed_adapter import LiveFeedPaperAdapter
        adapter = LiveFeedPaperAdapter(PolymarketFeed(), settings)
    elif mode == "live":
        from .execution.live import LivePolymarketAdapter
        adapter = LivePolymarketAdapter()
    else:
        raise ValueError(f"Unknown mode: {mode}")

    return BotService(settings=settings, db=db, adapter=adapter, strategy=strategy, risk=risk)


def run_loop(
    mode: str,
    db_path: str,
    markets: list[str],
    prior: Decimal = Decimal("0.50"),
    max_ticks: int = 0,
) -> None:
    """
    Main continuous loop.

    Args:
        mode: replay | live_feed | live
        db_path: SQLite path
        markets: list of market slugs to trade
        prior: default prior probability (0.50 = no opinion)
        max_ticks: 0 = run forever, >0 = run N ticks then stop
    """
    global RUNNING
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    settings = Settings()
    service = build_service(mode, db_path, settings)

    # Set up resolver for position exits (only with real feed)
    resolver = None
    if mode in ("live_feed", "live"):
        feed = PolymarketFeed()
        resolver = Resolver(service.db, feed)

    tick = 0
    log.info(
        "Bot starting: mode=%s markets=%s interval=%ds",
        mode, markets, settings.poll_interval_sec,
    )

    while RUNNING:
        tick += 1
        if max_ticks > 0 and tick > max_ticks:
            break

        log.info("── tick %d ──", tick)

        # ── 1. Trade each market ─────────────────────────────
        for market_slug in markets:
            try:
                # Generate prior-based signals
                # (service.run_once fetches the book internally)
                from .models import OrderBookSnapshot, BookLevel
                signals: list[SignalEvidence] = []

                # If we have a live feed, pre-fetch book for signal generation
                if mode in ("live_feed", "live"):
                    try:
                        book = service.adapter.get_orderbook(market_slug)
                        signals = generate_signals(book, prior_probability=prior)
                    except Exception as e:
                        log.warning("[%s] book fetch for signals failed: %r", market_slug, e)

                if not signals:
                    # Fallback: use prior-only evidence
                    edge_est = prior - Decimal("0.50")
                    if edge_est > Decimal("0.01"):
                        signals = [SignalEvidence(
                            name="prior_edge",
                            weight=abs(edge_est) * 2,
                            positive=edge_est > 0,
                        )]
                    else:
                        log.debug("[%s] no signals and no prior edge, skipping", market_slug)
                        continue

                log.info(
                    "[%s] signals: %s",
                    market_slug,
                    ", ".join(f"{s.name}={'+'if s.positive else '-'}{s.weight}" for s in signals),
                )

                result = service.run_once(
                    market_id=market_slug,
                    prior_probability=prior,
                    evidence=signals,
                )

                if result.order_id:
                    log.info(
                        "[%s] %s qty=%.4f spent=$%.4f",
                        market_slug, result.fill_status,
                        float(result.filled_qty), float(result.spent_usdc),
                    )
                else:
                    log.info("[%s] skip: %s", market_slug, result.decision_reason)

            except Exception as e:
                log.warning("[%s] tick error: %r", market_slug, e)

        # ── 2. Check resolutions (every N ticks) ─────────────
        if resolver and tick % settings.resolve_check_every == 0:
            try:
                closed = resolver.check_and_close_resolved()
                for c in closed:
                    log.info(
                        "[CLOSED] %s pnl=$%.4f reason=%s",
                        c.market_id, float(c.pnl), c.reason,
                    )
            except Exception as e:
                log.warning("Resolution check error: %r", e)

            # SL/TP check
            try:
                exits = resolver.check_exit_conditions(
                    stop_loss_pct=settings.stop_loss_pct,
                    take_profit_pct=settings.take_profit_pct,
                )
                for c in exits:
                    log.info(
                        "[EXIT] %s pnl=$%.4f reason=%s",
                        c.market_id, float(c.pnl), c.reason,
                    )
            except Exception as e:
                log.warning("Exit check error: %r", e)

        # ── 3. Status log ─────────────────────────────────────
        if tick % 10 == 0:
            try:
                cash = service.db.cash_balance(settings.bankroll_usdc)
                notional = service.db.sum_open_notional()
                log.info(
                    "[STATUS] tick=%d cash=$%.2f open_notional=$%.2f",
                    tick, float(cash), float(notional),
                )
            except Exception:
                pass

        # ── 4. Sleep ──────────────────────────────────────────
        if mode == "replay":
            # Replay mode: no sleep needed (fast backtesting)
            pass
        else:
            for _ in range(settings.poll_interval_sec * 2):
                if not RUNNING:
                    break
                time.sleep(0.5)

    log.info("Bot stopped after %d ticks", tick)
    service.db.close()
