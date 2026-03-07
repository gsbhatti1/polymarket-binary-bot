from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .config import Settings
from .db import Database
from .models import RiskState


@dataclass(frozen=True)
class RiskDecision:
    allowed: bool
    reason: str


class RiskEngine:
    def __init__(self, settings: Settings, db: Database) -> None:
        self.settings = settings
        self.db = db

    def snapshot(self, market_id: str, today_prefix: str) -> RiskState:
        cash = self.db.cash_balance(self.settings.bankroll_usdc)
        return RiskState(
            bankroll_usdc=self.settings.bankroll_usdc,
            cash_usdc=cash,
            total_open_notional=self.db.sum_open_notional(),
            market_open_notional=self.db.market_open_notional(market_id),
            realized_pnl_today=self.db.realized_pnl_today(today_prefix),
        )

    def pre_trade_check(self, market_id: str, requested_notional: Decimal, today_prefix: str) -> RiskDecision:
        state = self.snapshot(market_id, today_prefix)

        if requested_notional <= 0:
            return RiskDecision(False, "zero_or_negative_notional")

        if state.cash_usdc < self.settings.bankroll_floor_usdc:
            return RiskDecision(False, "bankroll_floor_breached")

        if state.realized_pnl_today <= -self.settings.max_daily_loss_usdc:
            return RiskDecision(False, "max_daily_loss_hit")

        if requested_notional > self.settings.per_trade_cap_usdc:
            return RiskDecision(False, "per_trade_cap_exceeded")

        if state.market_open_notional + requested_notional > self.settings.max_market_notional_usdc:
            return RiskDecision(False, "market_notional_cap_exceeded")

        if state.total_open_notional + requested_notional > self.settings.max_total_notional_usdc:
            return RiskDecision(False, "portfolio_notional_cap_exceeded")

        if state.cash_usdc - requested_notional < Decimal("0"):
            return RiskDecision(False, "insufficient_cash")

        return RiskDecision(True, "ok")
