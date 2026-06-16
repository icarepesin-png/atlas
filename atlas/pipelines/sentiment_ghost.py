"""Sentiment en MODE FANTOME: note les titres avec le LLM local, journalise,
n'influence JAMAIS les scores ni le portefeuille (poids zero).

Run:  python -m atlas.pipelines.sentiment_ghost [--limit 5]

Strategie de couverture: chaque nuit, les N titres les mieux classes au
composite dont le score sentiment date de plus de `refresh_days` sont
re-notes. L'univers utile est donc couvert en quelques semaines puis
rafraichi en continu. Apres plusieurs mois, l'IC (correlation entre ces
notes et les rendements realises) decidera si le pilier merite son poids.

Si Ollama n'est pas lance ou le modele absent, le pipeline se termine
silencieusement: le fantome ne casse jamais le run nocturne.
"""

from __future__ import annotations

import argparse
import logging
from datetime import date

import pandas as pd
from sqlalchemy import text

from atlas.config import get_config
from atlas.data.store import init_db, read_table
from atlas.features.sentiment import OllamaNewsSentiment

log = logging.getLogger(__name__)

_DDL = """
CREATE TABLE IF NOT EXISTS sentiment_scores (
    as_of_date TEXT NOT NULL,
    ticker TEXT NOT NULL,
    score REAL,
    confidence TEXT,
    n_headlines INTEGER,
    risks TEXT,
    opportunities TEXT,
    model TEXT,
    PRIMARY KEY (as_of_date, ticker)
)
"""


def select_tickers(limit: int, refresh_days: int) -> list[str]:
    """Top composite d'abord, en sautant ceux notes recemment."""
    scores = read_table("scores")
    if scores.empty:
        return []
    latest = scores[scores["as_of_date"] == scores["as_of_date"].max()]
    ranked = latest.sort_values("composite", ascending=False)["ticker"].tolist()

    engine = init_db()
    with engine.begin() as conn:
        conn.execute(text(_DDL))
        rows = conn.execute(text(
            "SELECT ticker, MAX(as_of_date) FROM sentiment_scores GROUP BY ticker"
        )).fetchall()
    last_scored = {r[0]: pd.Timestamp(r[1]) for r in rows}
    cutoff = pd.Timestamp(date.today()) - pd.Timedelta(days=refresh_days)
    fresh_needed = [t for t in ranked
                    if last_scored.get(t, pd.Timestamp.min) < cutoff]
    return fresh_needed[:limit]


def run(limit: int | None = None) -> dict:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = get_config().raw.get("sentiment_ghost", {})
    if not cfg.get("enabled", True):
        return {"status": "disabled"}
    model = cfg.get("model", "llama3.1:8b")
    n = limit or int(cfg.get("tickers_per_night", 30))
    refresh_days = int(cfg.get("refresh_days", 7))

    provider = OllamaNewsSentiment(model=model)
    if not provider.is_available():
        log.info("sentiment fantome: Ollama indisponible ou modele %s absent,"
                 " etape sautee", model)
        return {"status": "ollama_unavailable"}

    tickers = select_tickers(n, refresh_days)
    if not tickers:
        return {"status": "nothing_to_score"}

    engine = init_db()
    as_of = str(date.today())
    scored, skipped = 0, 0
    for ticker in tickers:
        result = provider.score_ticker(ticker)
        if result.confidence == "none":
            skipped += 1
            continue
        with engine.begin() as conn:
            conn.execute(text(_DDL))
            conn.execute(text(
                "INSERT OR REPLACE INTO sentiment_scores"
                " (as_of_date, ticker, score, confidence, n_headlines,"
                "  risks, opportunities, model)"
                " VALUES (:d, :t, :s, :c, :n, :r, :o, :m)"),
                {"d": as_of, "t": ticker, "s": result.score,
                 "c": result.confidence, "n": result.n_headlines,
                 "r": "; ".join(result.risks),
                 "o": "; ".join(result.opportunities), "m": model})
        scored += 1
        log.info("fantome %s: %s/100 (%s) - %d titres de presse",
                 ticker, result.score, result.confidence, result.n_headlines)

    summary = {"status": "ok", "scored": scored, "skipped": skipped,
               "model": model}
    log.info("sentiment fantome: %s", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    print(run(limit=args.limit))
