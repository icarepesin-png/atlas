# -*- coding: utf-8 -*-
"""Le pilier fondamental predit-il quelque chose ? Mesure sur 15 ans.

C'est la question qui bloquait le projet. Le pilier technique a ete mesure sur
2010-2026 et neutralise (IC -0.008, aucune information). Le fondamental porte
desormais 70% du score, mais il n'avait JAMAIS pu etre teste: les fondamentaux
Yahoo sont un instantane, les utiliser dans le passe revient a acheter en
connaissant l'avenir. Avec les depots EDGAR et leurs dates de publication, la
mesure devient possible.

Methode: a chaque date de mesure, chaque titre est note avec les comptes
REELLEMENT publies ce jour-la, on classe l'univers, et on regarde ce que les
titres bien classes ont fait ensuite. L'IC est la correlation de rang entre
note et rendement futur, calculee date par date puis moyennee - sinon les
mouvements de marche communs a tous les titres dominent le resultat.

  python scripts/ic_fondamental_pit.py             # univers actuel (biaise)
  python scripts/ic_fondamental_pit.py --corrige   # composition de chaque date
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from atlas.config import get_config
from atlas.data.store import load_ohlcv
from atlas.features.fundamental_pit import ratios_au

HORIZONS = (21, 63)          # ~1 mois et ~1 trimestre de bourse
MIN_TITRES = 40              # par date, pour un classement exploitable
DEBUT = "2010-01-01"

# Sens attendu: +1 = "plus c'est haut, mieux c'est"
SENS = {"roe": 1, "roa": 1, "roic": 1, "gross_margin": 1,
        "operating_margin": 1, "net_margin": 1, "revenue_growth": 1,
        "eps_growth": 1, "fcf_yield": 1, "pe": -1, "ps": -1,
        "debt_to_equity": -1}


def dates_de_mesure(fin: pd.Timestamp) -> list[pd.Timestamp]:
    """Un point par trimestre: les comptes annuels ne bougent qu'une fois
    l'an, mesurer plus souvent n'ajoute que du bruit et du temps de calcul."""
    return list(pd.date_range(DEBUT, fin, freq="QE"))


def main() -> None:
    chemin = Path(get_config().cache_dir) / "edgar" / "faits_edgar.parquet"
    if not chemin.exists():
        print("Lancer d'abord: python scripts/moisson_edgar.py")
        raise SystemExit(1)
    faits = pd.read_parquet(chemin)
    print(f"{len(faits):,} faits, {faits.ticker.nunique()} societes")

    # Sans correction, l'univers est fait des membres ACTUELS projetes dans le
    # passe: l'echantillon ne contient que des survivants et les mesures n'ont
    # pas de sens (voir docs/BACKTEST.md).
    membres = None
    if "--corrige" in sys.argv:
        f = Path(get_config().cache_dir) / "univers_historique" / "compositions.json"
        if not f.exists():
            print("Lancer d'abord: python scripts/univers_historique.py --cours")
            raise SystemExit(1)
        membres = {pd.Timestamp(d): set(lot)
                   for d, lot in json.loads(f.read_text(encoding="utf-8")).items()}
        print(f"univers CORRIGE: composition reelle de {len(membres)} trimestres")
    else:
        print("univers BIAISE: membres actuels projetes dans le passe")

    cours = {}
    for t in faits.ticker.unique():
        df = load_ohlcv(t)
        if not df.empty:
            s = df["close"]
            s.index = pd.DatetimeIndex(s.index).normalize()
            cours[t] = s
    print(f"{len(cours)} series de cours chargees")

    fin = min(max(s.index.max() for s in cours.values()),
              pd.Timestamp.today().normalize())
    dates = (sorted(membres) if membres is not None else dates_de_mesure(fin))
    dates = [d for d in dates if d <= fin]
    print(f"{len(dates)} dates de mesure, {dates[0].date()} -> {dates[-1].date()}\n")

    lignes = []
    for ticker, f in faits.groupby("ticker"):
        serie = cours.get(ticker)
        if serie is None or len(serie) < 300:
            continue
        for d in dates:
            if membres is not None and ticker not in membres.get(d, ()):
                continue      # ce titre n'etait pas dans l'indice ce jour-la
            dispo = serie.loc[serie.index <= d]
            if len(dispo) < 60:
                continue
            px = float(dispo.iloc[-1])
            r = ratios_au(f, d, cours=px)
            if not r:
                continue
            futur = serie.loc[serie.index > d]
            ligne = {"date": d, "ticker": ticker}
            ligne.update({k: v for k, v in r.items() if not k.startswith("_")})
            for h in HORIZONS:
                ligne[f"ret{h}"] = (float(futur.iloc[h - 1]) / px - 1
                                    if len(futur) >= h else np.nan)
            lignes.append(ligne)

    d = pd.DataFrame(lignes)
    print(f"{len(d):,} observations (titre x date)\n")

    print(f"{'facteur':20}" + "".join(f"{'IC ' + str(h) + 'j':>12}" for h in HORIZONS)
          + f"{'couverture':>12}")
    resultats = {}
    for facteur, sens in SENS.items():
        if facteur not in d.columns:
            continue
        cellules, couv = "", d[facteur].notna().mean()
        for h in HORIZONS:
            ics = []
            for _, g in d.groupby("date"):
                g = g[[facteur, f"ret{h}"]].dropna()
                if len(g) < MIN_TITRES:
                    continue
                ic = g[facteur].corr(g[f"ret{h}"], method="spearman")
                if pd.notna(ic):
                    ics.append(sens * ic)
            valeur = float(np.mean(ics)) if ics else np.nan
            resultats.setdefault(facteur, {})[h] = (valeur, len(ics))
            cellules += f"{valeur:+12.3f}" if ics else f"{'n/d':>12}"
        print(f"{facteur:20}{cellules}{100*couv:11.0f}%")

    print("\n  Sens corrige: un IC positif signifie que le facteur marche dans")
    print("  la direction attendue (un PER bas est un bon signe, pas un mauvais).")
    print("  Reperes: |IC| < 0.02 = bruit, 0.03-0.05 = faible mais exploitable,")
    print("  > 0.05 = bon signal.")

    # Le score fondamental agrege, tel que le systeme l'utiliserait
    print("\n=== score fondamental agrege (rang moyen des facteurs) ===")
    for h in HORIZONS:
        ics = []
        for _, g in d.groupby("date"):
            g = g.copy()
            rangs = []
            for facteur, sens in SENS.items():
                if facteur in g.columns and g[facteur].notna().sum() >= MIN_TITRES:
                    rangs.append(sens * g[facteur].rank(pct=True))
            if len(rangs) < 4:
                continue
            g["_score"] = pd.concat(rangs, axis=1).mean(axis=1)
            sub = g[["_score", f"ret{h}"]].dropna()
            if len(sub) < MIN_TITRES:
                continue
            ic = sub["_score"].corr(sub[f"ret{h}"], method="spearman")
            if pd.notna(ic):
                ics.append(ic)
        if ics:
            arr = np.array(ics)
            t_stat = arr.mean() / (arr.std() / np.sqrt(len(arr)))
            print(f"  {h:2d} seances: IC moyen {arr.mean():+.3f} | "
                  f"positif {100*(arr > 0).mean():3.0f}% du temps | "
                  f"t = {t_stat:+.2f} sur {len(arr)} dates")


if __name__ == "__main__":
    main()
