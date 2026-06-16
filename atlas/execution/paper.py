"""Paper trading broker: fills at provided reference price +/- slippage,
state persisted in the SQL store (orders / positions / trades tables)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import text

from atlas.config import get_config
from atlas.data.store import init_db
from atlas.execution.base import (Broker, BrokerPosition, Order, OrderSide,
                                  OrderStatus)

log = logging.getLogger(__name__)


class PaperBroker:
    name = "paper"

    def __init__(self, initial_cash: float | None = None,
                 slippage_bps: float | None = None, engine=None) -> None:
        bt = get_config().backtest
        self.engine = engine or init_db()
        self.slippage = (slippage_bps if slippage_bps is not None
                         else float(bt.get("slippage_bps", 5))) / 10_000
        with self.engine.begin() as conn:
            conn.execute(text(
                "CREATE TABLE IF NOT EXISTS paper_account "
                "(id INTEGER PRIMARY KEY CHECK (id = 1), cash REAL)"
            ))
            row = conn.execute(text("SELECT cash FROM paper_account WHERE id=1")).fetchone()
            if row is None:
                cash = initial_cash or float(bt.get("initial_capital", 100_000))
                conn.execute(text("INSERT INTO paper_account (id, cash) VALUES (1, :c)"),
                             {"c": cash})

    # -- account ---------------------------------------------------------------

    def get_cash(self) -> float:
        with self.engine.connect() as conn:
            return float(conn.execute(
                text("SELECT cash FROM paper_account WHERE id=1")).scalar() or 0.0)

    def _set_cash(self, cash: float) -> None:
        with self.engine.begin() as conn:
            conn.execute(text("UPDATE paper_account SET cash=:c WHERE id=1"), {"c": cash})

    def get_positions(self) -> list[BrokerPosition]:
        with self.engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT ticker, qty, avg_price, currency, fx_entry"
                " FROM positions")).fetchall()
        return [BrokerPosition(r[0], float(r[1]), float(r[2]),
                               r[3] or "USD", float(r[4] or 1.0)) for r in rows]

    def get_equity(self, marks_usd: dict[str, float] | None = None) -> float:
        """Cash + positions valued at USD marks (entry value fallback)."""
        equity = self.get_cash()
        for pos in self.get_positions():
            px_usd = (marks_usd or {}).get(pos.ticker,
                                           pos.avg_price * pos.fx_entry)
            equity += pos.qty * px_usd
        return equity

    # -- orders ------------------------------------------------------------------

    def submit_order(self, order: Order, reference_price: float | None = None,
                     fx_rate: float = 1.0, currency: str = "USD") -> Order:
        """Immediate simulated fill at reference (or limit) price + slippage.

        Prices stay in the LISTING currency (stops compare to local closes);
        cash impact, equity and realized PnL are converted to USD via fx_rate.
        """
        px = reference_price or order.limit_price
        if px is None or px <= 0:
            order.status = OrderStatus.REJECTED
            log.warning("paper reject %s %s: pas de prix", order.side.value, order.ticker)
            return order
        slip = px * self.slippage
        fill = px + slip if order.side == OrderSide.BUY else px - slip
        cost = fill * order.qty * fx_rate  # impact cash en USD
        cash = self.get_cash()

        if order.side == OrderSide.BUY and cost > cash:
            order.status = OrderStatus.REJECTED
            log.warning("paper reject BUY %s: cash insuffisant (%.0f > %.0f)",
                        order.ticker, cost, cash)
            return order

        now = datetime.now(timezone.utc).isoformat()
        # IMPORTANT: tout (positions, trades, cash, ordre) dans UNE transaction.
        # Ouvrir une 2e connexion pendant qu'une transaction d'ecriture est
        # ouverte bloque SQLite ("database is locked").
        with self.engine.begin() as conn:
            def set_cash(value: float) -> None:
                conn.execute(text("UPDATE paper_account SET cash=:c WHERE id=1"),
                             {"c": value})

            row = conn.execute(text(
                "SELECT qty, avg_price, opened_at, fx_entry FROM positions"
                " WHERE ticker=:t"), {"t": order.ticker}).fetchone()
            if order.side == OrderSide.BUY:
                if row:
                    old_qty, old_avg = float(row[0]), float(row[1])
                    old_fx = float(row[3] or 1.0)
                    new_qty = old_qty + order.qty
                    new_avg = (old_qty * old_avg + fill * order.qty) / new_qty
                    new_fx = (old_qty * old_fx + order.qty * fx_rate) / new_qty
                    conn.execute(text(
                        "UPDATE positions SET qty=:q, avg_price=:p, fx_entry=:f"
                        " WHERE ticker=:t"),
                        {"q": new_qty, "p": new_avg, "f": new_fx,
                         "t": order.ticker})
                else:
                    conn.execute(text(
                        "INSERT INTO positions (ticker, qty, avg_price,"
                        " opened_at, currency, fx_entry)"
                        " VALUES (:t, :q, :p, :o, :c, :f)"),
                        {"t": order.ticker, "q": order.qty, "p": fill,
                         "o": now, "c": currency, "f": fx_rate})
                set_cash(cash - cost)
            else:  # SELL
                held = float(row[0]) if row else 0.0
                if order.qty > held + 1e-9:
                    order.status = OrderStatus.REJECTED
                    log.warning("paper reject SELL %s: qty %.2f > detenu %.2f",
                                order.ticker, order.qty, held)
                    return order
                remaining = held - order.qty
                avg = float(row[1])
                fx_entry = float(row[3] or 1.0)
                # PnL en USD, effet de change inclus
                pnl = (fill * fx_rate - avg * fx_entry) * order.qty
                if remaining <= 1e-9:
                    conn.execute(text("DELETE FROM positions WHERE ticker=:t"),
                                 {"t": order.ticker})
                else:
                    conn.execute(text("UPDATE positions SET qty=:q WHERE ticker=:t"),
                                 {"q": remaining, "t": order.ticker})
                conn.execute(text(
                    "INSERT INTO trades (ticker, side, qty, entry_price, exit_price,"
                    " opened_at, closed_at, pnl, exit_reason)"
                    " VALUES (:t, 'long', :q, :e, :x, :o, :c, :p, :r)"),
                    {"t": order.ticker, "q": order.qty, "e": avg, "x": fill,
                     "o": row[2] if row else None, "c": now, "p": pnl,
                     "r": "signal"})
                set_cash(cash + fill * order.qty * fx_rate)

            order.status = OrderStatus.FILLED
            order.filled_price = round(fill, 4)
            conn.execute(text(
                "INSERT INTO orders (created_at, ticker, side, qty, order_type,"
                " limit_price, status, broker, filled_price, filled_at)"
                " VALUES (:c, :t, :s, :q, :ot, :lp, :st, 'paper', :fp, :fa)"),
                {"c": order.created_at, "t": order.ticker, "s": order.side.value,
                 "q": order.qty, "ot": order.order_type.value,
                 "lp": order.limit_price, "st": order.status.value,
                 "fp": order.filled_price, "fa": now})
        log.info("paper fill %s %s x%.0f @ %.2f", order.side.value,
                 order.ticker, order.qty, fill)
        return order

    def cancel_order(self, broker_order_id: str) -> bool:
        return False  # fills are immediate in paper mode
