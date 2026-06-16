"""Recherche du nom complet d'une societe a partir de son ticker.

Cache persistant (parquet) : un ticker -> nom complet. Les noms changent
rarement, donc le cache n'expire pas. Rempli en masse depuis Wikipedia
(noms des constituants S&P 500 / Nasdaq 100) et complete via Yahoo pour le
reste. Lecture cote dashboard : instantanee, repli sur le ticker si absent.
"""

from __future__ import annotations

import logging

import pandas as pd

from atlas.config import PROJECT_ROOT

log = logging.getLogger(__name__)


def _cache_file():
    # config/ est versionne (commit), donc le cache des noms est disponible
    # sur l'hebergement cloud du dashboard. data/cache/ est ignore par git.
    path = PROJECT_ROOT / "config" / "company_names.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def load_names() -> dict[str, str]:
    try:
        df = pd.read_parquet(_cache_file())
        return dict(zip(df["ticker"].astype(str), df["name"].astype(str)))
    except (FileNotFoundError, OSError, KeyError):
        return {}


def save_names(mapping: dict[str, str]) -> None:
    if not mapping:
        return
    df = pd.DataFrame({"ticker": list(mapping), "name": list(mapping.values())})
    df.to_parquet(_cache_file(), index=False)


def update_names(new: dict[str, str]) -> dict[str, str]:
    """Fusionne de nouveaux noms dans le cache et le sauvegarde."""
    merged = load_names()
    merged.update({k: v for k, v in new.items() if v and str(v).strip()})
    save_names(merged)
    return merged


def get_company_names(tickers) -> dict[str, str]:
    """Lecture cache uniquement: {ticker: nom complet ou ticker en repli}."""
    cache = load_names()
    return {t: cache.get(t, t) for t in tickers}


def fetch_names_yahoo(tickers, pause_s: float = 0.3) -> dict[str, str]:
    """Recupere les noms manquants via Yahoo (.info longName/shortName)."""
    import time

    import yfinance as yf

    out: dict[str, str] = {}
    for t in tickers:
        try:
            info = yf.Ticker(t).info or {}
            name = info.get("longName") or info.get("shortName")
            if name:
                out[t] = str(name)
        except Exception as exc:
            log.debug("nom indisponible pour %s: %s", t, exc)
        if pause_s:
            time.sleep(pause_s)
    return out


def ensure_names(tickers, max_yahoo: int = 60) -> dict[str, str]:
    """Garantit un nom pour chaque ticker: cache d'abord, Yahoo pour les
    manquants (plafonne pour rester rapide la nuit). Retourne le mapping
    complet (avec repli ticker)."""
    cache = load_names()
    missing = [t for t in tickers if t not in cache][:max_yahoo]
    if missing:
        fetched = fetch_names_yahoo(missing)
        if fetched:
            cache = update_names(fetched)
    return {t: cache.get(t, t) for t in tickers}
