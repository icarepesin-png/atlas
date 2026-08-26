# -*- coding: utf-8 -*-
"""Le score composite predit-il quoi que ce soit ? (IC par pilier)

C'est LE test qui manquait: le backtest valide un proxy momentum rebalance
mensuellement, pas le score a 5 piliers qui declenche reellement les achats.
On mesure ici, sur les scores REELLEMENT calcules chaque nuit depuis juin,
la correlation de rang entre le score du jour et le rendement des N seances
suivantes (information coefficient).

Reperes usuels: |IC| < 0.02 = bruit. 0.03-0.05 = faible mais exploitable.
> 0.05 = bon. Un IC negatif signifie un signal a l'envers.

  python scripts/pouvoir_predictif.py
"""

from __future__ import annotations

import sqlite3

import pandas as pd

from atlas.data.store import load_ohlcv

HORIZONS = (5, 10, 21)
PILIERS = ("composite", "fundamental", "technical", "sector")


def main() -> None:
    con = sqlite3.connect("atlas.db")
    scores = pd.read_sql_query(
        "SELECT as_of_date, ticker, composite, fundamental, technical,"
        " macro, sector, sentiment FROM scores", con)
    scores["d"] = pd.to_datetime(scores["as_of_date"]).dt.normalize()
    print(f"{len(scores):,} lignes de score, {scores.ticker.nunique()} titres, "
          f"{scores.d.nunique()} dates ({scores.d.min().date()} -> "
          f"{scores.d.max().date()})")

    cours = {}
    for t in scores.ticker.unique():
        df = load_ohlcv(t)
        if not df.empty:
            cours[t] = df["close"]

    lignes = []
    for t, grp in scores.groupby("ticker"):
        s = cours.get(t)
        if s is None or len(s) < max(HORIZONS) + 2:
            continue
        for _, r in grp.iterrows():
            apres = s.loc[s.index >= r["d"]]
            if len(apres) <= max(HORIZONS):
                continue
            p0 = float(apres.iloc[0])
            if p0 <= 0:
                continue
            ligne = {p: r[p] for p in PILIERS}
            ligne["ticker"] = t
            ligne["d"] = r["d"]
            for h in HORIZONS:
                ligne[f"ret{h}"] = 100 * (float(apres.iloc[h]) / p0 - 1)
            lignes.append(ligne)

    d = pd.DataFrame(lignes)
    print(f"{len(d):,} observations exploitables\n")

    print(f"{'pilier':14}" + "".join(f"{'IC ' + str(h) + 'j':>12}" for h in HORIZONS))
    for p in PILIERS:
        cells = ""
        for h in HORIZONS:
            # IC calcule DATE PAR DATE puis moyenne: sinon les mouvements de
            # marche communs a tous les titres dominent la correlation.
            ics = [g[p].corr(g[f"ret{h}"], method="spearman")
                   for _, g in d.groupby("d") if len(g) > 30]
            ics = [x for x in ics if pd.notna(x)]
            cells += f"{sum(ics)/len(ics):+12.3f}" if ics else f"{'n/a':>12}"
        print(f"{p:14}{cells}")

    print("\n=== rendement moyen par tranche de score composite ===")
    tranches = [(0, 60), (60, 70), (70, 80), (80, 85), (85, 101)]
    print(f"{'tranche':14}{'obs':>8}" + "".join(f"{str(h)+'j':>10}" for h in HORIZONS))
    for lo, hi in tranches:
        sub = d[(d.composite >= lo) & (d.composite < hi)]
        if sub.empty:
            continue
        cells = "".join(f"{sub[f'ret{h}'].mean():+9.2f}%" for h in HORIZONS)
        etoile = "  <- seuil de signal" if lo == 85 else ""
        print(f"{lo}-{hi if hi < 101 else 100:<10}{len(sub):>8,}{cells}{etoile}")

    print("\n=== le seuil 85 fait-il mieux que le reste de l'univers ? ===")
    for h in HORIZONS:
        hauts = d[d.composite >= 85][f"ret{h}"]
        autres = d[d.composite < 85][f"ret{h}"]
        print(f"  {h:2d} seances: signal {hauts.mean():+.2f}% "
              f"({len(hauts):,} obs) vs reste {autres.mean():+.2f}% "
              f"-> ecart {hauts.mean() - autres.mean():+.2f} pts")


if __name__ == "__main__":
    main()
