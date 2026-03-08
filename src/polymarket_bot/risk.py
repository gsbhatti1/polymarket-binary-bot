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
        self._peak_equity: Decimal = Decimal("0")
        self._peak_date: str = ""

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

        # Drawdown circuit breaker: stop if equity drops >15% from today's high
        max_dd = getattr(self.settings, "max_drawdown_pct", Decimal("0.15"))
        if max_dd > 0:
            current_equity = state.cash_usdc + state.total_open_notional
            # Reset peak on new day
            if today_prefix != self._peak_date:
                self._peak_equity = current_equity
                self._peak_date = today_prefix
            elif current_equity > self._peak_equity:
                self._peak_equity = current_equity
            if self._peak_equity > 0:
                drawdown = (self._peak_equity - current_equity) / self._peak_equity
                if drawdown > max_dd:
                    return RiskDecision(False, f"drawdown_circuit_breaker:{drawdown:.1%}>{max_dd:.0%}")

        if requested_notional > self.settings.per_trade_cap_usdc:
            return RiskDecision(False, "per_trade_cap_exceeded")

        if state.market_open_notional + requested_notional > self.settings.max_market_notional_usdc:
            return RiskDecision(False, "market_notional_cap_exceeded")

        if state.total_open_notional + requested_notional > self.settings.max_total_notional_usdc:
            return RiskDecision(False, "portfolio_notional_cap_exceeded")

        if state.cash_usdc - requested_notional < Decimal("0"):
            return RiskDecision(False, "insufficient_cash")

        return RiskDecision(True, "ok")
