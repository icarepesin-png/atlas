"""Regression tests for PaperBroker: full buy/sell cycle in one process.

Uses an isolated in-memory SQLite engine. The historical bug: submit_order
opened a second connection (via _set_cash) inside an open write transaction,
deadlocking SQLite ("database is locked").
"""

import pytest
from sqlalchemy import create_engine

from atlas.data.store import init_db
from atlas.execution.base import Order, OrderSide, OrderStatus, OrderType
from atlas.execution.paper import PaperBroker


@pytest.fixture
def broker() -> PaperBroker:
    engine = create_engine("sqlite://")  # in-memory, isolated
    init_db(engine)
    return PaperBroker(initial_cash=100_000, slippage_bps=0, engine=engine)


def test_buy_then_sell_cycle(broker):
    buy = broker.submit_order(Order("TEST", OrderSide.BUY, 100), reference_price=50.0)
    assert buy.status == OrderStatus.FILLED
    assert broker.get_cash() == pytest.approx(95_000)
    positions = broker.get_positions()
    assert len(positions) == 1
    assert positions[0].qty == 100

    sell = broker.submit_order(Order("TEST", OrderSide.SELL, 100, OrderType.MARKET),
                               reference_price=55.0)
    assert sell.status == OrderStatus.FILLED
    assert broker.get_cash() == pytest.approx(100_500)  # +100 * (55-50)
    assert broker.get_positions() == []


def test_buy_rejected_when_insufficient_cash(broker):
    order = broker.submit_order(Order("TEST", OrderSide.BUY, 10_000),
                                reference_price=50.0)
    assert order.status == OrderStatus.REJECTED
    assert broker.get_cash() == pytest.approx(100_000)


def test_sell_rejected_when_not_held(broker):
    order = broker.submit_order(Order("NOPE", OrderSide.SELL, 10),
                                reference_price=50.0)
    assert order.status == OrderStatus.REJECTED


def test_partial_sell_keeps_remainder(broker):
    broker.submit_order(Order("TEST", OrderSide.BUY, 100), reference_price=50.0)
    broker.submit_order(Order("TEST", OrderSide.SELL, 40), reference_price=50.0)
    positions = broker.get_positions()
    assert len(positions) == 1
    assert positions[0].qty == pytest.approx(60)