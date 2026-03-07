from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal
from dotenv import load_dotenv


load_dotenv()


def _d(name: str, default: str) -> Decimal:
    return Decimal(os.getenv(name, default))


@dataclass(frozen=True)
class Settings:
    bankroll_usdc: Decimal = _d("PM_BANKROLL_USDC", "100.0")
    per_trade_cap_usdc: Decimal = _d("PM_PER_TRADE_CAP_USDC", "25.0")
    max_market_notional_usdc: Decimal = _d("PM_MAX_MARKET_NOTIONAL_USDC", "100.0")
    max_total_notional_usdc: Decimal = _d("PM_MAX_TOTAL_NOTIONAL_USDC", "250.0")
    max_daily_loss_usdc: Decimal = _d("PM_MAX_DAILY_LOSS_USDC", "25.0")
    bankroll_floor_usdc: Decimal = _d("PM_BANKROLL_FLOOR_USDC", "25.0")
    fractional_kelly: Decimal = _d("PM_FRACTIONAL_KELLY", "0.25")
    max_kelly_fraction: Decimal = _d("PM_MAX_KELLY_FRACTION", "0.25")
    min_net_edge: Decimal = _d("PM_MIN_NET_EDGE", "0.02")
    min_order_notional_usdc: Decimal = _d("PM_MIN_ORDER_NOTIONAL_USDC", "1.0")
    paper_fee_bps: Decimal = _d("PM_PAPER_FEE_BPS", "0")
    paper_latency_ms: int = int(os.getenv("PM_PAPER_LATENCY_MS", "0"))
    default_market_price: Decimal = _d("PM_DEFAULT_MARKET_PRICE", "0.52")
    replay_path: str = os.getenv("PM_REPLAY_PATH", "replay/sample_btc_book.jsonl")

    # Loop control
    poll_interval_sec: int = int(os.getenv("PM_POLL_INTERVAL_SEC", "30"))
    resolve_check_every: int = int(os.getenv("PM_RESOLVE_CHECK_EVERY", "10"))

    # Exit management
    stop_loss_pct: Decimal = _d("PM_STOP_LOSS_PCT", "0.30")
    take_profit_pct: Decimal = _d("PM_TAKE_PROFIT_PCT", "0.50")

    # Market discovery
    min_market_volume: float = float(os.getenv("PM_MIN_MARKET_VOLUME", "10000"))
