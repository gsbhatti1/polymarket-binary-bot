from decimal import Decimal

from polymarket_bot.config import Settings
from polymarket_bot.models import BookLevel, OrderBookSnapshot, MarketState, SignalEvidence
from polymarket_bot.strategy import BayesianKellyStrategy


def make_market() -> MarketState:
    book = OrderBookSnapshot(
        ts="2026-03-07T15:00:00Z",
        market_id="BTC_UP",
        best_bid=Decimal("0.48"),
        best_ask=Decimal("0.52"),
        bids=[BookLevel(Decimal("0.48"), Decimal("100"))],
        asks=[BookLevel(Decimal("0.52"), Decimal("100"))],
    )
    return MarketState(
        market_id="BTC_UP",
        prior_probability=Decimal("0.55"),
        orderbook=book,
        evidence=[SignalEvidence("flow", Decimal("0.15"), True)],
    )


def test_posterior_increases_with_positive_evidence():
    settings = Settings()
    strategy = BayesianKellyStrategy(settings)
    market = make_market()
    posterior = strategy.posterior_probability(market.prior_probability, market.evidence)
    assert posterior > market.prior_probability


def test_decision_allocates_notional_on_edge():
    settings = Settings()
    strategy = BayesianKellyStrategy(settings)
    decision = strategy.decide(make_market(), bankroll_usdc=Decimal("100"))
    assert decision.target_notional_usdc > 0
    assert decision.reason == "trade_yes"
