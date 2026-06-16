-- ATLAS - Schema PostgreSQL de production.
-- Le MVP utilise SQLite (DDL equivalent dans atlas/data/store.py).
-- Migration: alembic conseille des que le schema bouge en production.

CREATE TABLE IF NOT EXISTS instruments (
    ticker        TEXT PRIMARY KEY,
    name          TEXT,
    exchange      TEXT,
    sector        TEXT,
    industry      TEXT,
    country       TEXT,
    currency      TEXT,
    index_memberships TEXT[],          -- ['sp500','msci_world']
    is_active     BOOLEAN DEFAULT TRUE,
    updated_at    TIMESTAMPTZ DEFAULT now()
);

-- Historique d'appartenance aux indices: indispensable contre le biais du survivant
CREATE TABLE IF NOT EXISTS index_membership_history (
    index_name    TEXT NOT NULL,
    ticker        TEXT NOT NULL,
    date_in       DATE NOT NULL,
    date_out      DATE,
    PRIMARY KEY (index_name, ticker, date_in)
);

CREATE TABLE IF NOT EXISTS prices_daily (
    ticker        TEXT NOT NULL,
    date          DATE NOT NULL,
    open          DOUBLE PRECISION,
    high          DOUBLE PRECISION,
    low           DOUBLE PRECISION,
    close         DOUBLE PRECISION,
    volume        BIGINT,
    PRIMARY KEY (ticker, date)
);
CREATE INDEX IF NOT EXISTS idx_prices_date ON prices_daily (date);

-- Fondamentaux point-in-time: filing_date = date de publication reelle.
-- Toute requete de backtest DOIT filtrer sur filing_date <= date_simulation.
CREATE TABLE IF NOT EXISTS fundamentals (
    ticker        TEXT NOT NULL,
    period_end    DATE NOT NULL,
    filing_date   DATE NOT NULL,
    source        TEXT,
    payload       JSONB NOT NULL,      -- ratios + postes des etats financiers
    PRIMARY KEY (ticker, period_end, source)
);
CREATE INDEX IF NOT EXISTS idx_fundamentals_filing ON fundamentals (filing_date);

CREATE TABLE IF NOT EXISTS macro_series (
    series_name   TEXT NOT NULL,
    date          DATE NOT NULL,
    value         DOUBLE PRECISION,
    PRIMARY KEY (series_name, date)
);

CREATE TABLE IF NOT EXISTS scores (
    as_of_date    DATE NOT NULL,
    ticker        TEXT NOT NULL,
    composite     DOUBLE PRECISION,
    fundamental   DOUBLE PRECISION,
    technical     DOUBLE PRECISION,
    macro         DOUBLE PRECISION,
    sector        DOUBLE PRECISION,
    sentiment     DOUBLE PRECISION,
    sector_name   TEXT,
    country       TEXT,
    details       JSONB,
    PRIMARY KEY (as_of_date, ticker)
);

CREATE TABLE IF NOT EXISTS signals (
    id            BIGSERIAL PRIMARY KEY,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    as_of_date    DATE NOT NULL,
    ticker        TEXT NOT NULL,
    side          TEXT NOT NULL,
    entry         DOUBLE PRECISION,
    stop          DOUBLE PRECISION,
    tp1           DOUBLE PRECISION,
    tp2           DOUBLE PRECISION,
    tp3           DOUBLE PRECISION,
    r_multiple    DOUBLE PRECISION,
    composite_score DOUBLE PRECISION,
    confidence    TEXT,
    status        TEXT DEFAULT 'new',   -- new | executed | expired | cancelled
    details       JSONB
);

CREATE TABLE IF NOT EXISTS orders (
    id            BIGSERIAL PRIMARY KEY,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    ticker        TEXT NOT NULL,
    side          TEXT NOT NULL,
    qty           DOUBLE PRECISION NOT NULL,
    order_type    TEXT,
    limit_price   DOUBLE PRECISION,
    status        TEXT DEFAULT 'pending',
    broker        TEXT,
    broker_order_id TEXT,
    filled_price  DOUBLE PRECISION,
    filled_at     TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS positions (
    ticker        TEXT PRIMARY KEY,
    qty           DOUBLE PRECISION NOT NULL,
    avg_price     DOUBLE PRECISION NOT NULL,
    opened_at     TIMESTAMPTZ,
    stop          DOUBLE PRECISION,
    trailing_stop DOUBLE PRECISION,
    signal_id     BIGINT REFERENCES signals(id)
);

CREATE TABLE IF NOT EXISTS trades (
    id            BIGSERIAL PRIMARY KEY,
    ticker        TEXT NOT NULL,
    side          TEXT NOT NULL,
    qty           DOUBLE PRECISION,
    entry_price   DOUBLE PRECISION,
    exit_price    DOUBLE PRECISION,
    opened_at     TIMESTAMPTZ,
    closed_at     TIMESTAMPTZ,
    pnl           DOUBLE PRECISION,
    r_realized    DOUBLE PRECISION,
    signal_id     BIGINT REFERENCES signals(id),
    exit_reason   TEXT
);

CREATE TABLE IF NOT EXISTS backtests (
    id            BIGSERIAL PRIMARY KEY,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    name          TEXT,
    params        JSONB,
    metrics       JSONB,
    equity_curve  JSONB
);

CREATE TABLE IF NOT EXISTS factor_performance (
    as_of_date    DATE NOT NULL,
    factor        TEXT NOT NULL,
    ic            DOUBLE PRECISION,
    forward_days  INTEGER,
    universe_size INTEGER,
    PRIMARY KEY (as_of_date, factor, forward_days)
);
