"""Daily scan pipeline: universe -> data -> features -> scores -> signals -> store.

Run:  python -m atlas.pipelines.daily_scan [--limit 200] [--refresh-universe]

Steps:
 1. Build universe (indices in config) and download OHLCV (batch, cache-first).
 2. Liquidity filter.
 3. Macro regime (FRED) and sector rotation scores (ETF proxies).
 4. Per-ticker: technical snapshot/score, momentum factors, fundamentals
    (parallel fetch + daily parquet cache: a re-run the same day is free).
 5. Cross-sectional scoring -> composite -> persist scores.
 6. Signal generation (entry rules) -> persist signals.
"""

from __future__ import annotations

import argparse
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import pandas as pd

from atlas.config import get_config
from atlas.data.store import (get_ohlcv_batch_cached, init_db, save_scores,
                              save_signals)
from atlas.data.yahoo import YahooProvider
from atlas.data.fred import fetch_macro_series
from atlas.features.fundamental import fundamental_factors
from atlas.features.momentum import momentum_factors
from atlas.features.regime import detect_regime
from atlas.features.sector import sector_scores, stock_sector_score
from atlas.features.sentiment import get_sentiment_provider
from atlas.features.technical import technical_score, technical_snapshot
from atlas.scoring.composite import composite_score, fundamental_score, momentum_overlay
from atlas.signals.generator import generate_signals
from atlas.universe.loader import build_universe, filter_liquidity
from atlas.learning.feedback import hit_rate_by_score_bucket

log = logging.getLogger(__name__)

# 2 workers maximum: au-dela, Yahoo repond "Too Many Requests" apres ~1 min
# et renvoie des fondamentaux vides pour le reste de l'univers.
FUNDAMENTALS_WORKERS = 2
CHUNK_PAUSE_S = 3.0


def _load_fundamentals(liquid: list[str], provider: YahooProvider,
                       as_of: str) -> pd.DataFrame:
    """Parallel fundamentals fetch with a per-day parquet cache."""
    cache_file = get_config().cache_dir / f"fundamentals_{as_of}.parquet"
    cached = pd.DataFrame()
    if cache_file.exists():
        cached = pd.read_parquet(cache_file)
        # Purge des lignes vides (echecs de rate-limit d'un run precedent):
        # elles repassent dans la liste a telecharger.
        key_cols = [c for c in ("roe", "pe", "market_cap", "gross_margin")
                    if c in cached.columns]
        if key_cols:
            usable = cached[key_cols].notna().any(axis=1)
            if (~usable).any():
                log.info("fondamentaux: purge de %d lignes vides du cache",
                         int((~usable).sum()))
            cached = cached[usable]
    missing = [t for t in liquid if t not in cached.index]
    if missing:
        log.info("fondamentaux: %d en cache, %d a telecharger (%d workers)",
                 len(cached), len(missing), FUNDAMENTALS_WORKERS)

        def fetch(t: str) -> dict:
            return fundamental_factors(provider.get_fundamentals(t))

        # Checkpoint toutes les 50 valeurs: un run interrompu reprend ou il
        # s'est arrete au lieu de tout re-telecharger.
        import time

        chunk_size = 50
        with ThreadPoolExecutor(max_workers=FUNDAMENTALS_WORKERS) as pool:
            for i in range(0, len(missing), chunk_size):
                chunk = missing[i:i + chunk_size]
                rows = list(pool.map(fetch, chunk))
                cached = pd.concat([cached, pd.DataFrame(rows).set_index("ticker")])
                cached.to_parquet(cache_file)
                log.info("fondamentaux: %d/%d", min(i + chunk_size, len(missing)),
                         len(missing))
                if i + chunk_size < len(missing):
                    time.sleep(CHUNK_PAUSE_S)
    return cached.loc[cached.index.intersection(liquid)]


def run(limit: int | None = None, refresh_universe: bool = False) -> dict:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    init_db()
    cfg = get_config()
    provider = YahooProvider()
    as_of = str(date.today())
    start = str(date.today() - timedelta(days=365 * int(cfg.data.get("history_years", 25))))

    # 1. Universe + prices (batch download, cache-first)
    tickers = build_universe(refresh=refresh_universe)
    if limit:
        tickers = tickers[:limit]
    log.info("chargement OHLCV pour %d tickers...", len(tickers))
    prices = get_ohlcv_batch_cached(tickers, provider, start=start)
    prices = {t: df for t, df in prices.items() if not df.empty}

    # 2. Liquidity filter
    liquid = filter_liquidity(prices)
    log.info("filtre liquidite: %d -> %d tickers", len(prices), len(liquid))

    # Entretien du cache des noms de societes (manquants seulement, plafonne)
    try:
        from atlas.data.names import ensure_names
        ensure_names(liquid)
    except Exception as exc:
        log.warning("maj noms societes echouee (non bloquant): %s", exc)

    # 3. Macro + sectors
    macro_series = fetch_macro_series()
    macro_state = detect_regime(macro_series)
    bench_ticker = cfg.sectors.get("benchmark", "SPY")
    etf_tickers = list(cfg.sectors.get("etfs", {}).values())
    etf_prices = get_ohlcv_batch_cached(etf_tickers + [bench_ticker], provider,
                                        start=start)
    bench = etf_prices.get(bench_ticker, pd.DataFrame())
    sectors_df = sector_scores(etf_prices, bench)
    if not sectors_df.empty:
        log.info("rotation sectorielle:\n%s", sectors_df["score"].to_string())

    # 4. Per-ticker features
    fund_df = _load_fundamentals(liquid, provider, as_of)
    sentiment = get_sentiment_provider()
    bench_close = bench["close"] if not bench.empty else pd.Series(dtype=float)
    tech_scores, mom_rows, sent_scores, sector_pillar = {}, [], {}, {}
    for t in liquid:
        df = prices[t]
        snap = technical_snapshot(df)
        tech_scores[t] = technical_score(snap)
        mom = momentum_factors(df["close"], bench_close)
        mom["ticker"] = t
        mom_rows.append(mom)
        sector_name = fund_df["sector_name"].get(t) if "sector_name" in fund_df else None
        sector_pillar[t] = stock_sector_score(sector_name, sectors_df)
        sent_scores[t] = sentiment.score_ticker(t).score

    mom_df = pd.DataFrame(mom_rows).set_index("ticker")

    # 5. Cross-sectional scoring. Piliers macro/sentiment passes a None quand
    # la donnee n'existe pas: leur poids est renormalise (voir composite.py).
    fund_pillar = fundamental_score(fund_df)
    tech_pillar = (0.7 * pd.Series(tech_scores)
                   + 0.3 * momentum_overlay(mom_df)).round(1)
    scores = composite_score(
        fundamental=fund_pillar,
        technical=tech_pillar,
        sector=pd.Series(sector_pillar),
        macro=macro_state.equity_score if macro_series else None,
        sentiment=(pd.Series(sent_scores) if sentiment.name != "neutral" else None),
    )
    scores["sector_name"] = fund_df["sector_name"]
    scores["country"] = fund_df["country"]
    save_scores(scores, as_of)
    log.info("top 10 scores:\n%s", scores["composite"].head(10).to_string())

    # 6. Signals
    signals = generate_signals(scores, prices,
                               hit_rates=hit_rate_by_score_bucket())
    save_signals([s.to_dict() for s in signals], as_of)
    for s in signals[:10]:
        log.info("SIGNAL %s: entree %.2f stop %.2f TP %.2f/%.2f/%.2f score %.0f (%s)",
                 s.ticker, s.entry, s.stop, s.tp1, s.tp2, s.tp3,
                 s.composite_score, s.confidence)

    return {"as_of": as_of, "universe": len(tickers), "scored": len(scores),
            "signals": len(signals), "regime": macro_state.regime.value}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ATLAS daily scan")
    parser.add_argument("--limit", type=int, default=None,
                        help="limiter le nombre de tickers (test rapide)")
    parser.add_argument("--refresh-universe", action="store_true")
    args = parser.parse_args()
    summary = run(limit=args.limit, refresh_universe=args.refresh_universe)
    print(summary)
