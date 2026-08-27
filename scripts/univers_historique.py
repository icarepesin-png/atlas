# -*- coding: utf-8 -*-
"""Reconstitue l'univers S&P 500 sans biais du survivant.

Recupere la composition de l'indice a chaque trimestre depuis 2010, puis
telecharge les cours des societes qui en sont sorties. Ce sont elles qui
manquaient: 237 titres, un tiers de l'univers reel, dont Bed Bath & Beyond,
Avon ou AK Steel. Leur absence faisait paraitre la volatilite payante et le
momentum inoperant (voir docs/BACKTEST.md).

  python scripts/univers_historique.py            # compositions seules
  python scripts/univers_historique.py --cours    # + telechargement des cours
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import pandas as pd

from atlas.config import get_config
from atlas.data.store import load_ohlcv, save_ohlcv
from atlas.universe.historique import composition_au
from atlas.universe.loader import build_universe

log = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    dates = list(pd.date_range("2010-03-31", "2026-06-30", freq="QE"))
    print(f"{len(dates)} trimestres a reconstituer\n")

    compositions = {}
    for i, d in enumerate(dates, start=1):
        tickers = composition_au(d)
        if tickers:
            compositions[str(d.date())] = tickers
        if i % 20 == 0 or i == len(dates):
            print(f"  {i}/{len(dates)} trimestres")

    elargi = sorted({t for lot in compositions.values() for t in lot})
    actuel = set(build_universe())
    disparus = [t for t in elargi if t not in actuel]

    dossier = Path(get_config().cache_dir) / "univers_historique"
    (dossier / "compositions.json").write_text(
        json.dumps(compositions, indent=1), encoding="utf-8")

    print(f"\n=== univers sans biais du survivant ===")
    print(f"  titres ayant appartenu a l'indice : {len(elargi)}")
    print(f"  dont absents de l'univers actuel  : {len(disparus)}"
          f" ({100*len(disparus)/len(elargi):.0f}%)")
    tailles = [len(v) for v in compositions.values()]
    print(f"  taille de l'indice: {min(tailles)} a {max(tailles)} membres")

    if "--cours" not in sys.argv:
        print("\n  Relancer avec --cours pour telecharger les series manquantes.")
        return

    from atlas.data.yahoo import YahooProvider
    provider = YahooProvider()
    manquants = [t for t in disparus if load_ohlcv(t).empty]
    print(f"\n{len(manquants)} series a telecharger (les autres sont en cache)")
    obtenus, absents = 0, []
    for debut in range(0, len(manquants), 40):
        lot = manquants[debut:debut + 40]
        try:
            frames = provider.get_ohlcv_batch(lot, start="2008-01-01")
        except Exception as exc:  # noqa: BLE001
            log.warning("lot en echec: %s", exc)
            continue
        for t in lot:
            df = frames.get(t, pd.DataFrame())
            if df is not None and not df.empty:
                save_ohlcv(t, df)
                obtenus += 1
            else:
                absents.append(t)
        print(f"  {min(debut + 40, len(manquants))}/{len(manquants)}"
              f" traites, {obtenus} series obtenues")

    print(f"\n  {obtenus} series recuperees, {len(absents)} introuvables")
    if absents:
        print(f"  introuvables chez Yahoo: {absents[:20]}")
        print("  (radiations anciennes: Yahoo ne conserve pas tout)")


if __name__ == "__main__":
    main()
