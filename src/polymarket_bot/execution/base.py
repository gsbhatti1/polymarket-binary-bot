from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import OrderBookSnapshot, OrderRequest, FillResult


class ExchangeAdapter(ABC):
    mode: str

    @abstractmethod
    def get_orderbook(self, market_id: str) -> OrderBookSnapshot:
        raise NotImplementedError

    @abstractmethod
    def place_order(self, order: OrderRequest) -> FillResult:
        raise NotImplementedError
