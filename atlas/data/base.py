"""Provider-agnostic data interfaces.

Every market data source (Yahoo, Polygon, Databento, IBKR...) implements
MarketDataProvider so the rest of the platform never depends on a vendor.
"""

from __future__ import annotations

from datetime import date
from typing import Protocol, runtime_checkable

import pandas as pd

# Canonical OHLCV columns used everywhere downstream.
OHLCV_COLUMNS = ["open", "high", "low", "close", "volume"]


@runtime_checkable
class MarketDataProvider(Protocol):
    """Daily (or intraday) price history, normalized to OHLCV_COLUMNS."""

    name: str

    def get_ohlcv(
        self,
        ticker: str,
        start: date | str | None = None,
        end: date | str | None = None,
        interval: str = "1d",
    ) -> pd.DataFrame:
        """Return DataFrame indexed by timestamp with OHLCV_COLUMNS. Empty df if no data."""
        ...

    def get_ohlcv_batch(
        self,
        tickers: list[str],
        start: date | str | None = None,
        end: date | str | None = None,
        interval: str = "1d",
    ) -> dict[str, pd.DataFrame]:
        ...


@runtime_checkable
class FundamentalsProvider(Protocol):
    """Point-in-time fundamentals. MVP: latest snapshot (Yahoo).

    WARNING: snapshot fundamentals introduce look-ahead bias in backtests.
    For institutional-grade backtests, plug a point-in-time source
    (FMP as-reported, SEC EDGAR with filing dates, FactSet).
    """

    name: str

    def get_fundamentals(self, ticker: str) -> dict:
        """Flat dict of fundamental fields (see atlas/features/fundamental.py)."""
        ...


def normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """Lower-case columns, keep canonical set, drop all-NaN rows, sort index."""
    if df is None or df.empty:
        return pd.DataFrame(columns=OHLCV_COLUMNS)
    out = df.copy()
    out.columns = [str(c).lower().replace(" ", "_") for c in out.columns]
    if "adj_close" in out.columns and "close" in out.columns:
        # Use adjusted prices for research consistency (splits/dividends).
        ratio = out["adj_close"] / out["close"]
        for col in ("open", "high", "low", "close"):
            if col in out.columns:
                out[col] = out[col] * ratio
    cols = [c for c in OHLCV_COLUMNS if c in out.columns]
    out = out[cols].dropna(how="all").sort_index()
    out.index = pd.to_datetime(out.index).tz_localize(None)
    return out
