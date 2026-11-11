# -*- coding: utf-8 -*-
"""Recalcule la courbe d'equity de toutes les campagnes.

La logique vit dans atlas/pipelines/equity_recalc.py et tourne a la fin de
chaque run; ce script permet de la relancer a la main.

  python scripts/recalculer_equity.py
"""

import logging

from atlas.pipelines.equity_recalc import run

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    for cle, valeur in run().items():
        print(f"{cle}: {valeur}")
