# -*- coding: utf-8 -*-
"""Reconstruit la courbe d'equity a partir des ordres et des cours reels.

Pourquoi: jusqu'au 2026-08-26, le cache de cours n'etait rafraichi qu'un jour
sur deux (voir atlas/data/store.py). Un jour sur deux, l'equity du soir etait
donc recopiee de la veille - 14 paires de valeurs identiques au centieme dans
paper_equity. Toute analyse de performance batie sur cette courbe (volatilite,
drawdown, Sharpe) est faussee.

Ici on rejoue les ordres executes dans l'ordre chronologique, on reconstitue
le cash et les quantites detenues a chaque date, et on valorise aux cours de
CLOTURE reels de la date en question. Le resultat va dans paper_equity_recalc:
l'historique d'origine n'est pas ecrase, on garde la trace de l'incident.

  python scripts/recalculer_equity.py            # simulation
  python scripts/recalculer_equity.py --ecrire   # ecrit paper_equity_recalc
"""

from __future__ import annotations

import sys
from collections import defaultdict

import pandas as pd
from sqlalchemy import text

from atlas.data.fx import FX_PAIRS, currency_of
from atlas.data.markets import last_expected_session, market_by_code
from atlas.data.store import init_db, load_ohlcv

CAPITAL = 100_000.0


def _series_fx() -> dict[str, pd.Series]:
    """Serie quotidienne de chaque taux de change, plus USD constant."""
    out: dict[str, pd.Series] = {}
    for devise, paire in FX_PAIRS.items():
        df = load_ohlcv(paire)
        if not df.empty:
            out[devise] = df["close"]
    if "GBP" in out:
        out["GBp"] = out["GBP"] / 100.0
    return out


def _taux(fx: dict[str, pd.Series], devise: str, jour: pd.Timestamp) -> float:
    if devise == "USD":
        return 1.0
    s = fx.get(devise)
    if s is None:
        return 1.0
    dispo = s.loc[s.index <= jour]
    return float(dispo.iloc[-1]) if len(dispo) else 1.0


def reconstruire(engine) -> pd.DataFrame:
    with engine.connect() as conn:
        ordres = conn.execute(text(
            "SELECT ticker, side, qty, filled_price, filled_at FROM orders"
            " WHERE status='filled' ORDER BY filled_at, id")).fetchall()
    if not ordres:
        return pd.DataFrame()

    fx = _series_fx()
    cours = {t: load_ohlcv(t) for t in {o[0] for o in ordres}}

    mouvements = []
    for ticker, side, qty, prix, quand in ordres:
        jour = pd.Timestamp(quand).tz_convert(None).normalize() \
            if pd.Timestamp(quand).tzinfo else pd.Timestamp(quand).normalize()
        mouvements.append((jour, ticker, side, float(qty), float(prix)))

    debut = min(m[0] for m in mouvements)
    fin = pd.Timestamp(last_expected_session(market_by_code("US")))
    jours = pd.bdate_range(debut, fin)

    cash = CAPITAL
    detenu: dict[str, float] = defaultdict(float)
    idx = 0
    lignes = []
    for jour in jours:
        while idx < len(mouvements) and mouvements[idx][0] <= jour:
            _, ticker, side, qty, prix = mouvements[idx]
            taux = _taux(fx, currency_of(ticker), jour)
            if side == "buy":
                cash -= prix * qty * taux
                detenu[ticker] += qty
            else:
                cash += prix * qty * taux
                detenu[ticker] -= qty
                if abs(detenu[ticker]) < 1e-9:
                    detenu.pop(ticker, None)
            idx += 1

        valeur = 0.0
        manquants = 0
        for ticker, qty in detenu.items():
            df = cours.get(ticker)
            if df is None or df.empty:
                manquants += 1
                continue
            dispo = df.loc[df.index <= jour]
            if not len(dispo):
                manquants += 1
                continue
            px = float(dispo["close"].iloc[-1])
            valeur += px * qty * _taux(fx, currency_of(ticker), jour)
        lignes.append({"date": jour.date().isoformat(),
                       "equity": cash + valeur, "cash": cash,
                       "positions": len(detenu), "sans_cours": manquants})
    return pd.DataFrame(lignes)


def main() -> None:
    engine = init_db()
    rec = reconstruire(engine)
    if rec.empty:
        print("aucun ordre a rejouer")
        return

    with engine.connect() as conn:
        anc = pd.DataFrame(conn.execute(text(
            "SELECT date, equity FROM paper_equity ORDER BY date")).fetchall(),
            columns=["date", "equity"])
    comp = rec.merge(anc, on="date", how="left", suffixes=("_recalc", "_base"))
    comp["ecart"] = comp["equity_recalc"] - comp["equity_base"]

    print(f"{len(rec)} jours de bourse reconstruits "
          f"({rec.date.iloc[0]} -> {rec.date.iloc[-1]})")
    vus = comp.dropna(subset=["equity_base"])
    print(f"{len(vus)} jours comparables avec l'historique enregistre")
    print(f"  ecart moyen  : {vus.ecart.mean():+,.0f} USD")
    print(f"  ecart median : {vus.ecart.median():+,.0f} USD")
    print(f"  ecart max    : {vus.ecart.abs().max():,.0f} USD")
    print(f"  equity finale: recalculee {rec.equity.iloc[-1]:,.0f} USD"
          f" | enregistree {vus.equity_base.iloc[-1]:,.0f} USD")
    if rec.sans_cours.max():
        print(f"  ATTENTION: jusqu'a {rec.sans_cours.max()} titre(s) sans cours")

    print("\n  10 plus gros ecarts:")
    for _, r in vus.reindex(vus.ecart.abs().sort_values(ascending=False).index).head(10).iterrows():
        print(f"    {r.date}  recalcul {r.equity_recalc:10,.0f}  "
              f"enregistre {r.equity_base:10,.0f}  ecart {r.ecart:+8,.0f}")

    if "--ecrire" in sys.argv:
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS paper_equity_recalc"))
            conn.execute(text(
                "CREATE TABLE paper_equity_recalc (date TEXT PRIMARY KEY,"
                " equity REAL, cash REAL, positions INTEGER)"))
            for _, r in rec.iterrows():
                conn.execute(text(
                    "INSERT INTO paper_equity_recalc (date, equity, cash,"
                    " positions) VALUES (:d, :e, :c, :p)"),
                    {"d": r.date, "e": float(r.equity), "c": float(r.cash),
                     "p": int(r.positions)})
        print(f"\npaper_equity_recalc ecrite ({len(rec)} lignes)")
    else:
        print("\nSIMULATION. Relancer avec --ecrire pour enregistrer.")


if __name__ == "__main__":
    main()
