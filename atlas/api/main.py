"""REST API (FastAPI). Read endpoints over the SQL store + pipeline triggers.

Run:  uvicorn atlas.api.main:app --reload --port 8000
Docs: http://localhost:8000/docs
"""

from __future__ import annotations

import json

import pandas as pd
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query

from atlas import __version__
from atlas.data.store import read_table
from atlas.learning.feedback import factor_decay_report, propose_weight_update

app = FastAPI(
    title="ATLAS API",
    version=__version__,
    description="Global equity quant platform: scores, signaux, portefeuille, risque.",
)


def _df_json(df: pd.DataFrame) -> list[dict]:
    return json.loads(df.to_json(orient="records", date_format="iso"))


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "version": __version__}


@app.get("/scores")
def scores(limit: int = Query(50, le=500), min_composite: float = 0.0) -> list[dict]:
    df = read_table("scores")
    if df.empty:
        return []
    latest = df[df["as_of_date"] == df["as_of_date"].max()]
    latest = latest[latest["composite"] >= min_composite]
    return _df_json(latest.sort_values("composite", ascending=False).head(limit))


@app.get("/signals")
def signals(status: str | None = None, limit: int = Query(50, le=500)) -> list[dict]:
    df = read_table("signals")
    if df.empty:
        return []
    if status:
        df = df[df["status"] == status]
    return _df_json(df.sort_values("created_at", ascending=False).head(limit))


@app.get("/portfolio")
def portfolio() -> dict:
    positions = read_table("positions")
    trades = read_table("trades")
    realized = float(trades["pnl"].sum()) if not trades.empty else 0.0
    return {
        "positions": _df_json(positions),
        "n_positions": len(positions),
        "realized_pnl": realized,
        "n_closed_trades": len(trades),
    }


@app.get("/trades")
def trades(limit: int = Query(100, le=1000)) -> list[dict]:
    df = read_table("trades")
    if df.empty:
        return []
    return _df_json(df.sort_values("closed_at", ascending=False).head(limit))


@app.get("/backtests")
def backtests() -> list[dict]:
    df = read_table("backtests")
    if df.empty:
        return []
    out = df[["id", "created_at", "name", "metrics"]].copy()
    out["metrics"] = out["metrics"].apply(lambda m: json.loads(m) if m else {})
    return _df_json(out.sort_values("created_at", ascending=False))


@app.get("/backtests/{backtest_id}/equity")
def backtest_equity(backtest_id: int) -> dict:
    df = read_table("backtests")
    row = df[df["id"] == backtest_id]
    if row.empty:
        raise HTTPException(404, "backtest introuvable")
    return {"id": backtest_id, "equity_curve": json.loads(row.iloc[0]["equity_curve"])}


@app.get("/learning/factor-decay")
def factor_decay() -> dict:
    df = factor_decay_report()
    if df.empty:
        return {"message": "pas encore assez d'historique d'IC facteurs"}
    return json.loads(df.tail(24).to_json(date_format="iso"))


@app.get("/learning/weight-proposal")
def weight_proposal() -> dict:
    return propose_weight_update()


@app.post("/pipelines/daily-scan")
def trigger_daily_scan(background: BackgroundTasks, limit: int | None = None) -> dict:
    from atlas.pipelines.daily_scan import run
    background.add_task(run, limit=limit)
    return {"status": "started", "limit": limit}
