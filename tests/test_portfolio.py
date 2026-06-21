"""Tests for portfolio construction, sizing and risk metrics."""

import numpy as np
import pandas as pd
import pytest

from atlas.backtest.metrics import (cagr, max_drawdown, profit_factor, sharpe,
                                    ulcer_index)
from atlas.portfolio.construction import (build_portfolio, equal_weight, hrp,
                                          inverse_volatility,
                                          volatility_targeting)
from atlas.portfolio.sizing import kelly_fraction, risk_based_size


@pytest.fixture
def returns() -> pd.DataFrame:
    rng = np.random.default_rng(11)
    idx = pd.bdate_range("2022-01-03", periods=300)
    data = {f"T{i}": rng.normal(0.0005, 0.01 + 0.004 * i, 300) for i in range(8)}
    return pd.DataFrame(data, index=idx)


def test_equal_weight():
    w = equal_weight(["A", "B", "C", "D"])
    assert w.sum() == pytest.approx(1.0)
    assert (w == 0.25).all()


def test_inverse_vol_sums_to_one(returns):
    w = inverse_volatility(returns)
    assert w.sum() == pytest.approx(1.0)
    assert w["T0"] > w["T7"]  # lower vol -> bigger weight


def test_vol_targeting_no_leverage(returns):
    w = volatility_targeting(returns, target_vol=0.10)
    assert 0 < w.sum() <= 1.0 + 1e-9


def test_hrp_valid_weights(returns):
    w = hrp(returns)
    assert w.sum() == pytest.approx(1.0)
    assert (w >= 0).all()
    assert set(w.index) == set(returns.columns)


def test_build_portfolio_constraints(returns):
    w = build_portfolio(returns, method="equal_weight")
    assert (w <= 0.05 + 1e-9).all()  # max_weight_per_position from config


def test_risk_based_size():
    # Stop serre: la contrainte max_weight_per_position (5% = 50 actions a 100)
    # prend le pas sur le sizing par risque (750 de risque / 5 = 150 actions).
    assert risk_based_size(capital=100_000, entry=100.0, stop=95.0) == 50
    # Stop large: le sizing par risque devient la contrainte active.
    # risk_per_trade=0.5% (config actuelle): 100000*0.005/20 = 25 actions.
    assert risk_based_size(capital=100_000, entry=100.0, stop=80.0) == 25
    assert risk_based_size(100_000, 100.0, 100.0) == 0


def test_risk_based_size_nan_safe():
    """Entrees NaN (cours absent un jour ferie) -> 0, jamais d'exception.
    Regression: int(NaN) faisait planter le run nocturne (Juneteenth 2026)."""
    nan = float("nan")
    assert risk_based_size(nan, 100.0, 95.0) == 0          # equity NaN
    assert risk_based_size(100_000, nan, 95.0) == 0        # entree NaN
    assert risk_based_size(100_000, 100.0, nan) == 0       # stop NaN
    assert risk_based_size(float("inf"), 100.0, 95.0) == 0  # inf


def test_kelly_capped():
    f = kelly_fraction(win_rate=0.60, avg_win_r=2.0)
    assert 0 < f <= 0.25


def test_metrics_sane():
    idx = pd.bdate_range("2020-01-01", periods=504)
    eq = pd.Series(np.linspace(100_000, 140_000, 504), index=idx)
    assert cagr(eq) > 0
    assert max_drawdown(eq) == pytest.approx(0.0)
    assert ulcer_index(eq) == pytest.approx(0.0)
    rets = eq.pct_change().dropna()
    assert sharpe(rets) > 0
    pnls = pd.Series([100, -50, 200, -25])
    assert profit_factor(pnls) == pytest.approx(4.0)
