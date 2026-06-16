"""Continuous risk management.

Monitors: portfolio drawdown, per-position drawdown, average pairwise
correlation, sector concentration, country/currency exposure.
Emits RiskActions consumed by the execution layer:
  REDUCE_EXPOSURE (target gross), CLOSE_POSITION, REBALANCE, HEDGE, NONE.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum

import numpy as np
import pandas as pd

from atlas.config import get_config

log = logging.getLogger(__name__)


class RiskActionType(str, Enum):
    NONE = "none"
    REDUCE_EXPOSURE = "reduce_exposure"
    CLOSE_POSITION = "close_position"
    REBALANCE = "rebalance"
    HEDGE = "hedge"


@dataclass
class RiskAction:
    action: RiskActionType
    reason: str
    target_gross_exposure: float | None = None
    ticker: str | None = None


@dataclass
class RiskReport:
    portfolio_drawdown: float = 0.0
    avg_correlation: float = np.nan
    sector_weights: dict = field(default_factory=dict)
    country_weights: dict = field(default_factory=dict)
    position_drawdowns: dict = field(default_factory=dict)
    actions: list[RiskAction] = field(default_factory=list)


def drawdown(equity: pd.Series) -> float:
    """Current drawdown from the running peak (positive number)."""
    if equity.empty:
        return 0.0
    peak = equity.cummax()
    return float((1 - equity / peak).iloc[-1])


def evaluate_risk(
    equity_curve: pd.Series,
    positions: pd.DataFrame,
    returns: pd.DataFrame | None = None,
    sectors: pd.Series | None = None,
    countries: pd.Series | None = None,
) -> RiskReport:
    """positions: columns [ticker, qty, avg_price, last_price]."""
    cfg = get_config().risk
    report = RiskReport()
    actions: list[RiskAction] = []

    # 1. Drawdown global -> paliers de de-risking
    dd = drawdown(equity_curve)
    report.portfolio_drawdown = dd
    for step in sorted(cfg.get("drawdown_derisk_steps", []),
                       key=lambda s: s["drawdown"], reverse=True):
        if dd >= float(step["drawdown"]):
            actions.append(RiskAction(
                RiskActionType.REDUCE_EXPOSURE,
                f"drawdown {dd:.1%} >= palier {step['drawdown']:.0%}",
                target_gross_exposure=float(step["gross_exposure"]),
            ))
            break

    if positions is not None and not positions.empty:
        value = positions["qty"] * positions["last_price"]
        # Denominateur = capital total (cash inclus), coherent avec la
        # contrainte appliquee a l'entree. Rapporter a la seule valeur
        # investie surestime la concentration quand le portefeuille n'est
        # que partiellement deploye.
        total_equity = float(equity_curve.iloc[-1]) if len(equity_curve) else 0.0
        denom = total_equity if total_equity > 0 else float(value.sum())
        weights = value / denom if denom else value

        # 2. Drawdown par position (stop catastrophe)
        max_pos_dd = float(cfg.get("max_position_drawdown", 0.20))
        for _, pos in positions.iterrows():
            pos_dd = 1 - pos["last_price"] / pos["avg_price"] if pos["avg_price"] else 0
            report.position_drawdowns[pos["ticker"]] = round(float(pos_dd), 4)
            if pos_dd >= max_pos_dd:
                actions.append(RiskAction(
                    RiskActionType.CLOSE_POSITION,
                    f"{pos['ticker']} en perte de {pos_dd:.1%} (max {max_pos_dd:.0%})",
                    ticker=str(pos["ticker"]),
                ))

        # 3. Correlation moyenne du book
        if returns is not None and returns.shape[1] >= 2:
            corr = returns.corr()
            mask = ~np.eye(len(corr), dtype=bool)
            report.avg_correlation = float(corr.values[mask].mean())
            if report.avg_correlation > float(cfg.get("max_avg_correlation", 0.7)):
                actions.append(RiskAction(
                    RiskActionType.HEDGE,
                    f"correlation moyenne {report.avg_correlation:.2f} trop elevee",
                ))

        # 4. Concentration sectorielle / pays
        max_sector = float(get_config().portfolio.get("max_weight_per_sector", 0.25))
        if sectors is not None:
            sw = weights.groupby(
                sectors.reindex(positions["ticker"]).fillna("Unknown").values
            ).sum()
            report.sector_weights = sw.round(4).to_dict()
            for sector, w in sw.items():
                if w > max_sector * 1.1:
                    actions.append(RiskAction(
                        RiskActionType.REBALANCE,
                        f"secteur {sector} a {w:.1%} (max {max_sector:.0%})",
                    ))
        if countries is not None:
            cw = weights.groupby(
                countries.reindex(positions["ticker"]).fillna("Unknown").values
            ).sum()
            report.country_weights = cw.round(4).to_dict()
            max_country = float(cfg.get("max_country_weight", 0.7))
            for country, w in cw.items():
                if w > max_country:
                    actions.append(RiskAction(
                        RiskActionType.REBALANCE,
                        f"pays {country} a {w:.1%} (max {max_country:.0%})",
                    ))

    if not actions:
        actions.append(RiskAction(RiskActionType.NONE, "tous les seuils respectes"))
    report.actions = actions
    for a in actions:
        if a.action != RiskActionType.NONE:
            log.warning("RISK ACTION: %s - %s", a.action.value, a.reason)
    return report
