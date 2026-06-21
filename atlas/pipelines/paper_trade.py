"""Paper execution pipeline (Phase 1 du GO_LIVE).

Run:  python -m atlas.pipelines.paper_trade

Methodologie alignee sur le backtest: un signal genere a la cloture du jour J
est execute a l'OUVERTURE de la seance suivante (J+1), pas au cours du jour
meme. Les signaux du jour restent donc 'new' jusqu'au prochain run; ceux
restes inexecutables 7 jours expirent.

1. Sorties: stops et trailing stops sur les positions ouvertes (cours locaux).
2. Entrees: signaux 'new' des jours precedents, executes a l'ouverture J+1,
   sizes par risque en USD (conversion de devise) et ajustes du regime macro.
3. Equity du jour (USD) en table paper_equity + rapport de risque.
"""

from __future__ import annotations

import logging
import math
from datetime import date

import pandas as pd
from sqlalchemy import text

from atlas.config import get_config
from atlas.data.fred import fetch_macro_series
from atlas.data.fx import currency_of, get_usd_rates, to_usd
from atlas.data.store import init_db, load_ohlcv, read_table
from atlas.execution.base import Order, OrderSide, OrderType
from atlas.execution.paper import PaperBroker
from atlas.features.regime import detect_regime
from atlas.portfolio.risk import evaluate_risk
from atlas.portfolio.sizing import risk_based_size
from atlas.signals.generator import check_exits

log = logging.getLogger(__name__)

SIGNAL_EXPIRY_DAYS = 7


def first_bar_after(df: pd.DataFrame, as_of: str) -> pd.Series | None:
    """First session bar strictly after the signal date (the J+1 open)."""
    if df is None or df.empty:
        return None
    after = df[df.index > pd.Timestamp(as_of)]
    return after.iloc[0] if len(after) else None


def _last_trade_pnl(engine, ticker: str) -> float | None:
    """P&L (USD) du dernier trade cloture pour ce ticker."""
    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT pnl FROM trades WHERE ticker=:t ORDER BY id DESC LIMIT 1"),
            {"t": ticker}).fetchone()
    return float(row[0]) if row and row[0] is not None else None


def _marks_usd(tickers, rates: dict[str, float]) -> dict[str, float]:
    """Dernier cours converti en USD pour chaque ticker. Ignore les cours
    NaN (ex: barre d'un jour ferie) pour ne pas contaminer l'equity."""
    out = {}
    for t in tickers:
        df = load_ohlcv(t)
        if not df.empty:
            px = float(df["close"].iloc[-1])
            if math.isfinite(px):
                out[t] = to_usd(px, currency_of(t), rates)
    return out


def run() -> dict:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    engine = init_db()
    broker = PaperBroker()
    cfg = get_config().portfolio
    rates = get_usd_rates()
    today = str(date.today())
    summary: dict = {"sells": 0, "buys": 0, "trail_updates": 0,
                     "expired": 0, "pending": 0}
    changes: list[str] = []  # mouvements reels (ouverture/cloture) -> Telegram

    # 1. Sorties sur les positions ouvertes (stops en devise locale)
    positions = read_table("positions")
    if not positions.empty:
        price_frames = {t: load_ohlcv(t) for t in positions["ticker"]}
        for ex in check_exits(positions, price_frames):
            if ex["side"] == "sell":
                cur = currency_of(ex["ticker"])
                order = broker.submit_order(
                    Order(ex["ticker"], OrderSide.SELL, ex["qty"], OrderType.MARKET),
                    reference_price=ex["price"],
                    fx_rate=rates.get(cur, 1.0), currency=cur)
                if order.status.value == "filled":
                    summary["sells"] += 1
                    pnl = _last_trade_pnl(engine, ex["ticker"])
                    pnl_txt = f", P&L {pnl:+,.0f} USD" if pnl is not None else ""
                    changes.append(
                        f"VENTE {ex['ticker']} x{ex['qty']:.0f} @ "
                        f"{order.filled_price:.2f} ({ex['reason']}){pnl_txt}")
            elif ex["side"] == "update_stop":
                with engine.begin() as conn:
                    conn.execute(text(
                        "UPDATE positions SET trailing_stop=:ts WHERE ticker=:t"
                        " AND (trailing_stop IS NULL OR trailing_stop < :ts)"),
                        {"ts": ex["trailing_stop"], "t": ex["ticker"]})
                summary["trail_updates"] += 1

    # 2. Entrees: signaux des jours PRECEDENTS, executes a l'ouverture J+1
    signals = read_table("signals")
    positions = read_table("positions")
    held = set(positions["ticker"]) if not positions.empty else set()
    max_pos = int(cfg.get("max_positions", 25))
    max_sector = float(cfg.get("max_weight_per_sector", 0.25))
    macro_series = fetch_macro_series()
    modifier = detect_regime(macro_series).exposure_modifier if macro_series else 1.0
    equity = broker.get_equity(_marks_usd(held, rates))

    sector_of: dict[str, str] = {}
    scores_all = read_table("scores")
    if not scores_all.empty:
        latest = scores_all[scores_all["as_of_date"] == scores_all["as_of_date"].max()]
        sector_of = dict(zip(latest["ticker"], latest["sector_name"].fillna("Unknown")))
    sector_value: dict[str, float] = {}
    if not positions.empty:
        marks = _marks_usd(positions["ticker"], rates)
        for _, pos in positions.iterrows():
            sec = sector_of.get(pos["ticker"], "Unknown")
            px = marks.get(pos["ticker"],
                           float(pos["avg_price"]) * float(pos.get("fx_entry") or 1.0))
            sector_value[sec] = sector_value.get(sec, 0.0) + float(pos["qty"]) * px

    if not signals.empty:
        todo = signals[signals["status"] == "new"].sort_values(
            "composite_score", ascending=False)
        for _, sig in todo.iterrows():
            ticker = sig["ticker"]
            # Signal du jour: la seance J+1 n'existe pas encore, on attend.
            if sig["as_of_date"] >= today:
                summary["pending"] += 1
                continue
            bar = first_bar_after(load_ohlcv(ticker), sig["as_of_date"])
            age_days = (pd.Timestamp(today) - pd.Timestamp(sig["as_of_date"])).days
            if bar is None:
                new_status = "expired" if age_days > SIGNAL_EXPIRY_DAYS else None
                if new_status is None:
                    summary["pending"] += 1
                    continue
            else:
                open_px = float(bar["open"])           # ouverture J+1, locale
                # Barre sans cours valide (jour ferie/donnee manquante):
                # on n'execute pas et on n'expire pas, on reessaie au prochain run.
                if not math.isfinite(open_px) or open_px <= 0:
                    summary["pending"] += 1
                    continue
                new_status = "expired"
                cur = currency_of(ticker)
                fx = rates.get(cur, 1.0)
                entry_usd = open_px * fx
                stop_usd = float(sig["stop"]) * fx
                sec = sector_of.get(ticker, "Unknown")
                if ticker not in held and len(held) < max_pos \
                        and entry_usd > stop_usd:
                    qty = risk_based_size(equity, entry_usd, stop_usd, modifier)
                    cand_value = qty * entry_usd
                    if qty > 0 and (sector_value.get(sec, 0.0) + cand_value) \
                            > max_sector * equity:
                        log.info("skip %s: secteur %s deja a %.1f%% (max %.0f%%)",
                                 ticker, sec,
                                 100 * sector_value.get(sec, 0.0) / equity,
                                 100 * max_sector)
                        qty = 0
                    if qty > 0:
                        order = broker.submit_order(
                            Order(ticker, OrderSide.BUY, qty),
                            reference_price=open_px, fx_rate=fx, currency=cur)
                        if order.status.value == "filled":
                            with engine.begin() as conn:
                                conn.execute(text(
                                    "UPDATE positions SET stop=:s,"
                                    " trailing_stop=:ts, signal_id=:sid"
                                    " WHERE ticker=:t"),
                                    {"s": float(sig["stop"]),
                                     "ts": float(sig["stop"]),
                                     "sid": int(sig["id"]), "t": ticker})
                            held.add(ticker)
                            sector_value[sec] = sector_value.get(sec, 0.0) + cand_value
                            summary["buys"] += 1
                            new_status = "executed"
                            changes.append(
                                f"ACHAT {ticker} x{qty:.0f} @ "
                                f"{order.filled_price:.2f} {cur} "
                                f"(score {float(sig['composite_score']):.0f}, "
                                f"stop {float(sig['stop']):.2f})")
            if new_status == "expired":
                summary["expired"] += 1
            with engine.begin() as conn:
                conn.execute(text("UPDATE signals SET status=:st WHERE id=:id"),
                             {"st": new_status, "id": int(sig["id"])})

    # 3. Equity du jour + rapport de risque (tout en USD)
    positions = read_table("positions")
    marks = _marks_usd(positions["ticker"], rates) if not positions.empty else {}
    equity = broker.get_equity(marks)
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS paper_equity"
            " (date TEXT PRIMARY KEY, equity REAL)"))
        conn.execute(text(
            "INSERT OR REPLACE INTO paper_equity (date, equity) VALUES (:d, :e)"),
            {"d": today, "e": equity})
        rows = conn.execute(text(
            "SELECT date, equity FROM paper_equity ORDER BY date")).fetchall()
    eq_curve = pd.Series({pd.Timestamp(r[0]): float(r[1]) for r in rows})

    if not positions.empty:
        fx_entry = positions.get("fx_entry", pd.Series(1.0, index=positions.index))
        risk_pos = positions.assign(
            avg_price=positions["avg_price"] * fx_entry.fillna(1.0),
            last_price=[marks.get(t, float(p) * float(f or 1.0))
                        for t, p, f in zip(positions["ticker"],
                                           positions["avg_price"],
                                           fx_entry.fillna(1.0))])
        closes = {}
        for t in positions["ticker"]:
            df = load_ohlcv(t)
            if not df.empty:
                closes[t] = df["close"].iloc[-90:]
        rets = pd.DataFrame(closes).pct_change().dropna() if closes else None
        sectors = countries = None
        if not scores_all.empty:
            latest = scores_all[scores_all["as_of_date"] == scores_all["as_of_date"].max()]
            latest = latest.drop_duplicates("ticker").set_index("ticker")
            sectors, countries = latest["sector_name"], latest["country"]
        report = evaluate_risk(eq_curve, risk_pos, rets, sectors, countries)
        summary["risk_actions"] = [
            f"{a.action.value}: {a.reason}" for a in report.actions]

    summary["equity"] = round(equity, 2)
    summary["open_positions"] = len(positions)

    # Notification Telegram des mouvements REELS (vous + Darius). Ne part que
    # s'il y a eu au moins une ouverture ou cloture; best-effort.
    if changes:
        msg = (f"ATLAS - mouvements du portefeuille ({today})\n"
               + "\n".join(changes)
               + f"\n\nEquity: {equity:,.0f} USD | "
               f"{summary['open_positions']} positions")
        try:
            from atlas.monitoring.notify import send
            send(msg)
        except Exception as exc:
            log.warning("notification mouvements echouee: %s", exc)

    log.info("paper trade: %s", summary)
    return summary


if __name__ == "__main__":
    print(run())
