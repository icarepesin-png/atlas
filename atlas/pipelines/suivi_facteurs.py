# -*- coding: utf-8 -*-
"""Mesure chaque nuit le pouvoir predictif des piliers de score.

Pourquoi ce pipeline existe: atlas/learning/feedback.py savait deja calculer
l'IC de chaque pilier et la table factor_performance l'attendait... mais rien
ne les appelait. La table est restee VIDE de juin a aout 2026, pendant que le
pilier technique produisait un IC de -0.289 - un signal a l'envers, invisible
faute de mesure. Cette surveillance existe pour que ca ne se reproduise pas.

Principe: on ne peut mesurer un IC qu'une fois le rendement futur CONNU. On
remonte donc aux scores d'il y a N seances et on les confronte au rendement
effectivement realise depuis. Idempotent (INSERT OR REPLACE par date/facteur/
horizon), best-effort: ce pipeline ne doit jamais faire echouer le run.

Run:  python -m atlas.pipelines.suivi_facteurs
"""

from __future__ import annotations

import logging

import pandas as pd

from atlas.data.store import init_db, load_ohlcv, read_table
from atlas.learning.feedback import compute_factor_ic, store_factor_ic

log = logging.getLogger(__name__)

HORIZONS = (5, 10, 21)
MIN_TITRES = 30


def _rendements(tickers, depart: pd.Timestamp, horizon: int) -> pd.Series:
    """Rendement realise sur `horizon` seances a partir de `depart`."""
    out = {}
    for t in tickers:
        df = load_ohlcv(t)
        if df.empty:
            continue
        apres = df.loc[df.index >= depart]
        if len(apres) <= horizon:
            continue
        p0 = float(apres["close"].iloc[0])
        if p0 > 0:
            out[t] = float(apres["close"].iloc[horizon]) / p0 - 1
    return pd.Series(out)


def run(horizons=HORIZONS) -> dict:
    init_db()
    scores = read_table("scores")
    if scores.empty:
        return {"status": "vide"}
    scores["d"] = pd.to_datetime(scores["as_of_date"]).dt.normalize()
    dates = sorted(scores["d"].unique())
    resume: dict = {"status": "ok", "mesures": 0}

    for horizon in horizons:
        # La date la plus recente dont le rendement a `horizon` est connu.
        candidates = [d for d in dates
                      if len(_rendements(scores[scores["d"] == d]["ticker"]
                                         .head(5), d, horizon)) > 0]
        if not candidates:
            continue
        cible = candidates[-1]
        lot = scores[scores["d"] == cible].set_index("ticker")
        fwd = _rendements(lot.index, cible, horizon)
        if len(fwd) < MIN_TITRES:
            continue
        ic = compute_factor_ic(lot, fwd)
        # Un pilier constant (macro identique pour tous, sentiment neutre)
        # n'a pas d'IC defini: on ne stocke pas de NaN.
        ic = {k: v for k, v in ic.items() if v == v}
        if not ic:
            continue
        as_of = pd.Timestamp(cible).date().isoformat()
        store_factor_ic(ic, as_of, horizon, len(fwd))
        resume["mesures"] += 1
        resume[f"ic_{horizon}j"] = ic
        pires = [f"{k} {v:+.3f}" for k, v in sorted(ic.items(), key=lambda x: x[1])[:2]]
        log.info("IC %dj au %s (%d titres): %s", horizon, as_of, len(fwd),
                 ", ".join(f"{k}={v:+.3f}" for k, v in ic.items()))
        if pires:
            log.info("   piliers les plus faibles: %s", " | ".join(pires))
    return resume


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    print(run())
