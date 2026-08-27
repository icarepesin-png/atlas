# -*- coding: utf-8 -*-
"""Mesure l'effet du biais du survivant sur les resultats.

On refait exactement la meme mesure sur deux univers:
  A. BIAISE   - les membres ACTUELS de l'indice, projetes dans le passe.
     C'est ce que le projet faisait depuis juin.
  B. CORRIGE  - a chaque date, les membres de l'indice A CETTE DATE, y compris
     ceux qui en sont sortis depuis.

Les facteurs testes sont des temoins dont l'effet est documente: si l'univers
biaise inverse le signe du facteur volatilite et annule le momentum, et que
l'univers corrige les rapproche de la litterature, alors le biais explique
les resultats absurdes du 2026-08-27 et non les facteurs eux-memes.

  python scripts/comparer_biais_survivant.py
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from atlas.config import get_config
from atlas.data.store import load_ohlcv
from atlas.universe.loader import build_universe

MIN_TITRES = 40


def series_cours(tickers) -> dict[str, pd.Series]:
    out = {}
    for t in tickers:
        df = load_ohlcv(t)
        if df.empty or len(df) < 300:
            continue
        s = df["close"]
        s.index = pd.DatetimeIndex(s.index).normalize()
        out[t] = s
    return out


def observations(cours: dict[str, pd.Series], dates,
                 membres: dict[str, list[str]] | None = None) -> pd.DataFrame:
    """Facteurs temoins et rendements futurs, date par date.

    `membres` restreint l'univers a la composition de chaque date. Sans lui,
    tous les titres connus sont utilises a toutes les dates - c'est
    precisement le biais qu'on veut mesurer.
    """
    lignes = []
    for d in dates:
        autorises = set(membres[str(d.date())]) if membres else None
        for t, s in cours.items():
            if autorises is not None and t not in autorises:
                continue
            passe = s.loc[s.index <= d]
            if len(passe) < 260:
                continue
            futur = s.loc[s.index > d]
            if len(futur) < 63:
                continue
            px = float(passe.iloc[-1])
            lignes.append({
                "date": d, "ticker": t,
                "momentum": float(passe.iloc[-21]) / float(passe.iloc[-252]) - 1,
                "volatilite": float(passe.pct_change().iloc[-252:].std()),
                "ret63": float(futur.iloc[62]) / px - 1,
            })
    return pd.DataFrame(lignes)


def ic(d: pd.DataFrame, facteur: str, sens: int) -> tuple[float, float, int]:
    ics = []
    for _, g in d.groupby("date"):
        sub = g[[facteur, "ret63"]].dropna()
        if len(sub) < MIN_TITRES:
            continue
        c = sub[facteur].corr(sub["ret63"], method="spearman")
        if pd.notna(c):
            ics.append(sens * c)
    if not ics:
        return float("nan"), float("nan"), 0
    a = np.array(ics)
    return a.mean(), a.mean() / (a.std() / np.sqrt(len(a))), len(a)


def main() -> None:
    dossier = Path(get_config().cache_dir) / "univers_historique"
    compositions = json.loads(
        (dossier / "compositions.json").read_text(encoding="utf-8"))
    dates = [pd.Timestamp(d) for d in sorted(compositions)]

    actuels = build_universe()
    tous = sorted({t for lot in compositions.values() for t in lot} | set(actuels))
    cours = series_cours(tous)
    disponibles = set(cours)
    print(f"{len(tous)} titres ayant appartenu a l'indice, "
          f"{len(disponibles)} avec un historique de cours")
    sortis = [t for t in tous if t not in set(actuels) and t in disponibles]
    print(f"dont {len(sortis)} sortis de l'indice et malgre tout recuperables\n")

    # A. univers biaise: uniquement les membres actuels, a toutes les dates
    cours_actuels = {t: s for t, s in cours.items() if t in set(actuels)}
    a = observations(cours_actuels, dates)

    # B. univers corrige: la composition de chaque date
    membres = {d: [t for t in lot if t in disponibles]
               for d, lot in compositions.items()}
    b = observations(cours, dates, membres=membres)

    print(f"{'':24}{'BIAISE':>22}{'CORRIGE':>22}")
    print(f"{'observations':24}{len(a):>22,}{len(b):>22,}")
    print()
    print(f"{'facteur temoin':24}{'IC 63j':>10}{'t':>12}{'IC 63j':>10}{'t':>12}")
    for nom, facteur, sens in (("momentum 12-1", "momentum", 1),
                               ("volatilite faible", "volatilite", -1)):
        ia, ta, _ = ic(a, facteur, sens)
        ib, tb, _ = ic(b, facteur, sens)
        print(f"{nom:24}{ia:+10.3f}{ta:+12.2f}{ib:+10.3f}{tb:+12.2f}")

    print("\n  Sens corrige: un IC positif = le facteur marche dans la direction")
    print("  attendue par la litterature (momentum paye, volatilite forte punit).")
    print("  Si la colonne CORRIGE se rapproche de zero ou du positif alors que")
    print("  la colonne BIAISE est franchement negative, le biais du survivant")
    print("  fabriquait le resultat.")


if __name__ == "__main__":
    main()
