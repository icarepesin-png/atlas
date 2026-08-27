# -*- coding: utf-8 -*-
"""Telecharge les fondamentaux point-in-time de l'univers depuis SEC EDGAR.

Constitue la base qui manquait au projet: chaque chiffre comptable accompagne
de sa DATE DE DEPOT, seule facon de reconstituer ce qu'on savait a une date
donnee et donc de backtester honnetement le pilier fondamental (70% du score
depuis le 2026-08-27).

Couverture attendue: ~92% de l'univers. EDGAR ne couvre que les emetteurs
enregistres aupres de la SEC, donc les 40 titres europeens (Londres, Paris,
Francfort, Zurich, Milan, Madrid, Amsterdam, Copenhague) resteront sans
donnees - c'est une limite du gisement, pas un bug.

Le script est REPRENABLE: relance apres interruption, il saute ce qui est
deja en cache. Compter environ 15 minutes pour l'univers complet, en se
tenant sous la limite de debit de la SEC.

  python scripts/moisson_edgar.py                 # univers complet
  python scripts/moisson_edgar.py --limite 20     # essai rapide
  python scripts/moisson_edgar.py --forcer        # ignore le cache
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

import pandas as pd

from atlas.config import PROJECT_ROOT, get_config
from atlas.data.edgar import (SecUserAgentManquant, cik_de, extraire,
                              faits_bruts)
from atlas.universe.loader import build_universe

log = logging.getLogger(__name__)
SORTIE = "faits_edgar.parquet"


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    limite = None
    if "--limite" in sys.argv:
        limite = int(sys.argv[sys.argv.index("--limite") + 1])
    max_age = 0 if "--forcer" in sys.argv else 30

    univers = build_universe()[:limite] if limite else build_universe()
    dossier = Path(get_config().cache_dir) / "edgar"
    dossier.mkdir(parents=True, exist_ok=True)
    chemin = dossier / SORTIE

    try:
        from atlas.data.edgar import entetes
        entetes()
    except SecUserAgentManquant as exc:
        print(exc)
        raise SystemExit(1)

    lots: list[pd.DataFrame] = []
    hors_sec, vides, echecs = [], [], []
    depart = time.time()

    for i, ticker in enumerate(univers, start=1):
        cik = cik_de(ticker)
        if cik is None:
            hors_sec.append(ticker)
            continue
        try:
            df = extraire(faits_bruts(cik, max_age_days=max_age), ticker)
        except SecUserAgentManquant as exc:
            print(f"\nARRET: {exc}")
            break
        except Exception as exc:  # noqa: BLE001
            echecs.append((ticker, type(exc).__name__))
            continue
        if df.empty:
            vides.append(ticker)
        else:
            lots.append(df)
        if i % 25 == 0 or i == len(univers):
            ecoule = time.time() - depart
            reste = (len(univers) - i) * ecoule / max(i, 1)
            print(f"  {i:4d}/{len(univers)}  {len(lots)} societes utiles  "
                  f"{ecoule/60:.1f} min ecoulees, ~{reste/60:.1f} min restantes")

    if not lots:
        print("aucune donnee recuperee")
        raise SystemExit(1)

    faits = pd.concat(lots, ignore_index=True)
    faits.to_parquet(chemin)

    print(f"\n=== {len(faits):,} faits pour {faits.ticker.nunique()} societes ===")
    print(f"  fichier      : {chemin.relative_to(PROJECT_ROOT)}"
          f" ({chemin.stat().st_size / 1024**2:.1f} Mo)")
    print(f"  periode      : {faits.fin.min().date()} -> {faits.fin.max().date()}")
    print(f"  hors SEC     : {len(hors_sec)} titres (europeens: attendu)")
    if vides:
        print(f"  sans concepts: {len(vides)} ({', '.join(vides[:8])})")
    if echecs:
        print(f"  echecs       : {len(echecs)} ({echecs[:5]})")
    print(f"  duree        : {(time.time() - depart)/60:.1f} min")

    couverture = faits.groupby("grandeur").ticker.nunique().sort_values()
    print("\n  couverture par grandeur (societes):")
    for grandeur, n in couverture.items():
        print(f"    {grandeur:22} {n:4d}")


if __name__ == "__main__":
    main()
