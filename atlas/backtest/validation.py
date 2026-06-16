"""Robustness validation: walk-forward, Monte Carlo, temporal CV, stress tests.

A strategy must pass these BEFORE paper trading (see docs/GO_LIVE.md):
- walk-forward: every out-of-sample window profitable or better than cash,
  parameter stability across windows;
- Monte Carlo: 5th percentile of final equity > initial capital,
  95th percentile of max drawdown below the configured limit;
- stress: positive-or-contained behavior in 2000-02, 2008, 2020, 2022 windows.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from atlas.backtest.engine import StrategyFn, run_backtest
from atlas.backtest.metrics import full_report, max_drawdown
from atlas.config import get_config

log = logging.getLogger(__name__)

STRESS_WINDOWS = {
    "dotcom_2000_2002": ("2000-03-01", "2002-10-31"),
    "gfc_2008": ("2007-10-01", "2009-03-31"),
    "covid_2020": ("2020-02-01", "2020-04-30"),
    "inflation_2022": ("2022-01-01", "2022-12-31"),
}


@dataclass
class WalkForwardResult:
    windows: list[dict] = field(default_factory=list)

    @property
    def oos_sharpes(self) -> list[float]:
        return [w["metrics"].get("sharpe") for w in self.windows]

    def summary(self) -> dict:
        sharpes = [s for s in self.oos_sharpes if s is not None and not np.isnan(s)]
        return {
            "n_windows": len(self.windows),
            "oos_sharpe_mean": round(float(np.mean(sharpes)), 3) if sharpes else None,
            "oos_sharpe_min": round(float(np.min(sharpes)), 3) if sharpes else None,
            "pct_windows_profitable": round(float(np.mean(
                [w["metrics"].get("total_return", 0) > 0 for w in self.windows]
            )), 3) if self.windows else None,
        }


def walk_forward(closes: pd.DataFrame, strategy: StrategyFn,
                 opens: pd.DataFrame | None = None) -> WalkForwardResult:
    """Anchored-rolling walk-forward driven by config.validation.walk_forward.

    The strategy only ever sees data prior to each decision (engine property),
    so each test window is genuinely out-of-sample.
    """
    cfg = get_config().validation.get("walk_forward", {})
    train_y = int(cfg.get("train_years", 5))
    test_y = int(cfg.get("test_years", 1))
    step_y = int(cfg.get("step_years", 1))

    start, end = closes.index.min(), closes.index.max()
    result = WalkForwardResult()
    cursor = start + pd.DateOffset(years=train_y)
    while cursor + pd.DateOffset(years=test_y) <= end:
        test_start = cursor
        test_end = cursor + pd.DateOffset(years=test_y)
        # history includes the train period so indicators are warm
        window = closes.loc[:test_end]
        bt = run_backtest(window, strategy, opens=opens,
                          start=str(test_start.date()), end=str(test_end.date()),
                          name=f"wf_{test_start.year}")
        result.windows.append({
            "test_start": str(test_start.date()),
            "test_end": str(test_end.date()),
            "metrics": full_report(bt.equity),
        })
        cursor += pd.DateOffset(years=step_y)
    log.info("walk-forward: %s", result.summary())
    return result


def monte_carlo(equity: pd.Series, n: int | None = None,
                block: int | None = None) -> dict:
    """Block bootstrap of strategy daily returns (preserves autocorrelation)."""
    cfg = get_config().validation.get("monte_carlo", {})
    n = n or int(cfg.get("n_simulations", 1000))
    block = block or int(cfg.get("block_size_days", 21))
    rets = equity.pct_change().dropna().values
    if len(rets) < block * 4:
        return {"error": "historique insuffisant pour le Monte Carlo"}
    rng = np.random.default_rng(42)
    horizon = len(rets)
    finals, mdds = [], []
    for _ in range(n):
        sim = []
        while len(sim) < horizon:
            start = rng.integers(0, len(rets) - block)
            sim.extend(rets[start:start + block])
        sim = np.array(sim[:horizon])
        curve = np.cumprod(1 + sim)
        finals.append(curve[-1])
        peak = np.maximum.accumulate(curve)
        mdds.append(float((1 - curve / peak).max()))
    return {
        "n_simulations": n,
        "final_multiple_p05": round(float(np.percentile(finals, 5)), 3),
        "final_multiple_p50": round(float(np.percentile(finals, 50)), 3),
        "final_multiple_p95": round(float(np.percentile(finals, 95)), 3),
        "max_drawdown_p50": round(float(np.percentile(mdds, 50)), 3),
        "max_drawdown_p95": round(float(np.percentile(mdds, 95)), 3),
        "prob_loss": round(float(np.mean(np.array(finals) < 1.0)), 3),
    }


def stress_tests(closes: pd.DataFrame, strategy: StrategyFn) -> dict:
    """Run the strategy through historical crisis windows."""
    out = {}
    for name, (start, end) in STRESS_WINDOWS.items():
        if pd.Timestamp(start) < closes.index.min():
            out[name] = {"skipped": "pas de donnees"}
            continue
        try:
            bt = run_backtest(closes, strategy, start=start, end=end, name=name)
            out[name] = {
                "total_return": full_report(bt.equity).get("total_return"),
                "max_drawdown": round(max_drawdown(bt.equity), 4),
            }
        except ValueError as exc:
            out[name] = {"skipped": str(exc)}
    return out


def parameter_sensitivity(closes: pd.DataFrame, base_top_n: int = 20,
                          base_lookback: int = 126,
                          start: str | None = None) -> dict:
    """Robustesse aux parametres: la strategie est rejouee avec top_n a
    +/- 50% et lookback a +/- 2 mois. Une strategie saine ne s'effondre pas
    quand on bouge ses parametres; si elle le fait, c'est un signe
    d'overfitting (les parametres sont calibres sur le bruit du passe).
    """
    from atlas.backtest.engine import momentum_strategy

    top_ns = sorted({max(5, base_top_n // 2), base_top_n,
                     int(base_top_n * 1.5)})
    lookbacks = sorted({base_lookback - 42, base_lookback, base_lookback + 42})
    rows = []
    for top_n in top_ns:
        for lookback in lookbacks:
            bt = run_backtest(closes, momentum_strategy(top_n=top_n,
                                                        lookback=lookback),
                              start=start, name=f"sens_n{top_n}_l{lookback}")
            m = full_report(bt.equity)
            rows.append({"top_n": top_n, "lookback": lookback,
                         "cagr": m.get("cagr"), "sharpe": m.get("sharpe"),
                         "max_drawdown": m.get("max_drawdown")})
    grid = pd.DataFrame(rows)
    sharpes = grid["sharpe"].dropna()
    cagrs = grid["cagr"].dropna()
    stable = (len(sharpes) > 0 and sharpes.min() > 0
              and len(cagrs) > 0 and cagrs.min() > 0
              and sharpes.min() >= 0.4 * sharpes.max())
    return {
        "grid": grid.to_dict(orient="records"),
        "sharpe_min": round(float(sharpes.min()), 3) if len(sharpes) else None,
        "sharpe_max": round(float(sharpes.max()), 3) if len(sharpes) else None,
        "cagr_min": round(float(cagrs.min()), 4) if len(cagrs) else None,
        "stable": bool(stable),
        "verdict": ("STABLE: les performances survivent aux variations de "
                    "parametres" if stable else
                    "FRAGILE: performances trop dependantes des parametres, "
                    "suspicion d'overfitting"),
    }


def purged_time_series_splits(index: pd.DatetimeIndex, n_splits: int = 5,
                              embargo_days: int = 10):
    """Temporal CV splits with embargo (purge) to avoid leakage between
    train and test through overlapping horizons. Yields (train_idx, test_idx)."""
    n = len(index)
    fold = n // (n_splits + 1)
    for k in range(1, n_splits + 1):
        train_end = k * fold
        test_start = train_end + embargo_days
        test_end = min(test_start + fold, n)
        if test_start >= n:
            break
        yield np.arange(0, train_end), np.arange(test_start, test_end)
