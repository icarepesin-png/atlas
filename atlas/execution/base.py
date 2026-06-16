"""Broker abstraction. Phase 1: PaperBroker. Phase 2/3: Alpaca, IBKR.

SAFETY: any non-paper broker refuses to start unless
settings.live_trading_enabled (LIVE_TRADING_ACK env var) is set. See
docs/GO_LIVE.md for the demo -> real procedure.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Protocol, runtime_checkable


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"


class OrderStatus(str, Enum):
    PENDING = "pending"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


@dataclass
class Order:
    ticker: str
    side: OrderSide
    qty: float
    order_type: OrderType = OrderType.LIMIT
    limit_price: float | None = None
    status: OrderStatus = OrderStatus.PENDING
    filled_price: float | None = None
    broker_order_id: str | None = None
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass
class BrokerPosition:
    ticker: str
    qty: float
    avg_price: float          # en devise de cotation
    currency: str = "USD"
    fx_entry: float = 1.0     # taux devise/USD au moment de l'achat


@runtime_checkable
class Broker(Protocol):
    name: str

    def submit_order(self, order: Order) -> Order: ...
    def cancel_order(self, broker_order_id: str) -> bool: ...
    def get_positions(self) -> list[BrokerPosition]: ...
    def get_cash(self) -> float: ...
    def get_equity(self) -> float: ...


def get_broker(name: str | None = None) -> Broker:
    from atlas.config import get_config, get_settings

    name = name or get_config().execution.get("broker", "paper")
    if name == "paper":
        from atlas.execution.paper import PaperBroker
        return PaperBroker()
    settings = get_settings()
    # Le compte demo Alpaca (ALPACA_PAPER=true) reste de l'argent fictif:
    # autorise sans LIVE_TRADING_ACK. Tout broker en argent reel exige l'ack.
    if name == "alpaca" and settings.alpaca_paper:
        from atlas.execution.alpaca import AlpacaBroker
        return AlpacaBroker()
    if not settings.live_trading_enabled:
        raise PermissionError(
            f"broker '{name}' refuse: LIVE_TRADING_ACK non confirme dans .env. "
            "Suivre docs/GO_LIVE.md avant toute execution non-paper."
        )
    if name == "alpaca":
        from atlas.execution.alpaca import AlpacaBroker
        return AlpacaBroker()
    if name == "ibkr":
        from atlas.execution.ibkr import IBKRBroker
        return IBKRBroker()
    raise ValueError(f"broker inconnu: {name}")
