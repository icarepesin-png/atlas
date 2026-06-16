"""AlpacaBroker tests with an injected fake client (no network, no keys)."""

from types import SimpleNamespace

import pytest

from atlas.execution.alpaca import AlpacaBroker
from atlas.execution.base import Order, OrderSide, OrderStatus, OrderType


class FakeClient:
    def __init__(self, status="accepted", fail=False):
        self.status = status
        self.fail = fail
        self.last_request = None
        self.cancelled = []

    def submit_order(self, order_data):
        if self.fail:
            raise RuntimeError("insufficient buying power")
        self.last_request = order_data
        return SimpleNamespace(id="abc-123", status=self.status,
                               filled_avg_price=101.5, filled_qty=10)

    def cancel_order_by_id(self, order_id):
        self.cancelled.append(order_id)

    def get_all_positions(self):
        return [SimpleNamespace(symbol="MSFT", qty="10",
                                avg_entry_price="400.5")]

    def get_account(self):
        return SimpleNamespace(cash="25000.0", equity="31000.0")


def _broker(**kw) -> AlpacaBroker:
    return AlpacaBroker(client=FakeClient(**kw))


def test_limit_order_mapping():
    broker = _broker(status="filled")
    order = broker.submit_order(Order("MSFT", OrderSide.BUY, 10,
                                      OrderType.LIMIT, limit_price=101.567))
    assert order.status == OrderStatus.FILLED
    assert order.broker_order_id == "abc-123"
    assert order.filled_price == pytest.approx(101.5)
    req = broker.client.last_request
    assert req.symbol == "MSFT"
    assert float(req.limit_price) == pytest.approx(101.57)  # arrondi au cent


def test_market_order_pending_status():
    broker = _broker(status="accepted")
    order = broker.submit_order(Order("MSFT", OrderSide.SELL, 5,
                                      OrderType.MARKET))
    assert order.status == OrderStatus.PENDING  # accepted = pas terminal


def test_rejection_on_exception():
    broker = _broker(fail=True)
    order = broker.submit_order(Order("MSFT", OrderSide.BUY, 10_000,
                                      OrderType.MARKET))
    assert order.status == OrderStatus.REJECTED
    assert order.broker_order_id is None


def test_positions_and_account():
    broker = _broker()
    positions = broker.get_positions()
    assert positions[0].ticker == "MSFT"
    assert positions[0].qty == 10.0
    assert broker.get_cash() == 25_000.0
    assert broker.get_equity() == 31_000.0


def test_cancel():
    broker = _broker()
    assert broker.cancel_order("abc-123") is True
    assert broker.client.cancelled == ["abc-123"]
