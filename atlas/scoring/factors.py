"""Cross-sectional factor processing: winsorize, z-score, percentile ranks.

Input: DataFrame index=ticker, columns=raw factor values.
Output: 0-100 scores per factor and aggregated per style group.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from atlas.config import get_config


def winsorize(s: pd.Series, pct: float) -> pd.Series:
    if s.dropna().empty:
        return s
    lo, hi = s.quantile(pct), s.quantile(1 - pct)
    return s.clip(lo, hi)


def zscore(s: pd.Series) -> pd.Series:
    sd = s.std()
    if not sd or np.isnan(sd):
        return pd.Series(0.0, index=s.index)
    return (s - s.mean()) / sd


def factor_scores(
    raw: pd.DataFrame,
    directions: dict[str, int],
    sector_col: str = "sector_name",
) -> pd.DataFrame:
    """Convert raw factor values to 0-100 cross-sectional percentile scores.

    If config scoring.sector_neutral and a sector column exists, ranks are
    computed within each sector (a cheap stock is cheap vs its peers).
    Missing values get the neutral score 50.
    """
    cfg = get_config().scoring
    pct = float(cfg.get("winsorize_pct", 0.02))
    sector_neutral = bool(cfg.get("sector_neutral", True)) and sector_col in raw.columns

    out = pd.DataFrame(index=raw.index)
    for col, direction in directions.items():
        if col not in raw.columns:
            continue
        s = pd.to_numeric(raw[col], errors="coerce") * direction
        s = winsorize(s, pct)
        if sector_neutral:
            ranks = s.groupby(raw[sector_col].fillna("Unknown")).rank(pct=True)
            # Single-stock sectors rank at 1.0 artificially -> blend with global rank
            global_ranks = s.rank(pct=True)
            ranks = 0.6 * ranks + 0.4 * global_ranks
        else:
            ranks = s.rank(pct=True)
        out[col] = (ranks * 100).fillna(50.0)
    return out


def group_score(scores: pd.DataFrame, columns: list[str]) -> pd.Series:
    """Average of available factor scores in a group (NaN-tolerant)."""
    cols = [c for c in columns if c in scores.columns]
    if not cols:
        return pd.Series(50.0, index=scores.index)
    return scores[cols].mean(axis=1, skipna=True).fillna(50.0)
