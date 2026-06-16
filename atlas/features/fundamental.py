"""Fundamental factors: profitability, growth, valuation, quality scores.

Inputs: dict produced by a FundamentalsProvider (ratios + raw statements).
All computations are NaN-tolerant: missing inputs yield NaN, never crash.

NOTE BIAIS: avec Yahoo, les fondamentaux sont un snapshot courant. Pour le
backtest, seuls les facteurs prix (momentum/technique) sont point-in-time.
Voir docs/BACKTEST.md pour brancher une source as-reported (FMP, EDGAR).
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd


def _row(df: pd.DataFrame | None, label: str, col: int = 0) -> float:
    """Fetch one cell from a yfinance statement (rows=items, cols=periods)."""
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return np.nan
    if label not in df.index or col >= df.shape[1]:
        return np.nan
    try:
        v = float(df.loc[label].iloc[col])
        return v if math.isfinite(v) else np.nan
    except (TypeError, ValueError):
        return np.nan


def _safe_div(a: float, b: float) -> float:
    if a is None or b is None or not math.isfinite(a or np.nan) or not b:
        return np.nan
    try:
        return a / b
    except ZeroDivisionError:
        return np.nan


# -- ROIC ----------------------------------------------------------------------

def roic(f: dict) -> float:
    """EBIT * (1 - effective tax) / invested capital (debt + equity)."""
    inc, bs = f.get("income_stmt"), f.get("balance_sheet")
    ebit = _row(inc, "EBIT")
    if np.isnan(ebit):
        ebit = _row(inc, "Operating Income")
    pretax = _row(inc, "Pretax Income")
    tax = _row(inc, "Tax Provision")
    tax_rate = _safe_div(tax, pretax)
    tax_rate = tax_rate if not np.isnan(tax_rate) and 0 <= tax_rate < 0.6 else 0.21
    equity = _row(bs, "Stockholders Equity")
    debt = _row(bs, "Total Debt")
    if np.isnan(debt):
        debt = (_row(bs, "Long Term Debt") or 0) + (_row(bs, "Current Debt") or 0)
    invested = (equity if not np.isnan(equity) else 0) + (debt if not np.isnan(debt) else 0)
    return _safe_div(ebit * (1 - tax_rate), invested)


# -- Piotroski F-Score (0-9) ----------------------------------------------------

def piotroski_f(f: dict) -> float:
    inc, bs, cf = f.get("income_stmt"), f.get("balance_sheet"), f.get("cash_flow")

    ni0, ni1 = _row(inc, "Net Income", 0), _row(inc, "Net Income", 1)
    ta0, ta1 = _row(bs, "Total Assets", 0), _row(bs, "Total Assets", 1)
    ta2 = _row(bs, "Total Assets", 2)
    cfo = _row(cf, "Operating Cash Flow")
    ltd0, ltd1 = _row(bs, "Long Term Debt", 0), _row(bs, "Long Term Debt", 1)
    ca0, ca1 = _row(bs, "Current Assets", 0), _row(bs, "Current Assets", 1)
    cl0, cl1 = _row(bs, "Current Liabilities", 0), _row(bs, "Current Liabilities", 1)
    sh0, sh1 = _row(bs, "Ordinary Shares Number", 0), _row(bs, "Ordinary Shares Number", 1)
    gp0, gp1 = _row(inc, "Gross Profit", 0), _row(inc, "Gross Profit", 1)
    rev0, rev1 = _row(inc, "Total Revenue", 0), _row(inc, "Total Revenue", 1)

    roa0 = _safe_div(ni0, ta0)
    roa1 = _safe_div(ni1, ta1)
    checks = [
        roa0 > 0,                                            # 1 ROA positif
        _safe_div(cfo, ta0) > 0,                             # 2 CFO positif
        roa0 > roa1,                                         # 3 ROA en hausse
        cfo > ni0,                                           # 4 accruals (CFO > NI)
        _safe_div(ltd0, ta0) < _safe_div(ltd1, ta1 if not np.isnan(ta1) else ta2),  # 5 levier en baisse
        _safe_div(ca0, cl0) > _safe_div(ca1, cl1),           # 6 current ratio en hausse
        not (sh0 > sh1 * 1.02),                              # 7 pas de dilution (>2%)
        _safe_div(gp0, rev0) > _safe_div(gp1, rev1),         # 8 marge brute en hausse
        _safe_div(rev0, ta0) > _safe_div(rev1, ta1),         # 9 rotation actifs en hausse
    ]
    valid = [c for c in checks if isinstance(c, (bool, np.bool_))]
    if len(valid) < 5:  # trop de donnees manquantes pour un score fiable
        return np.nan
    return float(sum(bool(c) for c in valid))


# -- Altman Z-Score --------------------------------------------------------------

def altman_z(f: dict) -> float:
    inc, bs = f.get("income_stmt"), f.get("balance_sheet")
    ta = _row(bs, "Total Assets")
    if np.isnan(ta) or ta <= 0:
        return np.nan
    wc = _row(bs, "Working Capital")
    if np.isnan(wc):
        wc = _row(bs, "Current Assets") - _row(bs, "Current Liabilities")
    re = _row(bs, "Retained Earnings")
    ebit = _row(inc, "EBIT")
    if np.isnan(ebit):
        ebit = _row(inc, "Operating Income")
    tl = _row(bs, "Total Liabilities Net Minority Interest")
    mve = f.get("market_cap") or np.nan
    sales = _row(inc, "Total Revenue")
    z = (
        1.2 * _safe_div(wc, ta) + 1.4 * _safe_div(re, ta) + 3.3 * _safe_div(ebit, ta)
        + 0.6 * _safe_div(mve, tl) + 1.0 * _safe_div(sales, ta)
    )
    return float(z) if math.isfinite(z) else np.nan


# -- Beneish M-Score (manipulation earnings) --------------------------------------

def beneish_m(f: dict) -> float:
    """M-Score > -1.78 suggests possible earnings manipulation."""
    inc, bs, cf = f.get("income_stmt"), f.get("balance_sheet"), f.get("cash_flow")

    def yr(df, label, i):
        return _row(df, label, i)

    rec0, rec1 = yr(bs, "Accounts Receivable", 0), yr(bs, "Accounts Receivable", 1)
    rev0, rev1 = yr(inc, "Total Revenue", 0), yr(inc, "Total Revenue", 1)
    gp0, gp1 = yr(inc, "Gross Profit", 0), yr(inc, "Gross Profit", 1)
    ca0, ca1 = yr(bs, "Current Assets", 0), yr(bs, "Current Assets", 1)
    ppe0, ppe1 = yr(bs, "Net PPE", 0), yr(bs, "Net PPE", 1)
    ta0, ta1 = yr(bs, "Total Assets", 0), yr(bs, "Total Assets", 1)
    dep0, dep1 = yr(cf, "Depreciation And Amortization", 0), yr(cf, "Depreciation And Amortization", 1)
    sga0, sga1 = yr(inc, "Selling General And Administration", 0), yr(inc, "Selling General And Administration", 1)
    ni0 = yr(inc, "Net Income", 0)
    cfo0 = yr(cf, "Operating Cash Flow", 0)
    tl0, tl1 = yr(bs, "Total Liabilities Net Minority Interest", 0), yr(bs, "Total Liabilities Net Minority Interest", 1)

    dsri = _safe_div(_safe_div(rec0, rev0), _safe_div(rec1, rev1))
    gmi = _safe_div(_safe_div(gp1, rev1), _safe_div(gp0, rev0))
    aqi = _safe_div(1 - _safe_div(ca0 + ppe0, ta0), 1 - _safe_div(ca1 + ppe1, ta1))
    sgi = _safe_div(rev0, rev1)
    depi = _safe_div(_safe_div(dep1, dep1 + ppe1), _safe_div(dep0, dep0 + ppe0))
    sgai = _safe_div(_safe_div(sga0, rev0), _safe_div(sga1, rev1))
    tata = _safe_div(ni0 - cfo0, ta0)
    lvgi = _safe_div(_safe_div(tl0, ta0), _safe_div(tl1, ta1))

    parts = {
        "dsri": (0.920, dsri), "gmi": (0.528, gmi), "aqi": (0.404, aqi),
        "sgi": (0.892, sgi), "depi": (0.115, depi), "sgai": (-0.172, sgai),
        "tata": (4.679, tata), "lvgi": (-0.327, lvgi),
    }
    valid = {k: (w, v) for k, (w, v) in parts.items() if not np.isnan(v)}
    if len(valid) < 5:
        return np.nan
    m = -4.84 + sum(w * v for w, v in valid.values())
    return float(m)


# -- Flat factor extraction --------------------------------------------------------

def fundamental_factors(f: dict) -> dict:
    """Flatten one company's fundamentals into the factor row used by scoring."""
    fcf = f.get("fcf")
    mcap = f.get("market_cap")
    return {
        "ticker": f.get("ticker"),
        "sector_name": f.get("sector"),
        "country": f.get("country"),
        # Profitability
        "roe": f.get("roe"), "roa": f.get("roa"), "roic": roic(f),
        "gross_margin": f.get("gross_margin"),
        "operating_margin": f.get("operating_margin"),
        "net_margin": f.get("net_margin"),
        # Growth
        "revenue_growth": f.get("revenue_growth"),
        "eps_growth": f.get("eps_growth"),
        # Quality
        "piotroski_f": piotroski_f(f),
        "altman_z": altman_z(f),
        "beneish_m": beneish_m(f),
        # Valuation (lower is better -> inverted in scoring)
        "pe": f.get("pe"), "forward_pe": f.get("forward_pe"),
        "ev_ebitda": f.get("ev_ebitda"), "ps": f.get("ps"), "peg": f.get("peg"),
        "fcf_yield": _safe_div(fcf, mcap),
        "market_cap": mcap,
    }


# Direction de chaque facteur: +1 = plus haut est mieux, -1 = plus bas est mieux
FACTOR_DIRECTIONS = {
    "roe": 1, "roa": 1, "roic": 1, "gross_margin": 1, "operating_margin": 1,
    "net_margin": 1, "revenue_growth": 1, "eps_growth": 1,
    "piotroski_f": 1, "altman_z": 1, "beneish_m": -1,
    "pe": -1, "forward_pe": -1, "ev_ebitda": -1, "ps": -1, "peg": -1,
    "fcf_yield": 1,
}

# Regroupement par style pour le reporting facteur
FACTOR_GROUPS = {
    "quality": ["roe", "roa", "roic", "gross_margin", "operating_margin",
                "net_margin", "piotroski_f", "altman_z", "beneish_m"],
    "growth": ["revenue_growth", "eps_growth"],
    "value": ["pe", "forward_pe", "ev_ebitda", "ps", "peg", "fcf_yield"],
}
