"""Backtest engine: periodic-rebalance portfolio simulation with costs.

Design choices against the classic biases:
- NO look-ahead: weights decided at rebalance date t use data up to t only;
  execution happens at the NEXT day's open (t+1).
- Costs: commission + slippage + half-spread on every traded notional.
- Survivorship: depends on the universe feed. With Yahoo + current
  constituents the bias EXISTS and is documented (docs/BACKTEST.md);
  historical-constituents feed required for production claims.
- Data snooping / overfitting: walk-forward + Monte Carlo in validation.py.

The strategy is injected as a callable, keeping the engine generic:
    strategy(prices_up_to_t: dict[str, pd.DataFrame], date: pd.Timestamp) -> weights
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pandas as pd

from atlas.config import get_config

log = logging.getLogger(__name__)

StrategyFn = Callable[[pd.DataFrame, pd.Timestamp], pd.Series]


@dataclass
class BacktestResult:
    equity: pd.Series
    weights_history: pd.DataFrame
    trades: pd.DataFrame
    costs_paid: float
    params: dict = field(default_factory=dict)
    days_derisked: int = 0
    min_exposure: float = 1.0


def _derisk_multiplier(drawdown: float, steps: list[dict]) -> float:
    """Gross exposure target for a given drawdown (risk overlay steps)."""
    for step in sorted(steps, key=lambda s: float(s["drawdown"]), reverse=True):
        if drawdown >= float(step["drawdown"]):
            return float(step["gross_exposure"])
    return 1.0


def _rebalance_dates(index: pd.DatetimeIndex, freq: str) -> pd.DatetimeIndex:
    if freq == "daily":
        return index
    period = {"weekly": "W", "monthly": "ME"}.get(freq, "ME")
    marks = index.to_series().resample(period).last().dropna()
    return pd.DatetimeIndex(marks.values)


def run_backtest(
    closes: pd.DataFrame,
    strategy: StrategyFn,
    opens: pd.DataFrame | None = None,
    start: str | None = None,
    end: str | None = None,
    name: str = "strategy",
) -> BacktestResult:
    """closes/opens: wide DataFrames (index=date, columns=tickers).

    strategy receives the close history STRICTLY BEFORE the execution day.
    """
    cfg = get_config().backtest
    capital = float(cfg.get("initial_capital", 100_000))
    cost_bps = (float(cfg.get("commission_bps", 2))
                + float(cfg.get("slippage_bps", 5))
                + float(cfg.get("spread_bps", 3)) / 2)
    cost_rate = cost_bps / 10_000
    freq = cfg.get("rebalance", "monthly")
    # Risk overlay: les paliers de reduction d'exposition (config risk.*)
    # sont simules comme en production. Decision a la cloture de t,
    # appliquee a partir de t+1 (pas de look-ahead).
    overlay_steps = (get_config().risk.get("drawdown_derisk_steps", [])
                     if bool(cfg.get("apply_risk_overlay", True)) else [])

    # Fenetre de DONNEES (full) distincte de la fenetre de SIMULATION (sim):
    # la strategie a besoin de l'historique anterieur a `start` pour chauffer
    # ses indicateurs (momentum 12m, SMA200...), la simulation ne demarre
    # qu'a `start`.
    full = closes.sort_index()
    if end:
        full = full.loc[:end]
    sim = full.loc[start or cfg.get("start"):]
    if sim.empty:
        raise ValueError("aucune donnee de prix dans la fenetre demandee")
    exec_prices = (opens if opens is not None else full).reindex(sim.index)

    rebal_dates = set(_rebalance_dates(sim.index, freq))
    daily_returns = full.pct_change().fillna(0.0)

    weights = pd.Series(dtype=float)
    pending_weights: pd.Series | None = None
    equity = capital
    peak = capital
    exposure_mult = 1.0
    days_derisked = 0
    min_exposure = 1.0
    equity_curve, weight_rows, trade_rows = [], [], []
    total_costs = 0.0

    dates = sim.index
    for i, dt in enumerate(dates):
        # 1. Execute pending rebalance at today's open (decided yesterday)
        if pending_weights is not None:
            new_w = pending_weights.reindex(full.columns).fillna(0.0)
            old_w = weights.reindex(full.columns).fillna(0.0)
            turnover = float((new_w - old_w).abs().sum()) * exposure_mult
            cost = equity * turnover * cost_rate
            equity -= cost
            total_costs += cost
            for t in new_w[(new_w - old_w).abs() > 1e-9].index:
                px = exec_prices.loc[dt, t] if t in exec_prices.columns else np.nan
                trade_rows.append({"date": dt, "ticker": t,
                                   "from_w": round(float(old_w[t]), 4),
                                   "to_w": round(float(new_w[t]), 4),
                                   "price": float(px) if np.isfinite(px) else None})
            weights = new_w
            pending_weights = None

        # 2. Daily P&L with current weights, scaled by the risk overlay
        if not weights.empty and i > 0:
            day_ret = float((weights * daily_returns.loc[dt]).sum())
            equity *= 1 + day_ret * exposure_mult
        equity_curve.append((dt, equity))
        weight_rows.append(weights.rename(dt))
        if exposure_mult < 1.0:
            days_derisked += 1

        # 2bis. Risk overlay: drawdown a la cloture de t -> exposition de t+1
        if overlay_steps:
            peak = max(peak, equity)
            dd = 1 - equity / peak
            target_mult = _derisk_multiplier(dd, overlay_steps)
            if target_mult != exposure_mult:
                # Reduire/augmenter l'exposition se paie en frais de transaction
                delta = abs(target_mult - exposure_mult) * float(weights.abs().sum())
                cost = equity * delta * cost_rate
                equity -= cost
                total_costs += cost
                exposure_mult = target_mult
                min_exposure = min(min_exposure, exposure_mult)

        # 3. Rebalance decision on close of rebalance days (executed at t+1)
        if dt in rebal_dates and i < len(dates) - 1:
            history = full.loc[:dt]  # data up to and including t, nothing more
            try:
                target = strategy(history, dt)
            except Exception as exc:
                log.warning("strategy failed at %s: %s", dt.date(), exc)
                target = weights
            if target is None:
                target = weights
            pending_weights = target.clip(lower=0.0)
            if pending_weights.sum() > 1.0:
                pending_weights = pending_weights / pending_weights.sum()

    eq = pd.Series(dict(equity_curve)).sort_index()
    res = BacktestResult(
        equity=eq,
        weights_history=pd.DataFrame(weight_rows),
        trades=pd.DataFrame(trade_rows),
        costs_paid=round(total_costs, 2),
        params={"name": name, "freq": freq, "cost_bps": cost_bps,
                "risk_overlay": bool(overlay_steps),
                "start": str(eq.index[0].date()), "end": str(eq.index[-1].date())},
        days_derisked=days_derisked,
        min_exposure=min_exposure,
    )
    log.info("backtest %s: %s -> %.0f (couts %.0f)", name,
             res.params["start"], equity, total_costs)
    return res


# -- Reference strategy: ATLAS momentum/quality proxy ----------------------------

def momentum_strategy(top_n: int = 20, lookback: int = 126,
                      skip_recent: int = 21) -> StrategyFn:
    """Price-only proxy of the composite score, usable point-in-time since 2000:
    rank by 6-month momentum (skip last month), keep names above 200d SMA,
    weight by inverse volatility.

    The full composite (fundamentals, sector, macro) requires point-in-time
    fundamentals to be backtested honestly; this proxy validates the
    technical/momentum sleeve over 2000-today including crises.
    """
    from atlas.portfolio.construction import inverse_volatility

    def strategy(history: pd.DataFrame, dt: pd.Timestamp) -> pd.Series:
        if len(history) < 252:
            return pd.Series(dtype=float)
        closes = history.iloc[-280:]
        mom = closes.iloc[-skip_recent - 1] / closes.iloc[-lookback - skip_recent - 1] - 1
        sma200 = history.iloc[-200:].mean()
        last = history.iloc[-1]
        eligible = mom[(last > sma200) & mom.notna()].sort_values(ascending=False)
        picks = list(eligible.index[:top_n])
        if not picks:
            return pd.Series(dtype=float)
        rets = history[picks].iloc[-126:].pct_change().dropna()
        if rets.empty:
            return pd.Series(1.0 / len(picks), index=picks)
        return inverse_volatility(rets)

    return strategy
