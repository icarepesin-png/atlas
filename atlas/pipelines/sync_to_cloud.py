"""Synchronisation de la base locale (SQLite) vers une base cloud (Postgres).

But: le dashboard heberge dans le cloud lit cette base Postgres et reste donc
consultable 24h/24, meme PC eteint. Le moteur de trading, lui, reste sur
SQLite en local (aucun risque, aucune reecriture).

Mecanique: lit les tables utiles en local et les RECOPIE dans Postgres
(remplacement complet, via pandas to_sql). Les tables sont petites
(scores du jour, positions, trades, equity), donc c'est rapide et sans risque.

Config: l'URL Postgres vient de la variable d'environnement ATLAS_CLOUD_DB
(.env). Si absente, la synchro est ignoree silencieusement (pas de cloud =
pas d'erreur). Appele en fin de daily_run.

Run manuel: python -m atlas.pipelines.sync_to_cloud
"""

from __future__ import annotations

import logging
import os

import pandas as pd
from sqlalchemy import create_engine

from atlas.data.store import get_engine, read_table_raw

log = logging.getLogger(__name__)

# Tables poussees vers le cloud (lues par le dashboard)
SYNC_TABLES = ["signals", "positions", "trades", "paper_equity",
               "paper_account", "sentiment_scores", "backtests"]


def cloud_url() -> str | None:
    # .env via les settings ATLAS, avec repli sur la variable d'environnement
    # systeme (utile si lancee hors du contexte ATLAS).
    from atlas.config import get_settings

    url = (get_settings().atlas_cloud_db or os.environ.get("ATLAS_CLOUD_DB", "")).strip()
    return url or None


def run() -> dict:
    url = cloud_url()
    if not url:
        log.info("ATLAS_CLOUD_DB absente: synchro cloud ignoree")
        return {"status": "disabled"}

    local = get_engine()
    # psycopg2 attend postgresql://; on tolere l'alias postgres://
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg2://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    cloud = create_engine(url)

    synced = {}
    # scores: uniquement la derniere date (le dashboard n'affiche que le dernier scan)
    try:
        scores = read_table_raw("scores", local)
        if not scores.empty:
            scores = scores[scores["as_of_date"] == scores["as_of_date"].max()]
        scores.to_sql("scores", cloud, if_exists="replace", index=False)
        synced["scores"] = len(scores)
    except Exception as exc:
        log.warning("synchro scores echouee: %s", exc)

    for table in SYNC_TABLES:
        try:
            df = read_table_raw(table, local)
            df.to_sql(table, cloud, if_exists="replace", index=False)
            synced[table] = len(df)
        except Exception as exc:
            log.warning("synchro %s echouee: %s", table, exc)

    log.info("synchro cloud OK: %s", synced)
    return {"status": "ok", "synced": synced}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    print(run())
