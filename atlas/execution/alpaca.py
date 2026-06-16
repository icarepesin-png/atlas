"""Alpaca broker connector (Phase 2 du GO_LIVE: compte demo paper).

SDK officiel alpaca-py (verifie sur la version 0.43): TradingClient,
MarketOrderRequest/LimitOrderRequest, get_account, get_all_positions.

Garde-fous:
- cles ALPACA_API_KEY / ALPACA_SECRET_KEY requises dans .env;
- en compte PAPER (ALPACA_PAPER=true), utilisable sans LIVE_TRADING_ACK;
- en compte REEL, execution/base.get_broker exige LIVE_TRADING_ACK.

Limites connues: actions US uniquement (les tickers europeens du scan ne
sont pas negociables chez Alpaca et seront rejetes par le broker).
"""

from __future__ import annotations

import logging

from atlas.config import get_settings
from atlas.execution.base import (BrokerPosition, Order, OrderSide,
                                  OrderStatus, OrderType)

log = logging.getLogger(__name__)

# Statuts Alpaca -> statuts ATLAS (tout le reste = en attente)
_TERMINAL = {
    "filled": OrderStatus.FILLED,
    "canceled": OrderStatus.CANCELLED,
    "expired": OrderStatus.CANCELLED,
    "rejected": OrderStatus.REJECTED,
}


class AlpacaBroker:
    name = "alpaca"

    def __init__(self, client=None) -> None:
        settings = get_settings()
        self.paper = settings.alpaca_paper
        if client is not None:  # injection pour les tests
            self.client = client
            return
        if not settings.alpaca_api_key or not settings.alpaca_secret_key:
            raise PermissionError(
                "Cles Alpaca absentes de .env (ALPACA_API_KEY / "
                "ALPACA_SECRET_KEY). Creer un compte sur alpaca.markets, "
                "generer les cles PAPER, puis relancer.")
        from alpaca.trading.client import TradingClient
        self.client = TradingClient(settings.alpaca_api_key,
                                    settings.alpaca_secret_key,
                                    paper=self.paper)
        log.info("alpaca connecte (paper=%s)", self.paper)

    def submit_order(self, order: Order) -> Order:
        from alpaca.trading.enums import OrderSide as AlpacaSide
        from alpaca.trading.enums import TimeInForce
        from alpaca.trading.requests import (LimitOrderRequest,
                                             MarketOrderRequest)

        side = (AlpacaSide.BUY if order.side == OrderSide.BUY
                else AlpacaSide.SELL)
        if order.order_type == OrderType.LIMIT and order.limit_price:
            request = LimitOrderRequest(
                symbol=order.ticker, qty=order.qty, side=side,
                time_in_force=TimeInForce.DAY,
                limit_price=round(float(order.limit_price), 2))
        else:
            request = MarketOrderRequest(
                symbol=order.ticker, qty=order.qty, side=side,
                time_in_force=TimeInForce.DAY)
        try:
            placed = self.client.submit_order(order_data=request)
        except Exception as exc:
            order.status = OrderStatus.REJECTED
            log.warning("alpaca reject %s %s: %s",
                        order.side.value, order.ticker, exc)
            return order
        order.broker_order_id = str(placed.id)
        status = str(getattr(placed.status, "value", placed.status))
        order.status = _TERMINAL.get(status, OrderStatus.PENDING)
        if placed.filled_avg_price is not None:
            order.filled_price = float(placed.filled_avg_price)
        log.info("alpaca %s %s x%s -> %s", order.side.value, order.ticker,
                 order.qty, status)
        return order

    def cancel_order(self, broker_order_id: str) -> bool:
        try:
            self.client.cancel_order_by_id(broker_order_id)
            return True
        except Exception as exc:
            log.warning("alpaca cancel %s echoue: %s", broker_order_id, exc)
            return False

    def get_positions(self) -> list[BrokerPosition]:
        return [
            BrokerPosition(p.symbol, float(p.qty), float(p.avg_entry_price))
            for p in self.client.get_all_positions()
        ]

    def get_cash(self) -> float:
        return float(self.client.get_account().cash)

    def get_equity(self) -> float:
        return float(self.client.get_account().equity)

    def is_market_open(self) -> bool:
        try:
            return bool(self.client.get_clock().is_open)
        except Exception:
            return False
