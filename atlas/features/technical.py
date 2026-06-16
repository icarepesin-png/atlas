"""Technical indicators and setup detection. Pure pandas/numpy (no TA-Lib).

All functions take a normalized OHLCV DataFrame (atlas.data.base) and return
Series aligned on its index, or scalar diagnostics for the latest bar.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# -- Moving averages ----------------------------------------------------------

def sma(close: pd.Series, n: int) -> pd.Series:
    return close.rolling(n).mean()


def ema(close: pd.Series, n: int) -> pd.Series:
    return close.ewm(span=n, adjust=False).mean()


# -- Oscillators / trend strength ---------------------------------------------

def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    """Wilder's RSI."""
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / n, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / n, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50.0)


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    line = ema(close, fast) - ema(close, slow)
    sig = line.ewm(span=signal, adjust=False).mean()
    return line, sig, line - sig


def true_range(df: pd.DataFrame) -> pd.Series:
    pc = df["close"].shift(1)
    return pd.concat(
        [df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()],
        axis=1,
    ).max(axis=1)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    return true_range(df).ewm(alpha=1 / n, adjust=False).mean()


def adx(df: pd.DataFrame, n: int = 14) -> pd.Series:
    up = df["high"].diff()
    down = -df["low"].diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=df.index)
    atr_ = atr(df, n)
    plus_di = 100 * plus_dm.ewm(alpha=1 / n, adjust=False).mean() / atr_
    minus_di = 100 * minus_dm.ewm(alpha=1 / n, adjust=False).mean() / atr_
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0.0, np.nan)
    return dx.ewm(alpha=1 / n, adjust=False).mean().fillna(0.0)


# -- Channels -----------------------------------------------------------------

def bollinger(close: pd.Series, n: int = 20, k: float = 2.0):
    mid = sma(close, n)
    sd = close.rolling(n).std()
    return mid + k * sd, mid, mid - k * sd


def donchian(df: pd.DataFrame, n: int = 20):
    return df["high"].rolling(n).max(), df["low"].rolling(n).min()


def keltner(df: pd.DataFrame, n: int = 20, k: float = 2.0):
    mid = ema(df["close"], n)
    rng = k * atr(df, n)
    return mid + rng, mid, mid - rng


# -- Setup detection ----------------------------------------------------------

def stage(df: pd.DataFrame) -> int:
    """Weinstein stage analysis on weekly data.

    1=base, 2=advance (buyable), 3=top, 4=decline.
    """
    wk = df["close"].resample("W-FRI").last().dropna()
    if len(wk) < 35:
        return 0
    ma30 = wk.rolling(30).mean()
    price, ma = wk.iloc[-1], ma30.iloc[-1]
    slope = ma30.iloc[-1] - ma30.iloc[-5]
    if price > ma and slope > 0:
        return 2
    if price > ma and slope <= 0:
        return 3
    if price <= ma and slope < 0:
        return 4
    return 1


def breakout_donchian(df: pd.DataFrame, n: int = 55) -> bool:
    """Close above the prior n-day high."""
    if len(df) < n + 1:
        return False
    prior_high = df["high"].iloc[-(n + 1):-1].max()
    return bool(df["close"].iloc[-1] > prior_high)


def pullback_to_ema(df: pd.DataFrame, n: int = 21, atr_n: int = 14) -> bool:
    """Uptrend (50>200 EMA) with price pulling back within 1 ATR of EMA(n)."""
    if len(df) < 210:
        return False
    c = df["close"]
    if ema(c, 50).iloc[-1] <= ema(c, 200).iloc[-1]:
        return False
    dist = abs(c.iloc[-1] - ema(c, n).iloc[-1])
    return bool(dist <= atr(df, atr_n).iloc[-1])


def volatility_contraction(df: pd.DataFrame, lookback: int = 60) -> bool:
    """VCP heuristic: successive range contractions + volume dry-up.

    Splits the lookback in 3 windows; each window's high-low range must be
    tighter than the previous, and recent volume below its 50-day average.
    """
    if len(df) < max(lookback, 50):
        return False
    w = lookback // 3
    ranges = []
    for i in range(3):
        seg = df.iloc[len(df) - (3 - i) * w: len(df) - (2 - i) * w or len(df)]
        rng = (seg["high"].max() - seg["low"].min()) / seg["close"].mean()
        ranges.append(rng)
    contracting = ranges[0] > ranges[1] > ranges[2]
    vol_dry = df["volume"].iloc[-10:].mean() < df["volume"].rolling(50).mean().iloc[-1]
    return bool(contracting and vol_dry)


# -- Composite technical score --------------------------------------------------

def technical_snapshot(df: pd.DataFrame) -> dict:
    """All latest-bar technical diagnostics for one ticker."""
    if df.empty or len(df) < 60:
        return {}
    c = df["close"]
    out = {
        "close": float(c.iloc[-1]),
        "rsi14": float(rsi(c).iloc[-1]),
        "adx14": float(adx(df).iloc[-1]),
        "atr14": float(atr(df).iloc[-1]),
        "above_ema50": bool(c.iloc[-1] > ema(c, 50).iloc[-1]),
        "above_sma200": len(df) >= 200 and bool(c.iloc[-1] > sma(c, 200).iloc[-1]),
        "macd_positive": bool(macd(c)[2].iloc[-1] > 0),
        "stage": stage(df),
        "breakout": breakout_donchian(df),
        "pullback": pullback_to_ema(df),
        "vcp": volatility_contraction(df),
        "dist_52w_high": float(c.iloc[-1] / c.iloc[-252:].max() - 1) if len(c) >= 252 else np.nan,
    }
    return out


def technical_score(snap: dict) -> float:
    """0-100 technical score from a snapshot. Trend-following bias by design."""
    if not snap:
        return np.nan
    score = 0.0
    score += 20 if snap.get("above_sma200") else 0
    score += 15 if snap.get("above_ema50") else 0
    score += 15 if snap.get("stage") == 2 else 0
    score += 10 if snap.get("macd_positive") else 0
    adx_ = snap.get("adx14", 0)
    score += 10 * min(adx_ / 40.0, 1.0)                 # trend strength
    rsi_ = snap.get("rsi14", 50)
    score += 10 if 45 <= rsi_ <= 75 else (5 if 40 <= rsi_ < 45 else 0)
    if snap.get("breakout") or snap.get("pullback") or snap.get("vcp"):
        score += 10                                      # actionable setup present
    d52 = snap.get("dist_52w_high")
    if d52 is not None and not np.isnan(d52):
        score += 10 * max(0.0, 1.0 + d52 / 0.25) if d52 > -0.25 else 0  # near 52w high
    return float(min(score, 100.0))
