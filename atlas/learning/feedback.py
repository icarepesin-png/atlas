"""Auto-improvement loop (human-gated).

Records everything (signals, trades, scores are already persisted by the
pipeline), then measures:
- factor IC: Spearman rank correlation between each factor score at date t
  and the forward return over N days -> which factors work / decay;
- hit rate by score bucket: calibrates Signal.probability;
- per-regime performance: which strategy sleeve works in which macro regime.

propose_weight_update() PRODUCES A PROPOSAL ONLY. Applying it to config.yaml
is a human decision (Phase 1/2) and stays behind an explicit call in Phase 3.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sqlalchemy import text

from atlas.config import get_config
from atlas.data.store import init_db, read_table

log = logging.getLogger(__name__)

PILLARS = ["fundamental", "technical", "macro", "sector", "sentiment"]


def compute_factor_ic(
    scores: pd.DataFrame,
    forward_returns: pd.Series,
    factors: list[str] | None = None,
) -> dict[str, float]:
    """Spearman IC between each pillar score and realized forward returns.

    scores: index=ticker (one as-of date); forward_returns: index=ticker.
    """
    factors = factors or PILLARS
    out = {}
    aligned = scores.join(forward_returns.rename("fwd"), how="inner")
    if len(aligned) < 20:
        return {}
    for f in factors:
        if f not in aligned.columns:
            continue
        ic, _ = spearmanr(aligned[f], aligned["fwd"], nan_policy="omit")
        out[f] = round(float(ic), 4) if not np.isnan(ic) else np.nan
    return out


def store_factor_ic(ic: dict[str, float], as_of: str, forward_days: int,
                    universe_size: int) -> None:
    engine = init_db()
    with engine.begin() as conn:
        for factor, value in ic.items():
            conn.execute(text(
                "INSERT OR REPLACE INTO factor_performance"
                " (as_of_date, factor, ic, forward_days, universe_size)"
                " VALUES (:d, :f, :ic, :fd, :n)"),
                {"d": as_of, "f": factor, "ic": value,
                 "fd": forward_days, "n": universe_size})


def hit_rate_by_score_bucket(min_trades: int = 30) -> dict[int, float]:
    """P(win) per composite-score bucket of 5 pts, from closed trades joined
    to their originating signals. Feeds Signal.probability calibration."""
    trades = read_table("trades")
    signals = read_table("signals")
    if trades.empty or signals.empty or "signal_id" not in trades.columns:
        return {}
    merged = trades.dropna(subset=["signal_id"]).merge(
        signals[["id", "composite_score"]], left_on="signal_id", right_on="id",
        how="inner")
    if len(merged) < min_trades:
        return {}
    merged["bucket"] = (merged["composite_score"] // 5 * 5).astype(int)
    rates = merged.groupby("bucket")["pnl"].apply(lambda s: float((s > 0).mean()))
    counts = merged.groupby("bucket").size()
    return {int(b): round(r, 3) for b, r in rates.items() if counts[b] >= 10}


def factor_decay_report(window_obs: int = 12) -> pd.DataFrame:
    """Rolling mean IC per factor: positive and stable = healthy,
    declining = degrading factor (candidate for down-weighting)."""
    hist = read_table("factor_performance")
    if hist.empty:
        return pd.DataFrame()
    hist = hist.sort_values("as_of_date")
    pivot = hist.pivot_table(index="as_of_date", columns="factor", values="ic")
    return pivot.rolling(window_obs, min_periods=3).mean()


def propose_weight_update(min_observations: int = 6,
                          learning_rate: float = 0.2) -> dict:
    """Proposal: shift pillar weights toward realized IC, bounded moves.

    new_w ~ old_w * (1 + learning_rate * normalized_ic), re-normalized,
    each pillar kept within [50%, 150%] of its current weight per update.
    Returns {"current": ..., "proposed": ..., "evidence": ...}; does NOT write.
    """
    current = get_config().scoring_weights.normalized()
    decay = factor_decay_report()
    if decay.empty or len(decay.dropna(how="all")) < min_observations:
        return {"current": current, "proposed": current,
                "evidence": "donnees insuffisantes, aucune modification proposee"}
    latest_ic = decay.iloc[-1].reindex(PILLARS).fillna(0.0)
    spread = latest_ic.abs().max()
    norm_ic = latest_ic / spread if spread else latest_ic * 0
    proposed = {}
    for pillar in PILLARS:
        w = current[pillar]
        adj = w * (1 + learning_rate * float(norm_ic.get(pillar, 0.0)))
        proposed[pillar] = float(np.clip(adj, 0.5 * w, 1.5 * w))
    total = sum(proposed.values())
    proposed = {k: round(v / total, 4) for k, v in proposed.items()}
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "current": {k: round(v, 4) for k, v in current.items()},
        "proposed": proposed,
        "evidence": {"latest_rolling_ic": latest_ic.round(4).to_dict()},
        "note": "Proposition seulement. Valider en walk-forward avant "
                "d'editer config.yaml (voir docs/GO_LIVE.md).",
    }
