"""Entry/exit signal generation.

Entry conditions (all required, thresholds in config.signals):
  composite > 85, fundamental > 80, technical > 80, sector > 70, liquidity ok.

For each candidate: entry price, ATR stop, trailing stop, 3 take-profits in
R multiples, estimated probability from historical hit-rate of the setup
(learning module; defaults to score-mapped heuristic until enough trades).
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass

import pandas as pd

from atlas.config import get_config
from atlas.features.technical import atr

log = logging.getLogger(__name__)


@dataclass
class Signal:
    ticker: str
    side: str               # "buy" (long-only MVP)
    entry: float
    stop: float
    trailing_stop: float
    tp1: float
    tp2: float
    tp3: float
    r_multiple: float       # distance entry->stop, en unite de prix
    composite_score: float
    confidence: str         # low | medium | high
    probability: float      # estimee, calibree par le module learning
    details: dict

    def to_dict(self) -> dict:
        return asdict(self)


def _confidence(score: float) -> str:
    if score >= 92:
        return "high"
    if score >= 88:
        return "medium"
    return "low"


def _probability(score: float, hit_rates: dict | None = None) -> float:
    """Heuristic until learning module has >100 closed trades per bucket."""
    if hit_rates:
        bucket = int(score // 5) * 5
        if bucket in hit_rates:
            return hit_rates[bucket]
    # mapping conservateur score -> proba de trade gagnant
    return round(min(0.45 + (score - 85) * 0.02, 0.70), 2)


def generate_signals(
    scores: pd.DataFrame,
    prices: dict[str, pd.DataFrame],
    hit_rates: dict | None = None,
) -> list[Signal]:
    """scores: output of composite_score() indexed by ticker."""
    cfg = get_config().signals
    min_comp = float(cfg.get("min_composite_score", 85))
    min_fund = float(cfg.get("min_fundamental_score", 80))
    min_tech = float(cfg.get("min_technical_score", 80))
    min_sect = float(cfg.get("min_sector_score", 70))
    stop_mult = float(cfg.get("stop_atr_multiple", 2.0))
    trail_mult = float(cfg.get("trailing_atr_multiple", 3.0))
    tp_r = cfg.get("take_profit_r", [1.5, 2.5, 4.0])
    atr_n = int(cfg.get("atr_period", 14))

    eligible = scores[
        (scores["composite"] >= min_comp)
        & (scores["fundamental"] >= min_fund)
        & (scores["technical"] >= min_tech)
        & (scores["sector"] >= min_sect)
    ]

    signals: list[Signal] = []
    for ticker, row in eligible.iterrows():
        df = prices.get(ticker)
        if df is None or df.empty or len(df) < 60:
            continue
        entry = float(df["close"].iloc[-1])
        a = float(atr(df, atr_n).iloc[-1])
        if not a or a <= 0:
            continue
        stop = round(entry - stop_mult * a, 2)
        r = entry - stop
        score = float(row["composite"])
        signals.append(Signal(
            ticker=str(ticker), side="buy",
            entry=round(entry, 2), stop=stop,
            # Le trailing demarre au stop et remonte ensuite avec le plus-haut
            # DEPUIS l'entree (check_exits). L'ancrer sur le plus-haut des 22
            # jours precedant l'achat sortirait immediatement les entrees en
            # pullback.
            trailing_stop=stop,
            tp1=round(entry + tp_r[0] * r, 2),
            tp2=round(entry + tp_r[1] * r, 2),
            tp3=round(entry + tp_r[2] * r, 2),
            r_multiple=round(r, 2),
            composite_score=score,
            confidence=_confidence(score),
            probability=_probability(score, hit_rates),
            details={
                "fundamental": float(row["fundamental"]),
                "technical": float(row["technical"]),
                "sector": float(row["sector"]),
                "macro": float(row["macro"]),
            },
        ))
    log.info("signaux generes: %d / %d eligibles", len(signals), len(eligible))
    return signals


def check_exits(positions: pd.DataFrame, prices: dict[str, pd.DataFrame]) -> list[dict]:
    """Exit orders for open positions: stop hit, trailing stop hit.

    positions: columns [ticker, qty, avg_price, opened_at, stop, trailing_stop]
    Chandelier exit ancre sur le plus-haut DEPUIS l'ouverture de la position.
    """
    cfg = get_config().signals
    trail_mult = float(cfg.get("trailing_atr_multiple", 3.0))
    exits = []
    for _, pos in positions.iterrows():
        df = prices.get(pos["ticker"])
        if df is None or df.empty:
            continue
        last = float(df["close"].iloc[-1])
        opened_at = pos.get("opened_at")
        if opened_at:
            opened = pd.to_datetime(opened_at, utc=True).tz_convert(None).normalize()
            since_entry = df.loc[df.index >= opened]
        else:
            since_entry = df.iloc[-1:]
        anchor_high = (float(since_entry["high"].max()) if len(since_entry)
                       else float(df["high"].iloc[-1]))
        new_trail = anchor_high - trail_mult * float(atr(df).iloc[-1])
        effective_stop = max(float(pos.get("stop") or 0), float(pos.get("trailing_stop") or 0), new_trail)
        if last <= effective_stop:
            exits.append({"ticker": pos["ticker"], "side": "sell",
                          "qty": float(pos["qty"]), "reason": "stop/trailing",
                          "price": last})
        else:
            exits.append({"ticker": pos["ticker"], "side": "update_stop",
                          "qty": 0.0, "reason": "trail_update",
                          "trailing_stop": round(new_trail, 2)})
    return exits
