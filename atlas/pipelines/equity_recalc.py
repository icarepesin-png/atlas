# -*- coding: utf-8 -*-
"""Courbe d'equity reconstruite a partir des ordres et des cours de cloture.

La table paper_equity est ecrite au fil des runs, donc elle herite de leurs
accidents: jours ou le PC etait eteint (trous), runs lances un samedi (points
dates du week-end), runs lances en pleine seance (valorisation sur un cours
de passage), runs repetes sur les memes cours (doublons). En campagne 2, cela
donnait 43 points pour 54 seances, dont 6 un week-end et 5 doublons.

Ici la courbe est RECALCULEE: on rejoue les ordres executes, campagne par
campagne, et on valorise chaque seance americaine a sa vraie cloture. Le
resultat ne depend plus de l'heure ni du jour ou les runs ont tourne, et il
se repare tout seul: appele a la fin de chaque run, il comble les trous des
jours manques des que les cours sont la.

Run:  python -m atlas.pipelines.equity_recalc
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import text

from atlas.config import get_config
from atlas.data.fx import FX_PAIRS, currency_of
from atlas.data.markets import (is_session_day, market_by_code,
                                seance_de_reference)
from atlas.data.store import init_db, load_ohlcv

log = logging.getLogger(__name__)


def _series_fx(depuis: pd.Timestamp | None = None) -> dict[str, pd.Series]:
    """Historique de chaque taux de change, assez profond pour la periode.

    Le run quotidien ne conserve que quelques semaines de taux (il n'a besoin
    que du dernier). Rejouer une campagne ancienne exige tout l'historique:
    sans lui, une action Shell a 3 371 pence etait comptee 3 371 dollars.
    """
    if depuis is not None:
        courtes = []
        for paire in FX_PAIRS.values():
            df = load_ohlcv(paire)
            if df.empty or df.index.min() > depuis + pd.Timedelta(days=5):
                courtes.append(paire)
        if courtes:
            try:
                from atlas.data.store import save_ohlcv
                from atlas.data.yahoo import YahooProvider

                debut = str((depuis - pd.Timedelta(days=15)).date())
                for paire, df in YahooProvider().get_ohlcv_batch(
                        courtes, start=debut).items():
                    if df is not None and not df.empty:
                        save_ohlcv(paire, df)
            except Exception as exc:  # noqa: BLE001
                log.warning("historique de change incomplet: %s", exc)
    out: dict[str, pd.Series] = {}
    for devise, paire in FX_PAIRS.items():
        df = load_ohlcv(paire)
        if not df.empty:
            out[devise] = df["close"]
    if "GBP" in out:
        out["GBp"] = out["GBP"] / 100.0
    return out


def _taux(fx: dict[str, pd.Series], devise: str, jour: pd.Timestamp) -> float:
    """Taux de conversion vers l'USD a une date.

    Jamais de repli silencieux sur 1,0 pour une devise etrangere: pour des
    pence, l'erreur serait d'un facteur 100. Faute de taux a la date, on prend
    le plus ancien connu, et faute de tout historique on le signale.
    """
    if devise == "USD":
        return 1.0
    s = fx.get(devise)
    if s is None or s.empty:
        log.warning("aucun taux de change pour %s: montant compte a 1,0", devise)
        return 1.0
    dispo = s.loc[s.index <= jour]
    return float(dispo.iloc[-1]) if len(dispo) else float(s.iloc[0])


def seance_d_un_ordre(seance: str | None, execute_le: str) -> pd.Timestamp:
    """Seance a laquelle rattacher un ordre.

    Les ordres recents portent leur seance. Pour les anciens, on la deduit de
    l'horodatage: un run traite la derniere seance americaine close au moment
    ou il tourne (un ordre passe le samedi appartient a la seance de vendredi).
    """
    if seance:
        return pd.Timestamp(seance)
    quand = pd.Timestamp(execute_le)
    if quand.tzinfo is None:
        quand = quand.tz_localize(timezone.utc)
    return pd.Timestamp(seance_de_reference(quand.to_pydatetime()))


def reconstruire(engine, campagne: int, capital: float,
                 debut: str | None = None, fin: str | None = None) -> pd.DataFrame:
    """Equity seance par seance d'une campagne."""
    with engine.connect() as conn:
        ordres = conn.execute(text(
            "SELECT ticker, side, qty, filled_price, filled_at, seance FROM orders"
            " WHERE status='filled' AND COALESCE(campagne, 1) = :c"
            " ORDER BY filled_at, id"), {"c": campagne}).fetchall()

    mouvements = sorted(
        ((seance_d_un_ordre(seance, quand), ticker, side, float(qty), float(prix))
         for ticker, side, qty, prix, quand, seance in ordres),
        key=lambda m: m[0])

    us = market_by_code("US")
    premier = pd.Timestamp(debut[:10]) if debut else (
        mouvements[0][0] if mouvements else None)
    if premier is None:
        return pd.DataFrame()
    dernier = pd.Timestamp(seance_de_reference())
    if fin:
        dernier = min(dernier, pd.Timestamp(fin[:10]))
    jours = [j for j in pd.bdate_range(premier, dernier)
             if is_session_day(us, j.date())]

    fx = _series_fx(depuis=premier)
    cours = {t: load_ohlcv(t) for t in {m[1] for m in mouvements}}
    cash = capital
    detenu: dict[str, float] = defaultdict(float)
    i, lignes = 0, []
    for jour in jours:
        while i < len(mouvements) and mouvements[i][0] <= jour:
            _, ticker, side, qty, prix = mouvements[i]
            taux = _taux(fx, currency_of(ticker), jour)
            if side == "buy":
                cash -= prix * qty * taux
                detenu[ticker] += qty
            else:
                cash += prix * qty * taux
                detenu[ticker] -= qty
                if abs(detenu[ticker]) < 1e-9:
                    detenu.pop(ticker, None)
            i += 1
        valeur = 0.0
        for ticker, qty in detenu.items():
            df = cours.get(ticker)
            dispo = df.loc[df.index <= jour] if df is not None and not df.empty else None
            if dispo is None or dispo.empty:
                continue
            valeur += (float(dispo["close"].iloc[-1]) * qty
                       * _taux(fx, currency_of(ticker), jour))
        lignes.append({"date": jour.date().isoformat(), "equity": cash + valeur,
                       "cash": cash, "positions": len(detenu),
                       "campagne": campagne})
    return pd.DataFrame(lignes)


def run() -> dict:
    """Recalcule toutes les campagnes et remplace paper_equity_recalc."""
    engine = init_db()
    capital = float(get_config().backtest.get("initial_capital", 100_000))
    with engine.connect() as conn:
        campagnes = conn.execute(text(
            "SELECT id, debut, fin FROM campagnes ORDER BY id")).fetchall()
    if not campagnes:
        campagnes = [(1, None, None)]

    lots = [reconstruire(engine, int(cid), capital, debut, fin)
            for cid, debut, fin in campagnes]
    lots = [df for df in lots if not df.empty]
    if not lots:
        return {"status": "vide"}
    tout = pd.concat(lots, ignore_index=True)

    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS paper_equity_recalc"))
        conn.execute(text(
            "CREATE TABLE paper_equity_recalc (date TEXT, equity REAL,"
            " cash REAL, positions INTEGER, campagne INTEGER,"
            " PRIMARY KEY (campagne, date))"))
        conn.execute(text(
            "INSERT INTO paper_equity_recalc (date, equity, cash, positions,"
            " campagne) VALUES (:date, :equity, :cash, :positions, :campagne)"),
            tout.to_dict("records"))
    resume = {"status": "ok", "calcule_le": datetime.now(timezone.utc).isoformat()}
    for cid, grp in tout.groupby("campagne"):
        resume[f"campagne_{cid}"] = {"seances": len(grp),
                                     "equity": round(float(grp.equity.iloc[-1]), 2)}
    log.info("equity recalculee: %s", resume)
    return resume


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    print(run())
