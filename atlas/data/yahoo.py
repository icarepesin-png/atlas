"""Yahoo Finance provider (MVP / fallback). Free, no key, rate-limited.

Good enough for: daily OHLCV on ~1500 tickers, snapshot fundamentals.
Not good enough for: 10k+ tickers, tick data, point-in-time fundamentals.
"""

from __future__ import annotations

import logging
import time
from datetime import date

import pandas as pd
import yfinance as yf

from atlas.data.base import normalize_ohlcv

log = logging.getLogger(__name__)

# yfinance .info keys -> canonical ATLAS field names
_INFO_FIELDS = {
    "returnOnEquity": "roe",
    "returnOnAssets": "roa",
    "grossMargins": "gross_margin",
    "operatingMargins": "operating_margin",
    "profitMargins": "net_margin",
    "revenueGrowth": "revenue_growth",
    "earningsGrowth": "eps_growth",
    "trailingPE": "pe",
    "forwardPE": "forward_pe",
    "enterpriseToEbitda": "ev_ebitda",
    "priceToSalesTrailing12Months": "ps",
    "pegRatio": "peg",
    "freeCashflow": "fcf",
    "marketCap": "market_cap",
    "enterpriseValue": "enterprise_value",
    "totalDebt": "total_debt",
    "totalCash": "total_cash",
    "sharesOutstanding": "shares_outstanding",
    "sector": "sector",
    "industry": "industry",
    "country": "country",
    "currency": "currency",
}


class YahooProvider:
    name = "yahoo"

    def __init__(self, pause_s: float = 0.0) -> None:
        self.pause_s = pause_s

    def get_ohlcv(
        self,
        ticker: str,
        start: date | str | None = None,
        end: date | str | None = None,
        interval: str = "1d",
    ) -> pd.DataFrame:
        try:
            df = yf.Ticker(ticker).history(
                start=start, end=end, interval=interval, auto_adjust=True
            )
        except Exception as exc:  # network / delisted / bad ticker
            log.warning("yahoo ohlcv failed for %s: %s", ticker, exc)
            return pd.DataFrame()
        return normalize_ohlcv(df)

    def get_ohlcv_batch(
        self,
        tickers: list[str],
        start: date | str | None = None,
        end: date | str | None = None,
        interval: str = "1d",
    ) -> dict[str, pd.DataFrame]:
        out: dict[str, pd.DataFrame] = {}
        # yf.download supporte le multi-ticker en une requete (group_by="ticker")
        chunk_size = 100
        for i in range(0, len(tickers), chunk_size):
            chunk = tickers[i : i + chunk_size]
            try:
                raw = yf.download(
                    chunk,
                    start=start,
                    end=end,
                    interval=interval,
                    group_by="ticker",
                    auto_adjust=True,
                    progress=False,
                    threads=True,
                )
            except Exception as exc:
                log.warning("yahoo batch failed (%d tickers): %s", len(chunk), exc)
                continue
            for t in chunk:
                try:
                    df = raw[t] if len(chunk) > 1 else raw
                    out[t] = normalize_ohlcv(df.dropna(how="all"))
                except (KeyError, TypeError):
                    out[t] = pd.DataFrame()
            if self.pause_s:
                time.sleep(self.pause_s)
        return out

    # -- Fundamentals (snapshot, NOT point-in-time) ---------------------------

    def get_fundamentals(self, ticker: str) -> dict:
        """Snapshot ratios + raw statements needed by F/Z/M scores."""
        tk = yf.Ticker(ticker)
        out: dict = {"ticker": ticker}
        try:
            info = tk.info or {}
        except Exception as exc:
            log.warning("yahoo info failed for %s: %s", ticker, exc)
            info = {}
        for src, dst in _INFO_FIELDS.items():
            out[dst] = info.get(src)
        # ROIC approx: EBIT * (1 - tax) / (debt + equity). Computed downstream
        # from statements; keep raw statements for Piotroski/Altman/Beneish.
        try:
            out["income_stmt"] = tk.financials          # annual income statement
            out["balance_sheet"] = tk.balance_sheet
            out["cash_flow"] = tk.cashflow
        except Exception as exc:
            log.warning("yahoo statements failed for %s: %s", ticker, exc)
        return out
