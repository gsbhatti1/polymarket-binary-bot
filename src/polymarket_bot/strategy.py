from __future__ import annotations

from decimal import Decimal, getcontext
from typing import Iterable

from .config import Settings
from .models import MarketState, SignalEvidence, SizingDecision

getcontext().prec = 28


def clamp_probability(p: Decimal) -> Decimal:
    eps = Decimal("0.0001")
    if p < eps:
        return eps
    if p > Decimal("0.9999"):
        return Decimal("0.9999")
    return p


class BayesianKellyStrategy:
    name = "bayes_kelly_binary"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def posterior_probability(self, prior: Decimal, evidence: Iterable[SignalEvidence]) -> Decimal:
        prior = clamp_probability(prior)
        log_odds = (prior / (Decimal("1") - prior)).ln()
        for item in evidence:
            signed_weight = item.weight if item.positive else -item.weight
            log_odds += signed_weight
        odds = log_odds.exp()
        posterior = odds / (Decimal("1") + odds)
        return clamp_probability(posterior)

    def kelly_yes_share(self, posterior: Decimal, ask_price: Decimal) -> Decimal:
        posterior = clamp_probability(posterior)
        ask_price = clamp_probability(ask_price)
        raw = (posterior - ask_price) / (Decimal("1") - ask_price)
        if raw < 0:
            return Decimal("0")
        capped = min(raw, self.settings.max_kelly_fraction)
        return capped * self.settings.fractional_kelly

    def decide(self, market: MarketState, bankroll_usdc: Decimal, current_position_qty: Decimal = Decimal("0")) -> SizingDecision:
        posterior = self.posterior_probability(market.prior_probability, market.evidence)
        ask = market.orderbook.best_ask
        bid = market.orderbook.best_bid
        net_edge = posterior - ask

        # ── EXIT: if we hold YES and edge has reversed, sell ──
        if current_position_qty > 0 and posterior < bid:
            return SizingDecision(
                posterior_probability=posterior,
                net_edge=posterior - bid,
                kelly_fraction=Decimal("0"),
                target_notional_usdc=current_position_qty * bid,  # sell all
                limit_price=bid,
                side="SELL_YES",
                reason="edge_reversed_sell",
            )

        if net_edge < self.settings.min_net_edge:
            return SizingDecision(
                posterior_probability=posterior,
                net_edge=net_edge,
                kelly_fraction=Decimal("0"),
                target_notional_usdc=Decimal("0"),
                limit_price=ask,
                side="BUY_YES",
                reason="edge_below_threshold",
            )

        kelly_fraction = self.kelly_yes_share(posterior, ask)
        target = bankroll_usdc * kelly_fraction
        if target > self.settings.per_trade_cap_usdc:
            target = self.settings.per_trade_cap_usdc

        if target < self.settings.min_order_notional_usdc:
            return SizingDecision(
                posterior_probability=posterior,
                net_edge=net_edge,
                kelly_fraction=kelly_fraction,
                target_notional_usdc=Decimal("0"),
                limit_price=ask,
                side="BUY_YES",
                reason="notional_below_minimum",
            )

        return SizingDecision(
            posterior_probability=posterior,
            net_edge=net_edge,
            kelly_fraction=kelly_fraction,
            target_notional_usdc=target,
            limit_price=ask,
            side="BUY_YES",
            reason="trade_yes",
        )
