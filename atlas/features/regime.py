"""Macro regime detection from FRED series.

Regimes: EXPANSION, SLOWDOWN, RECESSION, RECOVERY (+ NEUTRAL fallback).
Logic: growth direction (industrial production / unemployment trend)
crossed with monetary conditions (yield curve, inflation trend).

The regime feeds two things downstream:
- a macro score per stock (risk-on regimes favor cyclicals/growth),
- a global gross-exposure modifier in risk management.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


class Regime(str, Enum):
    EXPANSION = "expansion"
    SLOWDOWN = "slowdown"
    RECESSION = "recession"
    RECOVERY = "recovery"
    NEUTRAL = "neutral"


# Score macro 0-100 par regime pour un portefeuille long actions
REGIME_EQUITY_SCORE = {
    Regime.EXPANSION: 80.0,
    Regime.RECOVERY: 90.0,
    Regime.SLOWDOWN: 45.0,
    Regime.RECESSION: 20.0,
    Regime.NEUTRAL: 50.0,
}

# Modificateur d'exposition brute applique par le risk manager
REGIME_EXPOSURE = {
    Regime.EXPANSION: 1.0,
    Regime.RECOVERY: 1.0,
    Regime.SLOWDOWN: 0.7,
    Regime.RECESSION: 0.4,
    Regime.NEUTRAL: 0.85,
}


@dataclass
class MacroState:
    regime: Regime = Regime.NEUTRAL
    equity_score: float = 50.0
    exposure_modifier: float = 0.85
    indicators: dict = field(default_factory=dict)


def _yoy(s: pd.Series, periods: int = 12) -> float:
    s = s.dropna()
    if len(s) <= periods:
        return np.nan
    return float(s.iloc[-1] / s.iloc[-1 - periods] - 1)


def _trend(s: pd.Series, months: int = 6) -> float:
    """Signed change over the last N observations (monthly series)."""
    s = s.dropna()
    if len(s) <= months:
        return np.nan
    return float(s.iloc[-1] - s.iloc[-1 - months])


def detect_regime(series: dict[str, pd.Series]) -> MacroState:
    if not series:
        return MacroState()

    indicators: dict[str, float] = {}

    indpro_yoy = _yoy(series.get("industrial_production", pd.Series(dtype=float)))
    unemp_trend = _trend(series.get("unemployment", pd.Series(dtype=float)))
    cpi_yoy = _yoy(series.get("cpi", pd.Series(dtype=float)))
    cpi_trend = _trend(series.get("cpi", pd.Series(dtype=float)).pct_change(12) * 100
                       if "cpi" in series else pd.Series(dtype=float), 6)
    curve = series.get("yield_curve_10y2y", pd.Series(dtype=float)).dropna()
    curve_last = float(curve.iloc[-1]) if len(curve) else np.nan
    m2_yoy = _yoy(series.get("m2", pd.Series(dtype=float)))

    indicators.update({
        "indpro_yoy": indpro_yoy, "unemployment_trend_6m": unemp_trend,
        "cpi_yoy": cpi_yoy, "cpi_trend_6m": cpi_trend,
        "yield_curve_10y2y": curve_last, "m2_yoy": m2_yoy,
    })

    growth_up = (not np.isnan(indpro_yoy) and indpro_yoy > 0) or \
                (not np.isnan(unemp_trend) and unemp_trend < 0)
    growth_down = (not np.isnan(indpro_yoy) and indpro_yoy < -0.01) or \
                  (not np.isnan(unemp_trend) and unemp_trend > 0.3)
    curve_inverted = not np.isnan(curve_last) and curve_last < 0
    inflation_falling = not np.isnan(cpi_trend) and cpi_trend < 0

    if growth_down and curve_inverted:
        regime = Regime.RECESSION
    elif growth_down:
        regime = Regime.SLOWDOWN
    elif growth_up and inflation_falling:
        regime = Regime.RECOVERY
    elif growth_up:
        regime = Regime.EXPANSION
    else:
        regime = Regime.NEUTRAL

    state = MacroState(
        regime=regime,
        equity_score=REGIME_EQUITY_SCORE[regime],
        exposure_modifier=REGIME_EXPOSURE[regime],
        indicators=indicators,
    )
    log.info("regime macro: %s (score=%s)", regime.value, state.equity_score)
    return state
