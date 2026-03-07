from decimal import Decimal

from polymarket_bot.config import Settings
from polymarket_bot.execution.paper import PaperExchangeAdapter
from polymarket_bot.models import OrderRequest
from polymarket_bot.replay import ReplaySource


def test_paper_adapter_partial_or_full_fill():
    settings = Settings()
    adapter = PaperExchangeAdapter(ReplaySource("replay/sample_btc_book.jsonl"), settings)
    adapter.get_orderbook("BTC_UP")
    fill = adapter.place_order(OrderRequest(
        market_id="BTC_UP",
        side="BUY_YES",
        limit_price=Decimal("0.52"),
        quantity=Decimal("10"),
        strategy_name="t",
        client_order_id="x",
    ))
    assert fill.filled_qty == Decimal("10.00000000")
    assert fill.status == "filled"
