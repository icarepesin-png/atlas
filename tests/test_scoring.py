"""Composite score tests, including pillar renormalization."""

import pandas as pd
import pytest

from atlas.scoring.composite import composite_score


def test_renormalization_without_macro_sentiment():
    """Missing pillars must not dilute the composite toward 50."""
    f = pd.Series({"A": 100.0, "B": 0.0})
    t = pd.Series({"A": 100.0, "B": 0.0})
    s = pd.Series({"A": 100.0, "B": 0.0})
    df = composite_score(fundamental=f, technical=t, sector=s)
    assert df.loc["A", "composite"] == pytest.approx(100.0)
    assert df.loc["B", "composite"] == pytest.approx(0.0)
    # colonnes neutres presentes pour le stockage
    assert df.loc["A", "macro"] == 50.0
    assert df.loc["A", "sentiment"] == 50.0


def test_full_pillars_weighting():
    f = pd.Series({"A": 80.0})
    t = pd.Series({"A": 80.0})
    s = pd.Series({"A": 80.0})
    df = composite_score(fundamental=f, technical=t, sector=s,
                         macro=50.0, sentiment=pd.Series({"A": 50.0}))
    # 0.75 * 80 + 0.25 * 50 = 72.5
    assert df.loc["A", "composite"] == pytest.approx(72.5, abs=0.1)


def test_fundamental_score_spreads_to_percentiles():
    """The aggregated fundamental score must span the 0-100 range, not
    compress around 50 (rank-of-ranks)."""
    import numpy as np

    from atlas.scoring.composite import fundamental_score

    rng = np.random.default_rng(5)
    n = 200
    raw = pd.DataFrame({
        "roe": rng.normal(0.15, 0.1, n),
        "gross_margin": rng.normal(0.4, 0.15, n),
        "revenue_growth": rng.normal(0.08, 0.1, n),
        "pe": rng.lognormal(3.0, 0.5, n),
        "fcf_yield": rng.normal(0.04, 0.03, n),
    }, index=[f"T{i}" for i in range(n)])
    s = fundamental_score(raw)
    assert s.max() > 95
    assert s.min() < 5
    assert (s >= 80).sum() == pytest.approx(n * 0.2, abs=2)


def test_sorted_descending():
    f = pd.Series({"A": 10.0, "B": 90.0})
    t = pd.Series({"A": 10.0, "B": 90.0})
    s = pd.Series({"A": 10.0, "B": 90.0})
    df = composite_score(fundamental=f, technical=t, sector=s)
    assert list(df.index) == ["B", "A"]
