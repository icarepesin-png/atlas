"""Backtest CLI.

Run:  python -m atlas.pipelines.run_backtest [--limit 100] [--start 2005-01-01]
      [--validate]  (walk-forward + Monte Carlo + stress tests)

Uses the price-only momentum/quality proxy strategy (point-in-time safe).
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import date, timedelta

import pandas as pd

from atlas.backtest.engine import momentum_strategy, run_backtest
from atlas.backtest.metrics import full_report
from atlas.backtest.validation import (monte_carlo, parameter_sensitivity,
                                       stress_tests, walk_forward)
from atlas.config import get_config
from atlas.data.store import get_ohlcv_cached, init_db, save_backtest
from atlas.data.yahoo import YahooProvider
from atlas.universe.loader import build_universe

log = logging.getLogger(__name__)


def load_close_matrix(tickers: list[str], start: str) -> pd.DataFrame:
    provider = YahooProvider()
    closes = {}
    for t in tickers:
        df = get_ohlcv_cached(t, provider, start=start)
        if not df.empty and len(df) > 252:
            closes[t] = df["close"]
    return pd.DataFrame(closes).dropna(how="all")


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="ATLAS backtest")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--start", type=str, default=None)
    parser.add_argument("--top-n", type=int, default=20)
    parser.add_argument("--validate", action="store_true",
                        help="walk-forward + Monte Carlo + stress tests")
    args = parser.parse_args()

    init_db()
    cfg = get_config()
    start = args.start or cfg.backtest.get("start", "2000-01-01")
    hist_start = str(pd.Timestamp(start) - pd.DateOffset(years=2))[:10]

    tickers = build_universe()[: args.limit]
    log.info("chargement de %d tickers depuis %s...", len(tickers), hist_start)
    closes = load_close_matrix(tickers, hist_start)
    log.info("matrice de prix: %s", str(closes.shape))

    strategy = momentum_strategy(top_n=args.top_n)
    bt = run_backtest(closes, strategy, start=start, name="momentum_quality_proxy")

    bench_t = cfg.backtest.get("benchmark", "SPY")
    bench = get_ohlcv_cached(bench_t, YahooProvider(), start=hist_start)
    bench_eq = bench["close"].reindex(bt.equity.index).ffill() if not bench.empty else None

    metrics = full_report(bt.equity, bench_eq)
    print("\n=== METRIQUES ===")
    print(json.dumps(metrics, indent=2))
    print(f"couts totaux payes: {bt.costs_paid}")
    if bt.params.get("risk_overlay"):
        print(f"risk overlay: {bt.days_derisked} jours en exposition reduite, "
              f"exposition minimale {bt.min_exposure:.0%}")

    results = {"metrics": metrics}
    if args.validate:
        print("\n=== WALK-FORWARD ===")
        wf = walk_forward(closes, strategy)
        print(json.dumps(wf.summary(), indent=2))
        results["walk_forward"] = wf.summary()

        print("\n=== MONTE CARLO ===")
        mc = monte_carlo(bt.equity)
        print(json.dumps(mc, indent=2))
        results["monte_carlo"] = mc

        print("\n=== STRESS TESTS ===")
        st = stress_tests(closes, strategy)
        print(json.dumps(st, indent=2))
        results["stress_tests"] = st

        print("\n=== SENSIBILITE DES PARAMETRES ===")
        sens = parameter_sensitivity(closes, base_top_n=args.top_n, start=start)
        print(json.dumps({k: v for k, v in sens.items() if k != "grid"},
                         indent=2))
        results["sensitivity"] = sens

    save_backtest("momentum_quality_proxy", bt.params, results, bt.equity)
    log.info("backtest sauvegarde dans la base.")


if __name__ == "__main__":
    main()
