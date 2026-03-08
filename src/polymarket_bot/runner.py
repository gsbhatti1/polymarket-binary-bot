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
from . import telegram
from .market_filter import check_market_quality

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
    auto_discover: bool = False,
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

    # Set up resolver for position exits
    resolver = None
    if mode in ("live_feed", "live"):
        feed = PolymarketFeed()
        resolver = Resolver(service.db, feed)

    # In replay mode, create a lightweight resolver that uses replay book prices
    replay_resolver = None
    if mode == "replay" and hasattr(service.adapter, "replay"):
        replay_resolver = True  # flag — we'll check exits manually using book data

    # ── Auto-discover markets if requested ────────────────
    if auto_discover and mode in ("live_feed", "live"):
        try:
            feed_disc = PolymarketFeed()
            discovered = feed_disc.fetch_active_binary_markets(
                limit=settings.auto_discover_limit * 3,
                min_volume=settings.min_market_volume,
            )
            if discovered:
                disc_slugs = [m.slug for m in discovered[:settings.auto_discover_limit]]
                log.info("[DISCOVER] Found %d tradeable markets: %s", len(disc_slugs), disc_slugs[:5])
                markets = disc_slugs
            else:
                log.warning("[DISCOVER] No markets found, using provided list")
        except Exception as e:
            log.warning("[DISCOVER] Auto-discover failed: %r, using provided list", e)

    # ── In replay mode, discover markets from the replay file ──
    if mode == "replay" and hasattr(service.adapter, "replay"):
        replay_markets = service.adapter.replay.market_ids
        if replay_markets and markets == ["BTC_UP"]:
            markets = replay_markets
            log.info("[REPLAY] Found %d markets in replay file: %s", len(markets), markets[:8])

    tick = 0
    log.info(
        "Bot starting: mode=%s markets=%s interval=%ds",
        mode, markets, settings.poll_interval_sec,
    )
    telegram.send_startup(mode, markets, float(settings.bankroll_usdc))

    while RUNNING:
        tick += 1
        if max_ticks > 0 and tick > max_ticks:
            break

        log.debug("── tick %d ──", tick)

        # ── 1. Trade each market ─────────────────────────────
        tick_traded = False
        for market_slug in markets:
            try:
                # Skip BUYING if we already hold a position in this market
                # But still let the strategy evaluate for potential SELL
                existing = service.db.get_position(market_slug)
                already_holding = existing and Decimal(existing["yes_qty"]) > 0

                if already_holding and mode == "replay":
                    # In replay mode, check SL/TP using current book price
                    try:
                        book = service.adapter.get_orderbook(market_slug)
                        mid = (book.best_bid + book.best_ask) / 2
                        avg_cost = Decimal(existing["avg_yes_cost"])
                        yes_qty = Decimal(existing["yes_qty"])
                        if avg_cost > 0:
                            pct_change = (mid - avg_cost) / avg_cost
                            # Stop-loss
                            if pct_change <= -settings.stop_loss_pct:
                                from .resolver import CloseResult
                                pnl = (mid - avg_cost) * yes_qty
                                # Close the position
                                ts_now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                                service.db.conn.execute(
                                    "UPDATE positions SET yes_qty='0', updated_ts=? WHERE market_id=?",
                                    (ts_now, market_slug))
                                proceeds = mid * yes_qty
                                service.db.add_cash_entry(ts_now, "sell_stop_loss", proceeds, market_id=market_slug)
                                service.db.add_realized_pnl(ts_now, market_slug, pnl, note="stop_loss")
                                service.db.conn.commit()
                                log.info("[SL] tick=%d %s pnl=$%.4f (%.1f%%)", tick, market_slug, float(pnl), float(pct_change*100))
                                telegram.send_trade_closed(market_slug, yes_qty, avg_cost, mid, pnl, "stop_loss",
                                    service.db.cash_balance(settings.bankroll_usdc))
                            # Take-profit
                            elif pct_change >= settings.take_profit_pct:
                                pnl = (mid - avg_cost) * yes_qty
                                ts_now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                                service.db.conn.execute(
                                    "UPDATE positions SET yes_qty='0', updated_ts=? WHERE market_id=?",
                                    (ts_now, market_slug))
                                proceeds = mid * yes_qty
                                service.db.add_cash_entry(ts_now, "sell_take_profit", proceeds, market_id=market_slug)
                                service.db.add_realized_pnl(ts_now, market_slug, pnl, note="take_profit")
                                service.db.conn.commit()
                                log.info("[TP] tick=%d %s pnl=$%.4f (+%.1f%%)", tick, market_slug, float(pnl), float(pct_change*100))
                                telegram.send_trade_closed(market_slug, yes_qty, avg_cost, mid, pnl, "take_profit",
                                    service.db.cash_balance(settings.bankroll_usdc))
                    except Exception as e:
                        log.debug("[%s] replay exit check error: %r", market_slug, e)
                    continue

                if already_holding:
                    log.debug("[%s] already holding, skip buy", market_slug)
                    continue
                # Generate prior-based signals
                # (service.run_once fetches the book internally)
                from .models import OrderBookSnapshot, BookLevel
                signals: list[SignalEvidence] = []

                # If we have a live feed, pre-fetch book for signal generation
                if mode in ("live_feed", "live"):
                    try:
                        book = service.adapter.get_orderbook(market_slug)

                        # Market quality filter
                        filt = check_market_quality(
                            book,
                            min_price=settings.filter_min_price,
                            max_price=settings.filter_max_price,
                            max_spread_pct=settings.filter_max_spread_pct,
                            min_depth_per_side=settings.filter_min_depth,
                        )
                        if not filt.tradeable:
                            log.debug("[%s] filtered: %s", market_slug, filt.reason)
                            continue

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

                log.debug(
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
                    tick_traded = True
                    log.info(
                        "[TRADE] tick=%d %s %s qty=%.2f spent=$%.4f",
                        tick, market_slug, result.fill_status,
                        float(result.filled_qty), float(result.spent_usdc),
                    )
                    # Telegram alert
                    try:
                        cash_now = service.db.cash_balance(settings.bankroll_usdc)
                        telegram.send_trade_opened(
                            market_id=market_slug, side=result.decision_reason,
                            qty=result.filled_qty, price=Decimal("0"),
                            spent=result.spent_usdc, kelly_frac=Decimal("0"),
                            cash=cash_now, reason=result.decision_reason,
                        )
                    except Exception:
                        pass
                else:
                    log.debug("[%s] skip: %s", market_slug, result.decision_reason)

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
                    cash_now = service.db.cash_balance(settings.bankroll_usdc)
                    telegram.send_trade_closed(
                        market_id=c.market_id, qty=c.yes_qty,
                        entry_price=c.avg_cost, exit_price=c.exit_price,
                        pnl=c.pnl, reason=c.reason, cash=cash_now,
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
                    cash_now = service.db.cash_balance(settings.bankroll_usdc)
                    telegram.send_trade_closed(
                        market_id=c.market_id, qty=c.yes_qty,
                        entry_price=c.avg_cost, exit_price=c.exit_price,
                        pnl=c.pnl, reason=c.reason, cash=cash_now,
                    )
            except Exception as e:
                log.warning("Exit check error: %r", e)

        # ── 2b. Telegram commands (/status, /report, /positions) ──
        if tick % 3 == 0:
            try:
                for cmd, _ in telegram.poll_commands():
                    if cmd in ("/status", "/report"):
                        cash = service.db.cash_balance(settings.bankroll_usdc)
                        notional = service.db.sum_open_notional()
                        equity = cash + notional
                        return_pct = float(equity - settings.bankroll_usdc) / float(settings.bankroll_usdc) * 100
                        today_prefix = time.strftime("%Y-%m-%d", time.gmtime())
                        realized = float(service.db.realized_pnl_today(today_prefix))
                        positions = service.db.conn.execute(
                            "SELECT market_id, yes_qty, avg_yes_cost FROM positions WHERE CAST(yes_qty AS REAL) > 0"
                        ).fetchall()
                        pos_list = [dict(p) for p in positions]
                        telegram.send_status(
                            bankroll=float(settings.bankroll_usdc), cash=float(cash),
                            open_notional=float(notional), equity=float(equity),
                            return_pct=return_pct, realized_today=realized,
                            n_orders=service.db.count_rows("orders"),
                            n_fills=service.db.count_rows("fills"),
                            n_kills=service.db.count_rows("kill_events"),
                            positions=pos_list,
                        )
            except Exception:
                pass

        # ── 3. Status log (every tick, compact) ─────────────────
        try:
            cash = service.db.cash_balance(settings.bankroll_usdc)
            notional = service.db.sum_open_notional()
            equity = cash + notional
            total_return = equity - settings.bankroll_usdc
            return_pct = (float(total_return) / float(settings.bankroll_usdc) * 100) if settings.bankroll_usdc > 0 else 0.0
            n_orders = service.db.count_rows("orders")
            n_fills = service.db.count_rows("fills")

            # Full report every 10 ticks, compact every tick
            if tick % 10 == 0:
                log.info(
                    "[STATUS] tick=%d  cash=$%.2f  open=$%.2f  equity=$%.2f  return=%+.2f%%  orders=%d fills=%d",
                    tick, float(cash), float(notional), float(equity), return_pct, n_orders, n_fills,
                )
        except Exception:
            pass

        # ── 4. Sleep ──────────────────────────────────────────
        if mode == "replay":
            # Replay: small delay so you can read the output
            delay_sec = settings.replay_tick_delay_ms / 1000.0
            if delay_sec > 0:
                time.sleep(delay_sec)
        else:
            for _ in range(settings.poll_interval_sec * 2):
                if not RUNNING:
                    break
                time.sleep(0.5)

    log.info("Bot stopped after %d ticks", tick)

    # Final summary
    try:
        cash = service.db.cash_balance(settings.bankroll_usdc)
        notional = service.db.sum_open_notional()
        equity = cash + notional
        total_return = equity - settings.bankroll_usdc
        return_pct = (float(total_return) / float(settings.bankroll_usdc) * 100) if settings.bankroll_usdc > 0 else 0.0
        n_orders = service.db.count_rows("orders")
        n_fills = service.db.count_rows("fills")
        n_kills = service.db.count_rows("kill_events")
        log.info("=" * 50)
        log.info("  FINAL SUMMARY")
        log.info("=" * 50)
        log.info("  Bankroll:     $%.2f", float(settings.bankroll_usdc))
        log.info("  Cash:         $%.4f", float(cash))
        log.info("  Open:         $%.4f", float(notional))
        log.info("  Equity:       $%.4f", float(equity))
        log.info("  Return:       %+.2f%%", return_pct)
        log.info("  Orders:       %d", n_orders)
        log.info("  Fills:        %d", n_fills)
        log.info("  Risk blocks:  %d", n_kills)
        log.info("=" * 50)
        log.info("  Run: python watch.py --db %s --once", db_path)
        log.info("=" * 50)
        telegram.send_shutdown(tick, float(equity), return_pct)
    except Exception:
        pass

    service.db.close()
