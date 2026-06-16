"""Reconciliation quotidienne broker / base locale (critere GO_LIVE phase 2).

Run:  python -m atlas.pipelines.reconcile [--broker alpaca]

Compare les positions du broker avec la table positions locale et signale
tout ecart (ticker manquant, quantite differente). Zero ecart pendant
plusieurs semaines est une condition de passage en reel.
"""

from __future__ import annotations

import argparse
import logging

from atlas.data.store import read_table
from atlas.execution.base import get_broker

log = logging.getLogger(__name__)


def reconcile(broker_name: str | None = None) -> dict:
    broker = get_broker(broker_name)
    broker_pos = {p.ticker: float(p.qty) for p in broker.get_positions()}
    local = read_table("positions")
    local_pos = (dict(zip(local["ticker"], local["qty"].astype(float)))
                 if not local.empty else {})

    mismatches = []
    for ticker in sorted(set(broker_pos) | set(local_pos)):
        b, l = broker_pos.get(ticker), local_pos.get(ticker)
        if b is None:
            mismatches.append(f"{ticker}: en base locale ({l}) mais ABSENT chez le broker")
        elif l is None:
            mismatches.append(f"{ticker}: chez le broker ({b}) mais ABSENT en base locale")
        elif abs(b - l) > 1e-6:
            mismatches.append(f"{ticker}: quantite broker {b} != locale {l}")

    result = {
        "broker": broker.name,
        "broker_positions": len(broker_pos),
        "local_positions": len(local_pos),
        "mismatches": mismatches,
        "ok": not mismatches,
    }
    if mismatches:
        log.warning("RECONCILIATION EN ECART:\n%s", "\n".join(mismatches))
        try:
            from atlas.monitoring.notify import send
            send("ALERTE ATLAS - ecart de reconciliation broker/base:\n"
                 + "\n".join(mismatches[:10]))
        except Exception:
            pass
    else:
        log.info("reconciliation OK: %d positions identiques", len(broker_pos))
    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--broker", default=None, help="paper | alpaca")
    args = parser.parse_args()
    print(reconcile(args.broker))
