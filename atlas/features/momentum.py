"""Cross-sectional momentum and relative strength factors."""

from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS = {"1m": 21, "3m": 63, "6m": 126, "12m": 252}


def total_return(close: pd.Series, days: int) -> float:
    if len(close) <= days:
        return np.nan
    return float(close.iloc[-1] / close.iloc[-days - 1] - 1)


def momentum_12_1(close: pd.Series) -> float:
    """Classic 12-1 momentum: 12-month return excluding the last month."""
    if len(close) <= 252:
        return np.nan
    return float(close.iloc[-22] / close.iloc[-253] - 1)


def realized_volatility(close: pd.Series, days: int = 63) -> float:
    rets = close.pct_change().iloc[-days:]
    if rets.dropna().empty:
        return np.nan
    return float(rets.std() * np.sqrt(252))


def relative_strength(close: pd.Series, benchmark: pd.Series, days: int = 126) -> float:
    """Ticker return minus benchmark return over the window."""
    r_t = total_return(close, days)
    r_b = total_return(benchmark, days)
    if np.isnan(r_t) or np.isnan(r_b):
        return np.nan
    return r_t - r_b


def momentum_factors(close: pd.Series, benchmark: pd.Series | None = None) -> dict:
    out = {
        "mom_3m": total_return(close, TRADING_DAYS["3m"]),
        "mom_6m": total_return(close, TRADING_DAYS["6m"]),
        "mom_12m": total_return(close, TRADING_DAYS["12m"]),
        "mom_12_1": momentum_12_1(close),
        "volatility_3m": realized_volatility(close),
    }
    if benchmark is not None and not benchmark.empty:
        out["rel_strength_6m"] = relative_strength(close, benchmark)
    return out


MOMENTUM_DIRECTIONS = {
    "mom_3m": 1, "mom_6m": 1, "mom_12m": 1, "mom_12_1": 1,
    "volatility_3m": -1,         # low volatility factor
    "rel_strength_6m": 1,
}
