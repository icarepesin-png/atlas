"""Portfolio construction: equal weight, inverse vol, volatility targeting,
hierarchical risk parity (Lopez de Prado), Kelly-capped overlay.

Input: returns DataFrame (columns=tickers, daily returns) for the candidates.
Output: weight Series summing to <= 1.0 (rest is cash).
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import linkage
from scipy.spatial.distance import squareform

from atlas.config import get_config

log = logging.getLogger(__name__)


def equal_weight(tickers: list[str]) -> pd.Series:
    if not tickers:
        return pd.Series(dtype=float)
    return pd.Series(1.0 / len(tickers), index=tickers)


def inverse_volatility(returns: pd.DataFrame) -> pd.Series:
    vol = returns.std() * np.sqrt(252)
    vol = vol.replace(0.0, np.nan).dropna()
    if vol.empty:
        return pd.Series(dtype=float)
    iv = 1.0 / vol
    return iv / iv.sum()


def volatility_targeting(returns: pd.DataFrame, target_vol: float | None = None) -> pd.Series:
    """Inverse-vol weights scaled so expected portfolio vol matches target.

    Total allocation is capped at 100% (no leverage in MVP).
    """
    cfg = get_config().portfolio
    target = target_vol or float(cfg.get("target_volatility", 0.12))
    w = inverse_volatility(returns)
    if w.empty:
        return w
    cov = returns[w.index].cov() * 252
    port_vol = float(np.sqrt(w.values @ cov.values @ w.values))
    if port_vol <= 0:
        return w
    scale = min(target / port_vol, 1.0)
    return w * scale


# -- Hierarchical Risk Parity ---------------------------------------------------

def _quasi_diag(link: np.ndarray) -> list[int]:
    link = link.astype(int)
    sort_ix = pd.Series([link[-1, 0], link[-1, 1]])
    num_items = link[-1, 3]
    while sort_ix.max() >= num_items:
        sort_ix.index = range(0, sort_ix.shape[0] * 2, 2)
        df0 = sort_ix[sort_ix >= num_items]
        i = df0.index
        j = df0.values - num_items
        sort_ix[i] = link[j, 0]
        df0 = pd.Series(link[j, 1], index=i + 1)
        sort_ix = pd.concat([sort_ix, df0]).sort_index()
        sort_ix.index = range(sort_ix.shape[0])
    return sort_ix.tolist()


def _cluster_var(cov: pd.DataFrame, items: list[str]) -> float:
    sub = cov.loc[items, items]
    ivp = 1.0 / np.diag(sub.values)
    ivp /= ivp.sum()
    return float(ivp @ sub.values @ ivp)


def hrp(returns: pd.DataFrame) -> pd.Series:
    """Hierarchical Risk Parity weights."""
    rets = returns.dropna(axis=1, how="all").dropna()
    if rets.shape[1] < 2 or len(rets) < 60:
        return equal_weight(list(returns.columns))
    cov, corr = rets.cov(), rets.corr()
    dist = np.sqrt(0.5 * (1 - corr)).fillna(0.0)
    link = linkage(squareform(dist.values, checks=False), method="single")
    order = _quasi_diag(link)
    items = corr.index[order].tolist()

    w = pd.Series(1.0, index=items)
    clusters = [items]
    while clusters:
        clusters = [
            c[j:k]
            for c in clusters
            for j, k in ((0, len(c) // 2), (len(c) // 2, len(c)))
            if len(c) > 1
        ]
        for i in range(0, len(clusters), 2):
            c0, c1 = clusters[i], clusters[i + 1]
            v0, v1 = _cluster_var(cov, c0), _cluster_var(cov, c1)
            alpha = 1 - v0 / (v0 + v1)
            w[c0] *= alpha
            w[c1] *= 1 - alpha
    return w / w.sum()


# -- Constraints & dispatch -------------------------------------------------------

def apply_constraints(weights: pd.Series, sectors: pd.Series | None = None) -> pd.Series:
    """Cap per-position and per-sector weights; excess goes to cash."""
    cfg = get_config().portfolio
    max_w = float(cfg.get("max_weight_per_position", 0.05))
    max_sector = float(cfg.get("max_weight_per_sector", 0.25))
    w = weights.clip(upper=max_w)
    if sectors is not None:
        for sector, group in w.groupby(sectors.reindex(w.index).fillna("Unknown")):
            total = group.sum()
            if total > max_sector:
                w[group.index] *= max_sector / total
    return w


def build_portfolio(
    returns: pd.DataFrame,
    method: str | None = None,
    sectors: pd.Series | None = None,
) -> pd.Series:
    cfg = get_config().portfolio
    method = method or cfg.get("method", "volatility_targeting")
    max_pos = int(cfg.get("max_positions", 25))
    cols = list(returns.columns)[:max_pos]
    rets = returns[cols]

    if method == "equal_weight":
        w = equal_weight(cols)
    elif method == "inverse_vol":
        w = inverse_volatility(rets)
    elif method == "hrp":
        w = hrp(rets)
    else:
        w = volatility_targeting(rets)
    w = apply_constraints(w.dropna(), sectors)
    log.info("portefeuille %s: %d positions, exposition %.1f%%",
             method, len(w[w > 0]), 100 * w.sum())
    return w
