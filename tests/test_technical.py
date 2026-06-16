"""Smoke tests for technical indicators on synthetic data."""

import numpy as np
import pandas as pd
import pytest

from atlas.features.technical import (adx, atr, bollinger, donchian, ema,
                                      keltner, macd, rsi, sma,
                                      technical_score, technical_snapshot)


@pytest.fixture
def ohlcv() -> pd.DataFrame:
    rng = np.random.default_rng(7)
    n = 300
    idx = pd.bdate_range("2023-01-02", periods=n)
    close = pd.Series(100 * np.cumprod(1 + rng.normal(0.0008, 0.015, n)), index=idx)
    high = close * (1 + abs(rng.normal(0, 0.008, n)))
    low = close * (1 - abs(rng.normal(0, 0.008, n)))
    open_ = close.shift(1).fillna(close.iloc[0])
    vol = pd.Series(rng.integers(1e5, 1e6, n), index=idx).astype(float)
    return pd.DataFrame({"open": open_, "high": high, "low": low,
                         "close": close, "volume": vol})


def test_rsi_bounds(ohlcv):
    r = rsi(ohlcv["close"])
    assert ((r >= 0) & (r <= 100)).all()


def test_atr_positive(ohlcv):
    assert (atr(ohlcv).dropna() > 0).all()


def test_adx_bounds(ohlcv):
    a = adx(ohlcv).dropna()
    assert ((a >= 0) & (a <= 100)).all()


def test_moving_averages_align(ohlcv):
    c = ohlcv["close"]
    assert sma(c, 20).iloc[-1] == pytest.approx(c.iloc[-20:].mean())
    assert len(ema(c, 20)) == len(c)


def test_macd_shapes(ohlcv):
    line, sig, hist = macd(ohlcv["close"])
    assert (line - sig - hist).abs().max() < 1e-9


def test_channels(ohlcv):
    up, mid, lo = bollinger(ohlcv["close"])
    assert (up.dropna() >= lo.dropna()).all()
    dup, dlo = donchian(ohlcv)
    assert (dup.dropna() >= dlo.dropna()).all()
    kup, kmid, klo = keltner(ohlcv)
    assert (kup.dropna() >= klo.dropna()).all()


def test_snapshot_and_score(ohlcv):
    snap = technical_snapshot(ohlcv)
    assert snap and "rsi14" in snap
    score = technical_score(snap)
    assert 0 <= score <= 100
