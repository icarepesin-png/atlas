"""Healthcheck and J+1 execution-bar tests."""

from datetime import datetime

import numpy as np
import pandas as pd

from atlas.monitoring.healthcheck import last_expected_run
from atlas.pipelines.paper_trade import first_bar_after


def test_last_expected_run_weekday_morning():
    # Mercredi 9h00: le dernier run attendu est mardi 23h00
    now = datetime(2026, 6, 10, 9, 0)
    expected = last_expected_run(now)
    assert expected == datetime(2026, 6, 9, 23, 0)


def test_last_expected_run_monday_morning():
    # Lundi 9h00: le dernier run attendu est vendredi 23h00 (pas le week-end)
    now = datetime(2026, 6, 8, 9, 0)
    expected = last_expected_run(now)
    assert expected == datetime(2026, 6, 5, 23, 0)
    assert expected.weekday() == 4


def test_last_expected_run_late_evening():
    # Mercredi 23h30: le run du soir vient d'avoir lieu
    now = datetime(2026, 6, 10, 23, 30)
    assert last_expected_run(now) == datetime(2026, 6, 10, 23, 0)


def _ohlcv(dates):
    n = len(dates)
    return pd.DataFrame({
        "open": np.arange(n) + 100.0, "high": np.arange(n) + 101.0,
        "low": np.arange(n) + 99.0, "close": np.arange(n) + 100.5,
        "volume": np.full(n, 1e6),
    }, index=pd.DatetimeIndex(dates))


def test_first_bar_after_returns_next_session():
    df = _ohlcv(["2026-06-09", "2026-06-10", "2026-06-11"])
    bar = first_bar_after(df, "2026-06-10")
    assert bar is not None
    assert bar.name == pd.Timestamp("2026-06-11")
    assert bar["open"] == 102.0  # l'ouverture de J+1, pas la cloture de J


def test_first_bar_after_none_when_no_session_yet():
    df = _ohlcv(["2026-06-09", "2026-06-10"])
    assert first_bar_after(df, "2026-06-10") is None
    assert first_bar_after(pd.DataFrame(), "2026-06-10") is None
