# -*- coding: utf-8 -*-
"""Que valent les regles de sortie, independamment du choix des titres ?

On tire les titres AU HASARD et on ne fait varier que les sorties. Comme la
selection n'apporte rien par construction, toute difference de resultat
vient des regles elles-memes: stops, stop suiveur, prise partielle, carence.

  python scripts/sensibilite_sorties.py
"""

from __future__ import annotations

import sys

import numpy as np

from atlas.backtest.fidele import Parametres, mesures, simuler
from atlas.backtest.pit_data import charger, hasard

DEBUT = "2010-04-01"
VARIANTES = {
    "REELLES (2 / 2,75 / TP 1,5R)": {},
    "sans prise partielle": {"tp_r": None},
    "sans carence": {"carence_jours": 0},
    "stops serres (1,5 / 2)": {"stop_atr": 1.5, "trail_atr": 2.0},
    "stops larges (3 / 4)": {"stop_atr": 3.0, "trail_atr": 4.0},
    "stops tres larges (4 / 6)": {"stop_atr": 4.0, "trail_atr": 6.0},
}


def main() -> None:
    tirages = int(sys.argv[sys.argv.index("--tirages") + 1]) \
        if "--tirages" in sys.argv else 10
    d = charger()
    print(f"selection AU HASARD, 5% de l'indice, {tirages} tirages par variante\n")
    print(f"{'regles de sortie':32}{'CAGR':>8}{'Sharpe':>9}{'+/-':>6}"
          f"{'DD max':>9}{'reussite':>10}{'PF':>6}{'expo':>7}{'trades/an':>11}")
    annees = (d.cal[-1] - d.cal[0]).days / 365.25
    for nom, surcharge in VARIANTES.items():
        p = Parametres.depuis_config(selectivite=0.05, **surcharge)
        ms = [mesures(simuler(d, hasard(d, g), p, debut=DEBUT))
              for g in range(tirages)]
        sh = np.array([m["sharpe"] for m in ms])
        print(f"{nom:32}{100*np.mean([m['cagr'] for m in ms]):+7.1f}%"
              f"{sh.mean():+9.2f}{sh.std():6.2f}"
              f"{100*np.mean([m['drawdown_max'] for m in ms]):8.1f}%"
              f"{100*np.mean([m['reussite'] for m in ms]):9.0f}%"
              f"{np.mean([m['profit_factor'] for m in ms]):6.2f}"
              f"{100*np.mean([m['exposition_moyenne'] for m in ms]):6.0f}%"
              f"{np.mean([m['trades'] for m in ms])/annees:11.0f}")
    print("\n  reference: SPY achete et conserve, Sharpe 0,84 sur la periode.")


if __name__ == "__main__":
    main()
