"""Sector rotation engine.

Each sector is proxied by an ETF (config.sectors.etfs). Score 0-100 built from:
- absolute momentum 1m/3m/6m,
- relative strength vs benchmark (SPY),
- trend filter (price above its own 200-day SMA).

Capital flows and analyst revisions need paid data; the hook is `extra_score`
so a provider can be plugged without touching this module.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from atlas.config import get_config
from atlas.features.momentum import total_return

log = logging.getLogger(__name__)


def sector_scores(
    etf_prices: dict[str, pd.DataFrame],
    benchmark: pd.DataFrame,
    extra_score: dict[str, float] | None = None,
) -> pd.DataFrame:
    """Return DataFrame indexed by sector with momentum metrics and score 0-100."""
    cfg = get_config().sectors
    mapping: dict[str, str] = cfg.get("etfs", {})
    bench_close = benchmark["close"] if not benchmark.empty else pd.Series(dtype=float)

    rows = []
    for sector_name, etf in mapping.items():
        df = etf_prices.get(etf, pd.DataFrame())
        if df.empty or len(df) < 130:
            continue
        close = df["close"]
        m1, m3, m6 = total_return(close, 21), total_return(close, 63), total_return(close, 126)
        rs6 = np.nan
        if len(bench_close) > 126:
            rs6 = m6 - total_return(bench_close, 126)
        above_200 = len(close) >= 200 and close.iloc[-1] > close.rolling(200).mean().iloc[-1]
        rows.append({
            "sector": sector_name, "etf": etf, "mom_1m": m1, "mom_3m": m3,
            "mom_6m": m6, "rs_6m": rs6, "above_sma200": above_200,
            "extra": (extra_score or {}).get(sector_name, np.nan),
        })
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows).set_index("sector")

    # Rank-based 0-100 score: average of percentile ranks on momentum + RS
    rank_cols = ["mom_1m", "mom_3m", "mom_6m", "rs_6m"]
    ranks = df[rank_cols].rank(pct=True) * 100
    df["score"] = ranks.mean(axis=1, skipna=True)
    df.loc[df["above_sma200"], "score"] = df.loc[df["above_sma200"], "score"] + 5
    extra = df["extra"].fillna(df["score"])
    df["score"] = (0.85 * df["score"] + 0.15 * extra).clip(0, 100).round(1)
    return df.sort_values("score", ascending=False)


def stock_sector_score(stock_sector: str | None, scores: pd.DataFrame) -> float:
    """Map a stock's sector label (Yahoo naming) to the rotation score."""
    if scores.empty or not stock_sector:
        return 50.0
    aliases = {
        "Technology": "Technology", "Information Technology": "Technology",
        "Healthcare": "Healthcare", "Health Care": "Healthcare",
        "Energy": "Energy", "Utilities": "Utilities",
        "Industrials": "Industrials", "Financial Services": "Financials",
        "Financials": "Financials",
        "Consumer Cyclical": "ConsumerDiscretionary",
        "Consumer Discretionary": "ConsumerDiscretionary",
        "Consumer Defensive": "ConsumerStaples",
        "Consumer Staples": "ConsumerStaples",
        "Basic Materials": "Materials", "Materials": "Materials",
        "Real Estate": "RealEstate",
        "Communication Services": "Communication",
        "Semiconductors": "Semiconductor",
    }
    key = aliases.get(stock_sector, stock_sector)
    if key in scores.index:
        return float(scores.loc[key, "score"])
    return 50.0
