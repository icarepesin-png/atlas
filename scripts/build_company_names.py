"""Construit le cache des noms de societes (ticker -> nom complet).

Source rapide et fiable: les tableaux Wikipedia des constituants S&P 500 et
Nasdaq 100 (colonne Security / Company). Complete via Yahoo pour les titres
hors de ces deux indices (echantillon europeen, etc.).

Run: python scripts/build_company_names.py
"""

from __future__ import annotations

import io
import logging

import pandas as pd
import requests

from atlas.data.names import fetch_names_yahoo, load_names, update_names
from atlas.universe.loader import build_universe

log = logging.getLogger(__name__)

WIKI = {
    "sp500": "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
    "nasdaq100": "https://en.wikipedia.org/wiki/Nasdaq-100",
}
HEADERS = {"User-Agent": "Mozilla/5.0 (ATLAS research bot)"}


def _names_from_wikipedia(url: str) -> dict[str, str]:
    resp = requests.get(url, timeout=30, headers=HEADERS)
    resp.raise_for_status()
    tables = pd.read_html(io.StringIO(resp.text))
    for table in tables:
        cols = {str(c).strip().lower(): c for c in table.columns}
        tcol = cols.get("symbol") or cols.get("ticker")
        ncol = cols.get("security") or cols.get("company")
        if tcol is None or ncol is None or len(table) < 80:
            continue
        out = {}
        for _, row in table.iterrows():
            tk = str(row[tcol]).strip().replace(".", "-")
            name = str(row[ncol]).strip()
            if tk and name and tk != "nan":
                out[tk] = name
        return out
    return {}


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    names: dict[str, str] = {}
    for idx, url in WIKI.items():
        try:
            got = _names_from_wikipedia(url)
            log.info("%s: %d noms recuperes depuis Wikipedia", idx, len(got))
            names.update(got)
        except Exception as exc:
            log.warning("scrape noms %s echoue: %s", idx, exc)
    if names:
        update_names(names)

    # Complete les titres de l'univers absents du cache (echantillon europeen)
    universe = build_universe()
    cache = load_names()
    missing = [t for t in universe if t not in cache]
    log.info("complement Yahoo pour %d titres hors S&P/Nasdaq...", len(missing))
    if missing:
        fetched = fetch_names_yahoo(missing, pause_s=0.4)
        update_names(fetched)
        log.info("%d noms ajoutes via Yahoo", len(fetched))

    final = load_names()
    couverts = sum(1 for t in universe if t in final)
    log.info("cache noms: %d entrees, %d/%d titres de l'univers couverts",
             len(final), couverts, len(universe))
    print(f"OK: {len(final)} noms en cache, {couverts}/{len(universe)} couverts")


if __name__ == "__main__":
    main()
