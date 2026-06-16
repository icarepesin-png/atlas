"""Performance metrics: CAGR, Sharpe, Sortino, Calmar, MaxDD, Ulcer,
Profit Factor, alpha/beta vs benchmark."""

from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def cagr(equity: pd.Series) -> float:
    if len(equity) < 2 or equity.iloc[0] <= 0:
        return np.nan
    years = (equity.index[-1] - equity.index[0]).days / 365.25
    if years <= 0:
        return np.nan
    return float((equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1)


def sharpe(returns: pd.Series, rf_annual: float = 0.02) -> float:
    r = returns.dropna()
    if r.std() == 0 or r.empty:
        return np.nan
    excess = r - rf_annual / TRADING_DAYS
    return float(excess.mean() / r.std() * np.sqrt(TRADING_DAYS))


def sortino(returns: pd.Series, rf_annual: float = 0.02) -> float:
    r = returns.dropna()
    downside = r[r < 0].std()
    if not downside or np.isnan(downside) or r.empty:
        return np.nan
    excess = r - rf_annual / TRADING_DAYS
    return float(excess.mean() / downside * np.sqrt(TRADING_DAYS))


def max_drawdown(equity: pd.Series) -> float:
    if equity.empty:
        return np.nan
    dd = 1 - equity / equity.cummax()
    return float(dd.max())


def calmar(equity: pd.Series) -> float:
    mdd = max_drawdown(equity)
    if not mdd or np.isnan(mdd):
        return np.nan
    return float(cagr(equity) / mdd)


def ulcer_index(equity: pd.Series) -> float:
    if equity.empty:
        return np.nan
    dd_pct = (1 - equity / equity.cummax()) * 100
    return float(np.sqrt((dd_pct ** 2).mean()))


def profit_factor(trade_pnls: pd.Series) -> float:
    gains = trade_pnls[trade_pnls > 0].sum()
    losses = -trade_pnls[trade_pnls < 0].sum()
    if losses == 0:
        return np.nan
    return float(gains / losses)


def alpha_beta(returns: pd.Series, bench_returns: pd.Series,
               rf_annual: float = 0.02) -> tuple[float, float]:
    df = pd.concat([returns, bench_returns], axis=1, keys=["s", "b"]).dropna()
    if len(df) < 60:
        return np.nan, np.nan
    rf_d = rf_annual / TRADING_DAYS
    cov = np.cov(df["s"] - rf_d, df["b"] - rf_d)
    beta = float(cov[0, 1] / cov[1, 1]) if cov[1, 1] else np.nan
    alpha_d = (df["s"] - rf_d).mean() - beta * (df["b"] - rf_d).mean()
    return float(alpha_d * TRADING_DAYS), beta


def full_report(equity: pd.Series, bench_equity: pd.Series | None = None,
                trade_pnls: pd.Series | None = None) -> dict:
    rets = equity.pct_change().dropna()
    out = {
        "cagr": cagr(equity),
        "sharpe": sharpe(rets),
        "sortino": sortino(rets),
        "calmar": calmar(equity),
        "max_drawdown": max_drawdown(equity),
        "ulcer_index": ulcer_index(equity),
        "volatility": float(rets.std() * np.sqrt(TRADING_DAYS)) if len(rets) else np.nan,
        "total_return": float(equity.iloc[-1] / equity.iloc[0] - 1) if len(equity) > 1 else np.nan,
        "n_days": len(equity),
    }
    if bench_equity is not None and not bench_equity.empty:
        a, b = alpha_beta(rets, bench_equity.pct_change().dropna())
        out["alpha"] = a
        out["beta"] = b
    if trade_pnls is not None and not trade_pnls.empty:
        out["profit_factor"] = profit_factor(trade_pnls)
        out["win_rate"] = float((trade_pnls > 0).mean())
        out["n_trades"] = int(len(trade_pnls))
    return {k: (round(v, 4) if isinstance(v, float) and not np.isnan(v) else v)
            for k, v in out.items()}
