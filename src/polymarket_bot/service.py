from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from uuid import uuid4

from .config import Settings
from .db import Database
from .execution.base import ExchangeAdapter
from .models import MarketState, OrderRequest, SignalEvidence
from .risk import RiskEngine
from .strategy import BayesianKellyStrategy


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def day_prefix(ts: str) -> str:
    return ts[:10]


@dataclass
class RunResult:
    market_id: str
    mode: str
    decision_reason: str
    order_id: str | None
    fill_status: str | None
    filled_qty: Decimal
    spent_usdc: Decimal


class BotService:
    def __init__(
        self,
        *,
        settings: Settings,
        db: Database,
        adapter: ExchangeAdapter,
        strategy: BayesianKellyStrategy,
        risk: RiskEngine,
    ) -> None:
        self.settings = settings
        self.db = db
        self.adapter = adapter
        self.strategy = strategy
        self.risk = risk

    def run_once(self, market_id: str, prior_probability: Decimal, evidence: list[SignalEvidence]) -> RunResult:
        ts = now_utc()
        self.db.log_run(ts=ts, mode=self.adapter.mode, market_id=market_id)

        book = self.adapter.get_orderbook(market_id)
        market = MarketState(
            market_id=market_id,
            prior_probability=prior_probability,
            orderbook=book,
            evidence=evidence,
        )

        bankroll_for_sizing = self.db.cash_balance(self.settings.bankroll_usdc)

        # Check if we already hold a position in this market
        current_pos = self.db.get_position(market_id)
        current_qty = Decimal(current_pos["yes_qty"]) if current_pos else Decimal("0")

        sizing = self.strategy.decide(market, bankroll_usdc=bankroll_for_sizing, current_position_qty=current_qty)

        if sizing.target_notional_usdc <= 0:
            return RunResult(market_id, self.adapter.mode, sizing.reason, None, None, Decimal("0"), Decimal("0"))

        today = day_prefix(ts)

        # Skip risk check for exits — selling reduces exposure
        if sizing.side != "SELL_YES":
            pre = self.risk.pre_trade_check(market_id, sizing.target_notional_usdc, today)
            if not pre.allowed:
                self.db.add_kill_event(ts=ts, kill_name="pre_trade_risk_block", market_id=market_id, reason=pre.reason)
                return RunResult(market_id, self.adapter.mode, pre.reason, None, None, Decimal("0"), Decimal("0"))

        if sizing.side == "SELL_YES":
            # For sells, quantity = shares to sell (not notional/price)
            quantity = current_qty  # sell entire position
        else:
            quantity = (sizing.target_notional_usdc / sizing.limit_price).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)

        order = OrderRequest(
            market_id=market_id,
            side=sizing.side,
            limit_price=sizing.limit_price,
            quantity=quantity,
            strategy_name=self.strategy.name,
            client_order_id=f"cli-{uuid4().hex[:16]}",
        )

        fill = self.adapter.place_order(order)
        self.db.insert_order(
            order_id=fill.order_id,
            ts=fill.ts,
            mode=self.adapter.mode,
            market_id=market_id,
            side=order.side,
            quantity=order.quantity,
            limit_price=order.limit_price,
            strategy_name=order.strategy_name,
            client_order_id=order.client_order_id,
            status=fill.status,
            note=sizing.reason,
        )
        self.db.insert_fill(
            order_id=fill.order_id,
            ts=fill.ts,
            venue=fill.venue,
            market_id=market_id,
            side=fill.side,
            requested_qty=fill.requested_qty,
            filled_qty=fill.filled_qty,
            avg_price=fill.avg_price,
            fee_paid=fill.fee_paid,
            status=fill.status,
            note=fill.note,
        )

        if fill.filled_qty > 0:
            if sizing.side == "SELL_YES":
                # SELL path: credit cash, reduce position
                proceeds = (fill.filled_qty * fill.avg_price) - fill.fee_paid
                self.db.add_cash_entry(fill.ts, "sell_yes", proceeds, market_id=market_id, note=fill.status)
                # Reduce position (negative qty)
                self.db.upsert_yes_position(fill.ts, market_id, -fill.filled_qty, fill.avg_price)
                # Record realized PnL
                if current_pos:
                    avg_cost = Decimal(current_pos["avg_yes_cost"])
                    pnl = (fill.avg_price - avg_cost) * fill.filled_qty
                    self.db.add_realized_pnl(fill.ts, market_id, pnl, note="sell_exit")
                return RunResult(market_id, self.adapter.mode, sizing.reason, fill.order_id, fill.status, fill.filled_qty, proceeds)
            else:
                # BUY path (original)
                spent = (fill.filled_qty * fill.avg_price) + fill.fee_paid
                self.db.add_cash_entry(fill.ts, "buy_yes", -spent, market_id=market_id, note=fill.status)
                self.db.upsert_yes_position(fill.ts, market_id, fill.filled_qty, fill.avg_price)
                return RunResult(market_id, self.adapter.mode, sizing.reason, fill.order_id, fill.status, fill.filled_qty, spent)

        return RunResult(market_id, self.adapter.mode, sizing.reason, fill.order_id, fill.status, Decimal("0"), Decimal("0"))
