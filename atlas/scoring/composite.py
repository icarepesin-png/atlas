"""Composite multifactor score (0-100).

    composite = w_f * fundamental + w_t * technical + w_m * macro
              + w_s * sector + w_n * sentiment

Weights come from config.yaml (scoring.weights) and can be updated by the
learning module after human validation.
"""

from __future__ import annotations

import pandas as pd

from atlas.config import get_config
from atlas.features.fundamental import FACTOR_DIRECTIONS, FACTOR_GROUPS
from atlas.features.momentum import MOMENTUM_DIRECTIONS
from atlas.scoring.factors import factor_scores, group_score


def _respread(s: pd.Series) -> pd.Series:
    """Re-percentilize an averaged score (rank of ranks).

    Moyenner beaucoup de rangs percentiles compresse la distribution vers 50:
    sur 550 titres, presque personne ne depasse 80 et les seuils d'entree
    deviennent inatteignables. Le re-ranking restaure une lecture absolue:
    score 80 = top 20% de l'univers du jour.
    """
    if s.dropna().nunique() <= 1:
        return s.fillna(50.0)
    return (s.rank(pct=True) * 100).round(1)


def fundamental_score(raw: pd.DataFrame) -> pd.Series:
    """Quality 45% / Growth 25% / Value 30% over cross-sectional ranks,
    re-percentilized so that 80 means top quintile."""
    scores = factor_scores(raw, FACTOR_DIRECTIONS)
    quality = group_score(scores, FACTOR_GROUPS["quality"])
    growth = group_score(scores, FACTOR_GROUPS["growth"])
    value = group_score(scores, FACTOR_GROUPS["value"])
    return _respread(0.45 * quality + 0.25 * growth + 0.30 * value)


def momentum_overlay(raw: pd.DataFrame) -> pd.Series:
    """Momentum/low-vol score used to enrich the technical pillar."""
    scores = factor_scores(raw, MOMENTUM_DIRECTIONS)
    return _respread(scores.mean(axis=1, skipna=True))


def composite_score(
    fundamental: pd.Series,
    technical: pd.Series,
    sector: pd.Series,
    macro: float | None = None,
    sentiment: pd.Series | None = None,
) -> pd.DataFrame:
    """Assemble the final table. `macro` is scalar (same regime for all).

    macro/sentiment a None = pilier INDISPONIBLE (pas de cle FRED, pas de
    LLM): son poids est redistribue au prorata sur les piliers disponibles.
    Sans cette renormalisation, deux piliers figes a 50 plafonnent le
    composite a 87.5 et rendent le seuil d'entree de 85 quasi inatteignable.
    Les colonnes absentes sont stockees a 50 (neutre) pour l'affichage.
    """
    weights = get_config().scoring_weights.normalized()
    idx = fundamental.index
    pillars: dict[str, pd.Series] = {
        "fundamental": fundamental.reindex(idx).fillna(50.0),
        "technical": technical.reindex(idx).fillna(50.0),
        "sector": sector.reindex(idx).fillna(50.0),
    }
    if macro is not None:
        pillars["macro"] = pd.Series(float(macro), index=idx)
    if sentiment is not None:
        pillars["sentiment"] = sentiment.reindex(idx).fillna(50.0)

    active = {k: weights[k] for k in pillars}
    total = sum(active.values())
    df = pd.DataFrame(pillars)
    df["composite"] = sum(df[k] * (w / total) for k, w in active.items()).round(1)
    for missing in ("macro", "sentiment"):
        if missing not in df.columns:
            df[missing] = 50.0
    return df.sort_values("composite", ascending=False)
