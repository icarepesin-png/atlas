"""Investment universe construction.

MVP sources:
- S&P 500 / Nasdaq 100: scraped from Wikipedia (cached locally as CSV).
- STOXX 600 sample / other indices: static CSV under config/universe/.

Production path (10k+ tickers): replace with index constituents from
Polygon reference API or a licensed constituents feed, including HISTORICAL
membership to kill survivorship bias (see docs/BACKTEST.md).
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from atlas.config import PROJECT_ROOT, get_config

log = logging.getLogger(__name__)

UNIVERSE_DIR = PROJECT_ROOT / "config" / "universe"

_WIKI_SOURCES = {
    "sp500": ("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", 400),
    "nasdaq100": ("https://en.wikipedia.org/wiki/Nasdaq-100", 80),
}


def _load_from_wikipedia(index_name: str) -> list[str]:
    import io

    import requests

    url, min_rows = _WIKI_SOURCES[index_name]
    # Wikipedia rejette le User-Agent par defaut de pandas/urllib (403)
    resp = requests.get(url, timeout=30,
                        headers={"User-Agent": "Mozilla/5.0 (ATLAS research bot)"})
    resp.raise_for_status()
    tables = pd.read_html(io.StringIO(resp.text))
    # La position des tables change avec les editions de la page: on prend la
    # premiere table assez grande qui contient une colonne Symbol/Ticker.
    for table in tables:
        cols = {str(c).strip().lower(): c for c in table.columns}
        col = cols.get("symbol") or cols.get("ticker")
        if col is None or len(table) < min_rows:
            continue
        tickers = (
            table[col].astype(str).str.strip()
            .str.replace(".", "-", regex=False).tolist()
        )
        return sorted({t for t in tickers if t and t != "nan"})
    raise ValueError(f"table de constituants introuvable pour {index_name}")


def _csv_path(index_name: str) -> Path:
    return UNIVERSE_DIR / f"{index_name}.csv"


def load_index(index_name: str, refresh: bool = False) -> list[str]:
    """Load constituents for one index, cache-first."""
    path = _csv_path(index_name)
    if path.exists() and not refresh:
        return pd.read_csv(path)["ticker"].dropna().astype(str).tolist()
    if index_name in _WIKI_SOURCES:
        try:
            tickers = _load_from_wikipedia(index_name)
            UNIVERSE_DIR.mkdir(parents=True, exist_ok=True)
            pd.DataFrame({"ticker": tickers}).to_csv(path, index=False)
            return tickers
        except Exception as exc:
            log.warning("scrape %s failed: %s", index_name, exc)
    if path.exists():
        return pd.read_csv(path)["ticker"].dropna().astype(str).tolist()
    log.warning("aucune source pour l'indice %s (fichier %s absent)", index_name, path)
    return []


def build_universe(refresh: bool = False) -> list[str]:
    """Union of all configured indices, capped at universe.max_tickers."""
    cfg = get_config().universe
    tickers: set[str] = set()
    for idx in cfg.get("indices", ["sp500"]):
        tickers.update(load_index(idx, refresh=refresh))
    cap = int(cfg.get("max_tickers", 1500))
    out = sorted(tickers)[:cap]
    log.info("univers: %d tickers (cap %d)", len(out), cap)
    return out


def filter_liquidity(prices: dict[str, pd.DataFrame],
                     fx_rates: dict[str, float] | None = None) -> list[str]:
    """Keep tickers passing min price and min average dollar volume (20d).

    Les montants sont convertis en USD selon la devise de cotation: sans
    conversion, un titre londonien cote en pence gonflerait son volume
    en dollars d'un facteur 100.
    """
    from atlas.data.fx import currency_of, get_usd_rates, to_usd

    cfg = get_config().universe
    min_dv = float(cfg.get("min_dollar_volume", 5e6))
    min_price = float(cfg.get("min_price", 3.0))
    rates = fx_rates if fx_rates is not None else get_usd_rates()
    keep = []
    for t, df in prices.items():
        if df.empty or len(df) < 20:
            continue
        cur = currency_of(t)
        last = df.iloc[-20:]
        dollar_volume = to_usd(float((last["close"] * last["volume"]).mean()),
                               cur, rates)
        last_price_usd = to_usd(float(last["close"].iloc[-1]), cur, rates)
        if dollar_volume >= min_dv and last_price_usd >= min_price:
            keep.append(t)
    return keep
