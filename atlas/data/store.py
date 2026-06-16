"""Persistence layer.

- Parquet cache for OHLCV (fast, columnar, one file per ticker).
- SQL store (SQLite by default, PostgreSQL in production via DATABASE_URL)
  for scores, signals, trades, positions and backtest runs.

Schema mirrors db/schema.sql (PostgreSQL version).
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from atlas.config import get_config, get_settings

log = logging.getLogger(__name__)

_DDL = """
CREATE TABLE IF NOT EXISTS scores (
    as_of_date TEXT NOT NULL,
    ticker TEXT NOT NULL,
    composite REAL, fundamental REAL, technical REAL,
    macro REAL, sector REAL, sentiment REAL,
    sector_name TEXT, country TEXT,
    details TEXT,
    PRIMARY KEY (as_of_date, ticker)
);
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    as_of_date TEXT NOT NULL,
    ticker TEXT NOT NULL,
    side TEXT NOT NULL,
    entry REAL, stop REAL, tp1 REAL, tp2 REAL, tp3 REAL,
    r_multiple REAL, composite_score REAL, confidence TEXT,
    status TEXT DEFAULT 'new',
    details TEXT
);
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    ticker TEXT NOT NULL,
    side TEXT NOT NULL,
    qty REAL NOT NULL,
    order_type TEXT,
    limit_price REAL,
    status TEXT DEFAULT 'pending',
    broker TEXT,
    broker_order_id TEXT,
    filled_price REAL,
    filled_at TEXT
);
CREATE TABLE IF NOT EXISTS positions (
    ticker TEXT PRIMARY KEY,
    qty REAL NOT NULL,
    avg_price REAL NOT NULL,
    opened_at TEXT,
    stop REAL,
    trailing_stop REAL,
    signal_id INTEGER,
    currency TEXT DEFAULT 'USD',
    fx_entry REAL DEFAULT 1.0
);
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    side TEXT NOT NULL,
    qty REAL, entry_price REAL, exit_price REAL,
    opened_at TEXT, closed_at TEXT,
    pnl REAL, r_realized REAL,
    signal_id INTEGER,
    exit_reason TEXT
);
CREATE TABLE IF NOT EXISTS backtests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    name TEXT,
    params TEXT,
    metrics TEXT,
    equity_curve TEXT
);
CREATE TABLE IF NOT EXISTS factor_performance (
    as_of_date TEXT NOT NULL,
    factor TEXT NOT NULL,
    ic REAL,
    forward_days INTEGER,
    universe_size INTEGER,
    PRIMARY KEY (as_of_date, factor, forward_days)
);
"""


def get_engine() -> Engine:
    url = get_settings().database_url
    is_sqlite = url.startswith("sqlite")
    if is_sqlite:
        # Place SQLite file at project root regardless of cwd
        from atlas.config import PROJECT_ROOT
        url = f"sqlite:///{PROJECT_ROOT / 'atlas.db'}"
    engine = create_engine(url)
    if is_sqlite:
        # WAL: les lecteurs (dashboard, API) ne bloquent plus l'ecrivain
        # (run nocturne) et inversement. busy_timeout en filet de securite.
        from sqlalchemy import event

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()
    return engine


def init_db(engine: Engine | None = None) -> Engine:
    engine = engine or get_engine()
    with engine.begin() as conn:
        for stmt in _DDL.split(";"):
            if stmt.strip():
                conn.execute(text(stmt))
        # Migrations legeres pour les bases creees avant ces colonnes
        for migration in (
            "ALTER TABLE positions ADD COLUMN currency TEXT DEFAULT 'USD'",
            "ALTER TABLE positions ADD COLUMN fx_entry REAL DEFAULT 1.0",
        ):
            try:
                conn.execute(text(migration))
            except Exception:
                pass  # colonne deja presente
    return engine


# -- OHLCV parquet cache ------------------------------------------------------

def cache_path(ticker: str) -> str:
    safe = (ticker.replace("/", "_").replace("^", "_")
            .replace(".", "_").replace("=", "_"))
    return str(get_config().cache_dir / f"{safe}.parquet")


def save_ohlcv(ticker: str, df: pd.DataFrame) -> None:
    if df is not None and not df.empty:
        df.to_parquet(cache_path(ticker))


def load_ohlcv(ticker: str) -> pd.DataFrame:
    try:
        return pd.read_parquet(cache_path(ticker))
    except (FileNotFoundError, OSError):
        return pd.DataFrame()


def get_ohlcv_cached(ticker: str, provider, start=None, end=None,
                     max_age_days: int = 1) -> pd.DataFrame:
    """Cache-first read; refresh from provider when stale."""
    df = load_ohlcv(ticker)
    if not df.empty:
        last = df.index.max()
        age = (pd.Timestamp(date.today()) - last).days
        if age <= max_age_days:
            return df
    fresh = provider.get_ohlcv(ticker, start=start, end=end)
    if not fresh.empty:
        save_ohlcv(ticker, fresh)
        return fresh
    return df  # stale cache better than nothing


def get_ohlcv_batch_cached(tickers: list[str], provider, start=None, end=None,
                           max_age_days: int = 1) -> dict[str, pd.DataFrame]:
    """Batch variant: one multi-ticker request for everything stale or absent.

    Indispensable au-dela de ~100 titres (le sequentiel prend des heures)."""
    prices: dict[str, pd.DataFrame] = {}
    today = pd.Timestamp(date.today())
    stale: list[str] = []
    for t in tickers:
        df = load_ohlcv(t)
        if not df.empty and (today - df.index.max()).days <= max_age_days:
            prices[t] = df
        else:
            stale.append(t)
    if stale:
        log.info("batch refresh: %d/%d tickers a telecharger", len(stale), len(tickers))
        fresh = provider.get_ohlcv_batch(stale, start=start, end=end)
        for t in stale:
            df = fresh.get(t, pd.DataFrame())
            if df is not None and not df.empty:
                save_ohlcv(t, df)
                prices[t] = df
            else:
                cached = load_ohlcv(t)
                if not cached.empty:
                    prices[t] = cached
    return prices


# -- SQL writers --------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def save_scores(scores: pd.DataFrame, as_of: str, engine: Engine | None = None) -> None:
    """scores: index=ticker, columns include composite/fundamental/technical/..."""
    engine = engine or init_db()
    rows = []
    for ticker, row in scores.iterrows():
        rows.append({
            "as_of_date": as_of, "ticker": ticker,
            "composite": row.get("composite"), "fundamental": row.get("fundamental"),
            "technical": row.get("technical"), "macro": row.get("macro"),
            "sector": row.get("sector"), "sentiment": row.get("sentiment"),
            "sector_name": row.get("sector_name"), "country": row.get("country"),
            "details": None,
        })
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM scores WHERE as_of_date = :d"), {"d": as_of})
        conn.execute(text(
            "INSERT INTO scores (as_of_date, ticker, composite, fundamental, technical,"
            " macro, sector, sentiment, sector_name, country, details)"
            " VALUES (:as_of_date, :ticker, :composite, :fundamental, :technical,"
            " :macro, :sector, :sentiment, :sector_name, :country, :details)"
        ), rows)


def save_signals(signals: list[dict], as_of: str, engine: Engine | None = None) -> None:
    engine = engine or init_db()
    rows = [{
        "created_at": _now(), "as_of_date": as_of, "ticker": s["ticker"],
        "side": s.get("side", "buy"), "entry": s.get("entry"), "stop": s.get("stop"),
        "tp1": s.get("tp1"), "tp2": s.get("tp2"), "tp3": s.get("tp3"),
        "r_multiple": s.get("r_multiple"), "composite_score": s.get("composite_score"),
        "confidence": s.get("confidence"), "details": json.dumps(s.get("details", {})),
    } for s in signals]
    with engine.begin() as conn:
        # Re-run du meme jour: remplace les signaux non traites au lieu de
        # les dupliquer (les 'executed'/'expired' sont conserves pour l'audit).
        conn.execute(text(
            "DELETE FROM signals WHERE as_of_date = :d AND status = 'new'"),
            {"d": as_of})
        if not rows:
            return
        conn.execute(text(
            "INSERT INTO signals (created_at, as_of_date, ticker, side, entry, stop,"
            " tp1, tp2, tp3, r_multiple, composite_score, confidence, details)"
            " VALUES (:created_at, :as_of_date, :ticker, :side, :entry, :stop,"
            " :tp1, :tp2, :tp3, :r_multiple, :composite_score, :confidence, :details)"
        ), rows)


def save_backtest(name: str, params: dict, metrics: dict,
                  equity_curve: pd.Series, engine: Engine | None = None) -> None:
    engine = engine or init_db()
    payload = {
        "created_at": _now(), "name": name,
        "params": json.dumps(params, default=str),
        "metrics": json.dumps(metrics, default=str),
        "equity_curve": equity_curve.to_json(date_format="iso"),
    }
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO backtests (created_at, name, params, metrics, equity_curve)"
            " VALUES (:created_at, :name, :params, :metrics, :equity_curve)"
        ), payload)


ALLOWED_TABLES = {"scores", "signals", "orders", "positions", "trades",
                  "backtests", "factor_performance", "paper_equity",
                  "paper_account", "sentiment_scores"}


def read_table(table: str, engine: Engine | None = None) -> pd.DataFrame:
    engine = engine or init_db()
    if table not in ALLOWED_TABLES:
        raise ValueError(f"table inconnue: {table}")
    with engine.connect() as conn:
        return pd.read_sql(text(f"SELECT * FROM {table}"), conn)


def read_table_raw(table: str, engine: Engine | None = None) -> pd.DataFrame:
    """Lecture SANS init_db (pas de DDL): pour le dashboard cloud qui lit une
    base Postgres deja peuplee par la synchro. Renvoie un df vide si la table
    n'existe pas encore. Fonctionne aussi en local (SQLite)."""
    if table not in ALLOWED_TABLES:
        raise ValueError(f"table inconnue: {table}")
    engine = engine or get_engine()
    try:
        with engine.connect() as conn:
            return pd.read_sql(text(f"SELECT * FROM {table}"), conn)
    except Exception:
        return pd.DataFrame()
