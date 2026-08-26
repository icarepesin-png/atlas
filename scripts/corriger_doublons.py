# -*- coding: utf-8 -*-
"""Ramene a la taille voulue les positions achetees deux fois.

Le 2026-08-08, deux rattrapages simultanes ont execute le meme signal chacun
de leur cote (voir atlas/pipelines/lock.py). GEN et FTNT se sont retrouves au
DOUBLE de la taille prevue, soit ~10% du portefeuille pour un plafond de 5%.

Ce script detecte les achats en double (meme ticker, meme horodatage a la
seconde) et revend l'excedent au dernier cours connu. La vente est enregistree
avec une raison explicite pour qu'elle ne soit pas confondue avec une decision
de strategie dans les analyses de performance.

  python scripts/corriger_doublons.py              # simulation (par defaut)
  python scripts/corriger_doublons.py --appliquer  # execute reellement
"""

from __future__ import annotations

import sys

from sqlalchemy import text

from atlas.data.fx import currency_of, get_usd_rates
from atlas.data.store import init_db, load_ohlcv
from atlas.execution.base import Order, OrderSide, OrderType
from atlas.execution.paper import PaperBroker

RAISON = "correction: doublon d'execution du 2026-08-08"


def doublons(engine) -> list[dict]:
    """Achats identiques le meme jour: meme ticker, meme quantite, meme prix.

    Les horodatages different de quelques microsecondes (deux processus
    concurrents), on ne peut donc pas grouper dessus. En revanche le systeme
    n'achete jamais deux fois le meme ticker dans la meme journee: meme
    quantite ET meme prix d'execution ne peut etre qu'un doublon.
    """
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT ticker, MIN(filled_at), COUNT(*) n, SUM(qty) qty_totale,"
            " MIN(qty) qty_unitaire FROM orders"
            " WHERE side='buy' AND status='filled'"
            " GROUP BY ticker, substr(filled_at, 1, 10), qty, filled_price"
            " HAVING n > 1")).fetchall()
    out = []
    for t, quand, n, qty_totale, qty_unitaire in rows:
        with engine.connect() as conn:
            detenu = conn.execute(text(
                "SELECT qty FROM positions WHERE ticker=:t"), {"t": t}).fetchone()
        if not detenu:
            continue  # position deja fermee entre-temps: rien a corriger
        detenu = float(detenu[0])
        excedent = min(detenu - qty_unitaire, qty_totale - qty_unitaire)
        if excedent > 0:
            out.append({"ticker": t, "quand": quand, "n": n,
                        "detenu": detenu, "garder": qty_unitaire,
                        "vendre": excedent})
    return out


def main() -> None:
    appliquer = "--appliquer" in sys.argv
    engine = init_db()
    broker = PaperBroker(engine=engine)
    rates = get_usd_rates()

    cas = doublons(engine)
    if not cas:
        print("aucun doublon d'execution a corriger")
        return

    print(f"{len(cas)} position(s) achetee(s) en double:\n")
    for c in cas:
        df = load_ohlcv(c["ticker"])
        if df.empty:
            print(f"  {c['ticker']}: aucun cours, ignore")
            continue
        px = float(df["close"].iloc[-1])
        cur = currency_of(c["ticker"])
        fx = rates.get(cur, 1.0)
        print(f"  {c['ticker']:8} {c['n']} achats le {str(c['quand'])[:19]}")
        print(f"           detenu {c['detenu']:.0f} -> garder {c['garder']:.0f}"
              f" (vendre {c['vendre']:.0f} @ {px:.2f} {cur}"
              f" = {c['vendre'] * px * fx:,.0f} USD)")
        if not appliquer:
            continue
        ordre = broker.submit_order(
            Order(c["ticker"], OrderSide.SELL, c["vendre"], OrderType.MARKET),
            reference_price=px, fx_rate=fx, currency=cur, reason=RAISON)
        print(f"           -> {ordre.status.value} @ {ordre.filled_price}")

    if not appliquer:
        print("\nSIMULATION. Relancer avec --appliquer pour executer.")


if __name__ == "__main__":
    main()
