"""Position sizing: risk-based (distance to stop), Kelly-capped, regime-adjusted."""

from __future__ import annotations

import logging
import math

from atlas.config import get_config

log = logging.getLogger(__name__)


def risk_based_size(
    capital: float,
    entry: float,
    stop: float,
    exposure_modifier: float = 1.0,
) -> int:
    """Shares so that (entry - stop) * qty = risk_per_trade * capital.

    Capped by max_weight_per_position. exposure_modifier scales down sizing
    in unfavorable macro regimes (see features/regime.py).
    """
    cfg = get_config().portfolio
    risk_pct = float(cfg.get("risk_per_trade", 0.0075))
    max_w = float(cfg.get("max_weight_per_position", 0.05))
    # Entrees invalides (NaN/inf, ex: cours absent un jour ferie) -> 0, jamais
    # une exception. int(NaN) plantait le run nocturne (cf. Juneteenth 2026).
    if not all(math.isfinite(x) for x in (capital, entry, stop)):
        return 0
    r = entry - stop
    if r <= 0 or entry <= 0 or capital <= 0:
        return 0
    qty_risk = (capital * risk_pct * exposure_modifier) / r
    qty_cap = (capital * max_w) / entry
    if not math.isfinite(qty_risk) or not math.isfinite(qty_cap):
        return 0
    return int(max(min(qty_risk, qty_cap), 0))


def kelly_fraction(win_rate: float, avg_win_r: float, avg_loss_r: float = 1.0) -> float:
    """Kelly f* = p/b_loss - q/b_win, capped by config (kelly_cap).

    Returns the fraction of the risk budget to deploy, in [0, kelly_cap].
    Inputs come from the learning module's realized statistics.
    """
    cap = float(get_config().portfolio.get("kelly_cap", 0.25))
    if avg_win_r <= 0 or not 0 < win_rate < 1:
        return 0.0
    b = avg_win_r / avg_loss_r
    f = win_rate - (1 - win_rate) / b
    return float(max(0.0, min(f, cap)))
