# -*- coding: utf-8 -*-
"""Cloture la campagne de test en cours et en ouvre une nouvelle.

POURQUOI PAS UN SIMPLE RESET: ce projet s'interdit d'effacer le paper trading
depuis le jour 0, et la regle est bonne - remettre les compteurs a zero quand
le resultat deplait, c'est se mentir. Ici la performance n'est pas en cause:
c'est la STRATEGIE qui change (audit du 2026-08-26). Melanger dans les memes
statistiques des trades pris avec deux scores differents les rend illisibles,
et garder un portefeuille choisi par un score invalide fausserait le nouveau
test des le premier jour.

D'ou ce mecanisme: rien n'est efface. Les trades, ordres et equity de la
campagne close gardent leur numero et restent consultables. On solde les
positions au dernier cours connu, on fige le bilan, et la nouvelle campagne
repart du capital initial.

  python scripts/nouvelle_campagne.py "nom"              # simulation
  python scripts/nouvelle_campagne.py "nom" --appliquer  # execute
"""

from __future__ import annotations

import shutil
import sys
from datetime import date, datetime, timezone

from sqlalchemy import text

from atlas.config import PROJECT_ROOT, get_config
from atlas.data.fx import currency_of, get_usd_rates
from atlas.data.store import campagne_courante, init_db, load_ohlcv
from atlas.execution.base import Order, OrderSide, OrderType
from atlas.execution.paper import PaperBroker

RAISON = "fin de campagne"


def bilan(engine, camp: int) -> dict:
    with engine.connect() as conn:
        n, pnl = conn.execute(text(
            "SELECT COUNT(*), COALESCE(SUM(pnl), 0) FROM trades"
            " WHERE COALESCE(campagne, 1) = :c"), {"c": camp}).fetchone()
        gagnants = conn.execute(text(
            "SELECT COUNT(*) FROM trades WHERE pnl > 0"
            " AND COALESCE(campagne, 1) = :c"), {"c": camp}).scalar()
        jours = conn.execute(text(
            "SELECT COUNT(*), MIN(date), MAX(date) FROM paper_equity"
            " WHERE COALESCE(campagne, 1) = :c"), {"c": camp}).fetchone()
    return {"trades": n, "pnl": float(pnl), "gagnants": gagnants,
            "seances": jours[0], "debut": jours[1], "fin": jours[2]}


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    appliquer = "--appliquer" in sys.argv
    nom = args[0] if args else f"campagne du {date.today()}"

    engine = init_db()
    broker = PaperBroker(engine=engine)
    camp = campagne_courante(engine)
    capital = float(get_config().backtest.get("initial_capital", 100_000))
    rates = get_usd_rates()

    with engine.connect() as conn:
        positions = conn.execute(text(
            "SELECT ticker, qty, avg_price, fx_entry FROM positions")).fetchall()
    b = bilan(engine, camp)

    print(f"=== CAMPAGNE {camp} en cours ===")
    print(f"  {b['seances']} seances ({b['debut']} -> {b['fin']})")
    print(f"  {b['trades']} trades clotures, {b['gagnants']} gagnants"
          + (f" ({100*b['gagnants']/b['trades']:.0f}%)" if b["trades"] else ""))
    print(f"  PnL realise: {b['pnl']:+,.2f} USD")
    print(f"  {len(positions)} position(s) a solder\n")

    solde = 0.0
    for ticker, qty, avg, fxe in positions:
        df = load_ohlcv(ticker)
        if df.empty:
            print(f"  {ticker:8} AUCUN COURS: a traiter a la main")
            continue
        px = float(df["close"].iloc[-1])
        cur = currency_of(ticker)
        fx = rates.get(cur, 1.0)
        pnl = (px * fx - avg * (fxe or 1.0)) * qty
        solde += pnl
        print(f"  {ticker:8} x{qty:>6.0f} @ {px:9.2f} {cur:4} -> {pnl:+9,.0f} USD")
        if appliquer:
            broker.submit_order(
                Order(ticker, OrderSide.SELL, float(qty), OrderType.MARKET),
                reference_price=px, fx_rate=fx, currency=cur, reason=RAISON)

    equity_finale = capital + b["pnl"] + solde
    print(f"\n  liquidation: {solde:+,.2f} USD")
    print(f"  EQUITY FINALE campagne {camp}: {equity_finale:,.2f} USD "
          f"({100*(equity_finale/capital - 1):+.2f}%)")
    print(f"\n=== CAMPAGNE {camp + 1}: {nom} ===")
    print(f"  capital initial {capital:,.0f} USD, 0 position")

    if not appliquer:
        print("\nSIMULATION. Relancer avec --appliquer pour executer.")
        return

    sauvegarde = PROJECT_ROOT / "data" / "backups" / f"fin_campagne_{camp}_{date.today()}.db"
    sauvegarde.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(PROJECT_ROOT / "atlas.db", sauvegarde)
    print(f"\n  sauvegarde integrale: {sauvegarde.name}")

    maintenant = datetime.now(timezone.utc).isoformat()
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT OR REPLACE INTO campagnes (id, nom, debut, fin,"
            " capital_initial, equity_finale, note) VALUES (:id, :nom, :d,"
            " :f, :ci, :ef, :note)"),
            {"id": camp, "nom": f"campagne {camp}", "d": b["debut"] or "",
             "f": maintenant, "ci": capital, "ef": equity_finale,
             "note": f"{b['trades']} trades, {b['gagnants']} gagnants"})
        conn.execute(text(
            "INSERT INTO campagnes (id, nom, debut, capital_initial)"
            " VALUES (:id, :nom, :d, :ci)"),
            {"id": camp + 1, "nom": nom, "d": maintenant, "ci": capital})
        # Les signaux en attente ont ete generes par l'ancien score
        conn.execute(text("UPDATE signals SET status='expired'"
                          " WHERE status='new'"))
        conn.execute(text("UPDATE paper_account SET cash=:c WHERE id=1"),
                     {"c": capital})
    print(f"  campagne {camp} figee, campagne {camp + 1} ouverte")
    print(f"  cash remis a {capital:,.0f} USD, signaux en attente expires")
    print("\n  L'historique n'est PAS efface: trades, ordres et equity de la")
    print(f"  campagne {camp} restent en base sous leur numero.")


if __name__ == "__main__":
    main()
