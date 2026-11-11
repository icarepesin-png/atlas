# -*- coding: utf-8 -*-
"""La strategie reelle a-t-elle un avantage ? Reponse sur 2010-2026.

Rejoue les regles du paper trading (entree a l'ouverture suivante, sizing par
le risque, stop 2 ATR, suiveur 2,75 ATR, prise partielle a 1,5R, carence)
sur l'univers historique du S&P 500 et les comptes EDGAR dates.

La question n'est pas "la strategie gagne-t-elle de l'argent": sur 16 ans de
marche haussier, presque tout gagne. La question est "la SELECTION fait-elle
mieux que le hasard, a regles de sortie identiques". D'ou le temoin: memes
regles, titres tires au sort, plusieurs tirages. Une famille de facteurs n'a
de valeur que si elle sort nettement de la distribution du hasard.

  python scripts/backtest_fidele.py              # complet (une dizaine de minutes)
  python scripts/backtest_fidele.py --tirages 5  # essai rapide
"""

from __future__ import annotations

import json
import logging
import sys

import numpy as np
import pandas as pd

from atlas.backtest.fidele import Parametres, mesures, simuler
from atlas.backtest.pit_data import (charger, hasard, scores_familles,
                                     titres_historiques)
from atlas.config import PROJECT_ROOT
from atlas.data import prix_reels
from atlas.data.store import load_ohlcv

DEBUT = "2010-04-01"
SELECTIVITES = {"0,6% (reglage reel)": 0.006, "2%": 0.02, "5%": 0.05,
                "10%": 0.10}
PERIODES = (("2010-2015", "2010-04-01", "2015-12-31"),
            ("2016-2020", "2016-01-01", "2020-12-31"),
            ("2021-2026", "2021-01-01", "2026-12-31"))


def completer_prix_reels() -> None:
    """Telecharge les cours non ajustes des dividendes et les divisions pour
    les titres qui n'en ont pas encore (indispensable aux ratios de valeur,
    voir atlas/data/prix_reels.py)."""
    manquants = [t for t in titres_historiques()
                 if not load_ohlcv(t).empty and prix_reels.charger(t).empty]
    if manquants:
        print(f"telechargement des cours reels de {len(manquants)} titres...")
        bilan = prix_reels.telecharger(manquants)
        print(f"  {bilan['obtenus']} obtenus, {bilan['absents']} absents\n")


def ic_familles(d, scores: dict, horizons=(21, 63), pas: int = 21) -> dict:
    """Correlation de rang score / rendement futur, une mesure par mois."""
    out = {}
    t0 = int(np.searchsorted(d.cal.values, np.datetime64(pd.Timestamp(DEBUT))))
    for nom, s in scores.items():
        out[nom] = {}
        for h in horizons:
            ics = []
            for t in range(t0, len(d.cal) - h, pas):
                futur = d.cloture[t + h] / d.cloture[t] - 1
                ok = np.isfinite(s[t]) & np.isfinite(futur) & d.membre[t]
                if ok.sum() < 40:
                    continue
                a = pd.Series(s[t][ok]).rank()
                b = pd.Series(futur[ok]).rank()
                ics.append(float(np.corrcoef(a, b)[0, 1]))
            arr = np.array(ics)
            out[nom][h] = {
                "ic": float(arr.mean()), "n": len(arr),
                "positif": float((arr > 0).mean()),
                "t": float(arr.mean() / (arr.std() / np.sqrt(len(arr)))),
            }
    return out


def sharpe(equity: pd.Series, debut: str | None = None,
           fin: str | None = None) -> float:
    e = equity.loc[debut:fin] if (debut or fin) else equity
    r = e.pct_change().dropna()
    return float(r.mean() / r.std() * np.sqrt(252)) if len(r) > 20 and r.std() > 0 else float("nan")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    tirages = 20
    if "--tirages" in sys.argv:
        tirages = int(sys.argv[sys.argv.index("--tirages") + 1])

    completer_prix_reels()
    d = charger()
    c = d.couverture
    print(f"univers: {c['titres_historiques']} titres ont appartenu a l'indice,"
          f" {c['avec_cours']} avec cours, {c['avec_comptes']} avec comptes")
    print(f"couverture des membres de l'indice: {100*c['membres_couverts_moy']:.0f}%"
          f" en moyenne, {100*c['membres_couverts_min']:.0f}% au plus bas")
    print(f"periode: {DEBUT} -> {d.cal[-1].date()}\n")

    scores = scores_familles(d)

    print("=== 1. pouvoir predictif des familles (une mesure par mois) ===")
    ic = ic_familles(d, scores)
    print(f"{'famille':18}{'IC 21j':>9}{'t':>7}{'IC 63j':>9}{'t':>7}{'positif':>9}")
    for nom, par_h in ic.items():
        a, b = par_h[21], par_h[63]
        print(f"{nom:18}{a['ic']:+9.3f}{a['t']:+7.2f}{b['ic']:+9.3f}"
              f"{b['t']:+7.2f}{100*b['positif']:8.0f}%")
    print("  |t| > 2 = statistiquement significatif. La mesure a 21 jours est"
          "\n  sans chevauchement; celle a 63 jours se chevauche (t surestime).\n")

    spy = load_ohlcv("SPY")["close"]
    spy = spy[spy.index >= DEBUT]
    annees = (spy.index[-1] - spy.index[0]).days / 365.25
    cagr_spy = (spy.iloc[-1] / spy.iloc[0]) ** (1 / annees) - 1
    dd_spy = float((spy / spy.cummax() - 1).min())

    resume = {"periode": [DEBUT, str(d.cal[-1].date())], "couverture": c,
              "ic": ic, "strategies": {}, "periodes": {},
              "spy": {"cagr": float(cagr_spy), "sharpe": sharpe(spy),
                      "drawdown_max": dd_spy}}

    courbes: dict = {}
    for libelle, q in SELECTIVITES.items():
        p = Parametres.depuis_config(selectivite=q)
        print(f"=== 2. regles reelles, {libelle} de l'indice retenu chaque jour ===")
        print(f"{'selection':20}{'CAGR':>8}{'Sharpe':>8}{'DD max':>9}"
              f"{'trades':>8}{'reussite':>10}{'PF':>6}{'expo':>7}")

        res_temoins = [simuler(d, hasard(d, g), p, debut=DEBUT)
                       for g in range(tirages)]
        temoins = [mesures(r) for r in res_temoins]
        cagrs = np.array([m["cagr"] for m in temoins])
        sharpes = np.array([m["sharpe"] for m in temoins])
        print(f"{'HASARD (moyenne)':20}{100*cagrs.mean():+7.1f}%"
              f"{sharpes.mean():+8.2f}"
              f"{100*np.mean([m['drawdown_max'] for m in temoins]):8.1f}%"
              f"{np.mean([m['trades'] for m in temoins]):8.0f}"
              f"{100*np.mean([m['reussite'] for m in temoins]):9.0f}%"
              f"{np.mean([m['profit_factor'] for m in temoins]):6.2f}"
              f"{100*np.mean([m['exposition_moyenne'] for m in temoins]):6.0f}%")
        print(f"{'  ecart-type':20}{100*cagrs.std():7.1f}%{sharpes.std():8.2f}")

        bloc = {"hasard": {"cagr_moyen": float(cagrs.mean()),
                           "cagr_ecart_type": float(cagrs.std()),
                           "sharpe_moyen": float(sharpes.mean()),
                           "sharpe_ecart_type": float(sharpes.std()),
                           "exposition": float(np.mean(
                               [m["exposition_moyenne"] for m in temoins])),
                           "tirages": tirages}}
        courbes[libelle] = {"hasard": [r.equity for r in res_temoins]}
        for nom, s in scores.items():
            r = simuler(d, s, p, debut=DEBUT)
            m = mesures(r)
            z = (m["sharpe"] - sharpes.mean()) / sharpes.std() if sharpes.std() else 0
            bat = float((sharpes < m["sharpe"]).mean())
            m.update(z_vs_hasard=float(z), bat_les_tirages=bat)
            bloc[nom] = m
            courbes[libelle][nom] = r.equity
            print(f"{nom:20}{100*m['cagr']:+7.1f}%{m['sharpe']:+8.2f}"
                  f"{100*m['drawdown_max']:8.1f}%{m['trades']:8d}"
                  f"{100*m['reussite']:9.0f}%{m['profit_factor']:6.2f}"
                  f"{100*m['exposition_moyenne']:6.0f}%"
                  f"   z={z:+.1f}, bat {100*bat:.0f}% des tirages")
        resume["strategies"][libelle] = bloc
        print()

    print(f"reference: SPY achete et conserve = {100*cagr_spy:+.1f}% par an, "
          f"Sharpe {sharpe(spy):.2f}, drawdown {100*dd_spy:.0f}%\n")

    print("=== 3. stabilite dans le temps (Sharpe par periode, selectivite 5%) ===")
    ref = courbes["5%"]
    print(f"{'selection':20}" + "".join(f"{n:>12}" for n, _, _ in PERIODES))
    ligne_h = []
    for _, a, b in PERIODES:
        ligne_h.append(np.nanmean([sharpe(e, a, b) for e in ref["hasard"]]))
    print(f"{'HASARD (moyenne)':20}" + "".join(f"{v:+12.2f}" for v in ligne_h))
    resume["periodes"]["hasard"] = [float(v) for v in ligne_h]
    for nom in scores:
        vals = [sharpe(ref[nom], a, b) for _, a, b in PERIODES]
        resume["periodes"][nom] = [float(v) for v in vals]
        print(f"{nom:20}" + "".join(f"{v:+12.2f}" for v in vals))

    print("\n  z = ecart au hasard en ecarts-types (Sharpe). z > 2: la selection")
    print("  apporte quelque chose. z proche de 0: elle ne fait pas mieux que")
    print("  des titres tires au sort avec les memes regles de sortie.")

    sortie = PROJECT_ROOT / "data" / "backtest_fidele.json"
    sortie.write_text(json.dumps(resume, indent=1, default=float),
                      encoding="utf-8")
    print(f"\nresultats enregistres dans {sortie.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
