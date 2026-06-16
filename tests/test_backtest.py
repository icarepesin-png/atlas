"""Backtest engine tests: no look-ahead, costs applied, validation tools."""

import numpy as np
import pandas as pd
import pytest

from atlas.backtest.engine import momentum_strategy, run_backtest
from atlas.backtest.validation import monte_carlo, purged_time_series_splits


@pytest.fixture
def closes() -> pd.DataFrame:
    rng = np.random.default_rng(3)
    idx = pd.bdate_range("2018-01-01", periods=1500)
    data = {}
    for i in range(12):
        drift = 0.0003 + 0.0002 * (i % 4)
        data[f"S{i}"] = 50 * np.cumprod(1 + rng.normal(drift, 0.015, 1500))
    return pd.DataFrame(data, index=idx)


def test_backtest_runs_and_pays_costs(closes):
    bt = run_backtest(closes, momentum_strategy(top_n=5), start="2019-01-01")
    assert len(bt.equity) > 200
    assert bt.costs_paid > 0
    assert bt.equity.iloc[0] == pytest.approx(100_000, rel=0.01)


def test_no_lookahead(closes):
    """Strategy sees only history up to the decision date."""
    seen_futures = []

    def spy_strategy(history: pd.DataFrame, dt: pd.Timestamp) -> pd.Series:
        seen_futures.append(history.index.max() > dt)
        return pd.Series(dtype=float)

    run_backtest(closes, spy_strategy, start="2021-01-01", end="2021-06-30")
    assert not any(seen_futures)


def test_monte_carlo_output(closes):
    bt = run_backtest(closes, momentum_strategy(top_n=5), start="2019-01-01")
    mc = monte_carlo(bt.equity, n=50, block=21)
    assert "final_multiple_p50" in mc
    assert 0 <= mc["prob_loss"] <= 1


def test_purged_splits_no_overlap():
    idx = pd.bdate_range("2015-01-01", periods=1000)
    for train, test in purged_time_series_splits(idx, n_splits=4, embargo_days=10):
        assert train.max() + 10 <= test.min()


def test_risk_overlay_reduces_drawdown():
    """Sur un krach, l'overlay doit couper l'exposition et amortir la perte."""
    from atlas.backtest.metrics import max_drawdown
    from atlas.config import get_config

    # Un actif qui monte 2 ans puis perd ~45% en 4 mois
    idx = pd.bdate_range("2018-01-01", periods=700)
    up = 100 * np.cumprod(1 + np.full(500, 0.0008))
    down = up[-1] * np.cumprod(1 + np.full(200, -0.003))
    closes = pd.DataFrame({"CRASH": np.concatenate([up, down]),
                           "FLAT": np.full(700, 50.0)}, index=idx)

    def all_in(history, dt):
        return pd.Series({"CRASH": 1.0})

    cfg = get_config().raw["backtest"]
    try:
        cfg["apply_risk_overlay"] = False
        bt_naked = run_backtest(closes, all_in, start="2019-01-01")
        cfg["apply_risk_overlay"] = True
        bt_overlay = run_backtest(closes, all_in, start="2019-01-01")
    finally:
        cfg["apply_risk_overlay"] = True

    dd_naked = max_drawdown(bt_naked.equity)
    dd_overlay = max_drawdown(bt_overlay.equity)
    assert bt_overlay.days_derisked > 0
    assert bt_overlay.min_exposure < 1.0
    # L'overlay doit reduire significativement le pire drawdown
    assert dd_overlay < dd_naked * 0.75
    assert bt_naked.params["risk_overlay"] is False
    assert bt_overlay.params["risk_overlay"] is True
