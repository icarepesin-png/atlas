# -*- coding: utf-8 -*-
"""Le pilier technique est-il structurellement inverse, ou en mauvaise passe ?

L'IC mesure de juin a aout 2026 est de -0.289 sur 21 seances, negatif 30 jours
sur 30. Deux lectures possibles et opposees:
  a) le signal ne marche pas (il faut le neutraliser),
  b) il traverse un "momentum crash" - phenomene documente, frequent dans les
     rebonds ou les titres massacres repartent le plus fort.
2 mois et demi ne permettent pas de trancher. Le score technique etant calcule
UNIQUEMENT a partir des prix, il est reconstructible sur 15 ans sans le biais
des fondamentaux non point-in-time: on peut donc mesurer son IC annee par annee.

APPROXIMATION ASSUMEE: on reconstruit la partie vectorisable du score, soit 75
des 100 points (SMA200 20, EMA50 15, MACD 10, ADX 10, RSI 10, distance au plus
haut 52s 10). Les 25 points restants (stage de Weinstein 15, setup breakout/
pullback/VCP 10) demandent un calcul point par point trop couteux ici. Le
classement des titres, qui est tout ce que mesure un IC de rang, en est peu
affecte.

  python scripts/ic_technique_historique.py
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from atlas.data.store import load_ohlcv
from atlas.features.technical import adx, ema, macd, rsi, sma
from atlas.universe.loader import build_universe

HORIZON = 21          # seances
MIN_TITRES = 40       # par date, pour un IC exploitable
DEBUT = "2010-01-01"


def score_technique_vectoriel(df: pd.DataFrame) -> pd.Series:
    """Score technique (partie vectorisable) pour CHAQUE date de la serie."""
    c = df["close"]
    s = pd.Series(0.0, index=df.index)
    s += 20 * (c > sma(c, 200)).astype(float)
    s += 15 * (c > ema(c, 50)).astype(float)
    s += 10 * (macd(c)[2] > 0).astype(float)
    s += 10 * (adx(df) / 40.0).clip(upper=1.0).fillna(0.0)
    r = rsi(c)
    s += 10 * ((r >= 45) & (r <= 75)).astype(float) \
        + 5 * ((r >= 40) & (r < 45)).astype(float)
    plus_haut = c.rolling(252).max()
    d52 = c / plus_haut - 1
    s += (10 * (1.0 + d52 / 0.25)).where(d52 > -0.25, 0.0).clip(lower=0)
    return s


def main() -> None:
    tickers = build_universe()
    scores, rendements = {}, {}
    retenus = 0
    for t in tickers:
        df = load_ohlcv(t)
        if df.empty or len(df) < 300:
            continue
        df = df[df.index >= DEBUT]
        if len(df) < 300:
            continue
        try:
            s = score_technique_vectoriel(df)
        except Exception:
            continue
        c = df["close"]
        fwd = c.shift(-HORIZON) / c - 1
        scores[t] = s
        rendements[t] = fwd
        retenus += 1

    S = pd.DataFrame(scores)
    R = pd.DataFrame(rendements)
    print(f"{retenus} titres, {S.index.min().date()} -> {S.index.max().date()}")

    # IC par date (transversal), puis moyenne par annee
    dates = S.index[::5]                      # une mesure par semaine
    lignes = []
    for d in dates:
        s, r = S.loc[d], R.loc[d]
        ok = s.notna() & r.notna()
        if ok.sum() < MIN_TITRES:
            continue
        ic = s[ok].corr(r[ok], method="spearman")
        if pd.notna(ic):
            lignes.append({"date": d, "ic": ic})
    d = pd.DataFrame(lignes).set_index("date")
    print(f"{len(d)} mesures hebdomadaires\n")

    print(f"{'annee':8}{'IC moyen':>11}{'% dates <0':>13}{'mesures':>10}")
    for an, grp in d.groupby(d.index.year):
        print(f"{an:<8}{grp.ic.mean():+11.3f}{100*(grp.ic < 0).mean():12.0f}%"
              f"{len(grp):10d}")
    print(f"\n{'ENSEMBLE':8}{d.ic.mean():+11.3f}"
          f"{100*(d.ic < 0).mean():12.0f}%{len(d):10d}")
    print(f"  ecart-type des IC: {d.ic.std():.3f}")
    print(f"  IC median        : {d.ic.median():+.3f}")

    recent = d[d.index >= "2026-06-01"]
    if len(recent):
        print(f"\n  periode du test paper (depuis juin 2026): "
              f"IC moyen {recent.ic.mean():+.3f} sur {len(recent)} mesures")
        pire = d.ic.mean() - 2 * d.ic.std()
        print(f"  seuil 'anormal' (moyenne - 2 ecarts-types): {pire:+.3f}")
        print("  -> la periode recente est "
              + ("DANS la variation historique normale"
                 if recent.ic.mean() > pire else "HORS norme historique"))


if __name__ == "__main__":
    main()
