"""Interactive Brokers connector (Phase 2/3) via TWS ou IB Gateway.

NON IMPLEMENTE volontairement: a brancher avec la librairie `ib_insync`
(ou ib_async, son successeur maintenu) sur le port API de TWS/Gateway
(IBKR_HOST/IBKR_PORT/IBKR_CLIENT_ID dans .env). Commencer en compte papier
(port 7497), jamais directement sur le port reel 7496.

L'interface a respecter est atlas.execution.base.Broker.
"""

from __future__ import annotations

from atlas.execution.base import Broker, BrokerPosition, Order


class IBKRBroker:
    name = "ibkr"

    def __init__(self) -> None:
        raise NotImplementedError(
            "Connecteur IBKR a implementer (ib_insync/ib_async + TWS Gateway). "
            "Compte papier d'abord (port 7497)."
        )

    def submit_order(self, order: Order) -> Order: ...
    def cancel_order(self, broker_order_id: str) -> bool: ...
    def get_positions(self) -> list[BrokerPosition]: ...
    def get_cash(self) -> float: ...
    def get_equity(self) -> float: ...
