# -*- coding: utf-8 -*-
"""Rejoue les entrees REELLES avec differentes regles de sortie.

Pourquoi: le backtest de docs/BACKTEST.md simule un portefeuille rebalance
mensuellement, SANS stop ni take-profit - autrement dit une autre strategie
que celle qui tourne en paper. Ses 15% de CAGR ne disent donc rien des
regles de sortie reellement appliquees.

Ici on ne touche pas au choix des titres (memes entrees, memes dates: aucun
biais de selection) et on ne fait varier QUE la sortie. Les positions encore
ouvertes sont incluses, valorisees au dernier cours: ne garder que les trades
clotures reviendrait a n'etudier que ceux qui ont touche un stop.

  python scripts/simuler_regles_sortie.py
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

import pandas as pd

from atlas.config import get_config
from atlas.data.store import load_ohlcv
from atlas.features.technical import atr


@dataclass
class Regle:
    nom: str
    stop_mult: float = 2.0
    trail_mult: float = 2.75
    tp_r: float | None = None        # objectif en multiples de R
    tp_part: float = 1 / 3           # fraction vendue a l'objectif
    duree_max: int | None = None     # sortie forcee apres N seances


def rejouer(entree: float, a: float, barres: pd.DataFrame, r: Regle) -> float:
    """Rendement en % d'une position, selon la regle de sortie."""
    stop = entree - r.stop_mult * a
    plus_haut = entree
    reste = 1.0
    acquis = 0.0
    R = r.stop_mult * a
    for i, (_, b) in enumerate(barres.iterrows()):
        haut, bas, cloture = float(b["high"]), float(b["low"]), float(b["close"])
        if not (haut > 0 and bas > 0 and cloture > 0):
            continue
        # 1. objectif partiel touche dans la seance
        if r.tp_r and reste > 1 - r.tp_part:
            cible = entree + r.tp_r * R
            if haut >= cible:
                acquis += r.tp_part * (cible / entree - 1)
                reste -= r.tp_part
        # 2. stop effectif (le plus haut des deux), evalue a la cloture
        plus_haut = max(plus_haut, haut)
        effectif = max(stop, plus_haut - r.trail_mult * a)
        if cloture <= effectif:
            return acquis + reste * (cloture / entree - 1)
        # 3. sortie temporelle
        if r.duree_max and i + 1 >= r.duree_max:
            return acquis + reste * (cloture / entree - 1)
    return acquis + reste * (float(barres["close"].iloc[-1]) / entree - 1)


def positions_prises(con) -> list[dict]:
    """Toutes les entrees reelles: trades clotures + positions ouvertes."""
    lot = []
    for tk, qty, px, ouvert in con.execute(
            "SELECT ticker, qty, entry_price, opened_at FROM trades"):
        lot.append({"ticker": tk, "qty": qty, "entree": px, "ouvert": ouvert})
    for tk, qty, px, ouvert in con.execute(
            "SELECT ticker, qty, avg_price, opened_at FROM positions"):
        lot.append({"ticker": tk, "qty": qty, "entree": px, "ouvert": ouvert})
    return lot


def main() -> None:
    cfg = get_config().signals
    con = sqlite3.connect("atlas.db")
    lot = positions_prises(con)

    regles = [
        Regle("ACTUELLE (stop 2 ATR, trail 2.75)"),
        Regle("+ prise partielle a 1.5R", tp_r=1.5),
        Regle("+ prise partielle a 1.0R", tp_r=1.0),
        Regle("trailing serre 2.0 ATR", trail_mult=2.0),
        Regle("trailing serre 1.5 ATR", trail_mult=1.5),
        Regle("trailing large 3.5 ATR", trail_mult=3.5),
        Regle("stop serre 1.5 ATR", stop_mult=1.5),
        Regle("trail 2.0 + partielle 1.5R", trail_mult=2.0, tp_r=1.5),
        Regle("sortie forcee a 20 seances", duree_max=20),
    ]

    cas = []
    for p in lot:
        df = load_ohlcv(p["ticker"])
        if df.empty:
            continue
        ouv = pd.to_datetime(p["ouvert"], format="mixed", utc=True) \
            .tz_convert(None).normalize()
        avant = df.loc[df.index < ouv]
        apres = df.loc[df.index >= ouv]
        if len(avant) < 20 or apres.empty:
            continue
        a = float(atr(avant).iloc[-1])
        if not (a > 0) or p["entree"] <= 0:
            continue
        cas.append({"ticker": p["ticker"], "entree": float(p["entree"]),
                    "atr": a, "barres": apres,
                    "capital": float(p["entree"]) * float(p["qty"])})

    print(f"=== {len(cas)} entrees rejouees "
          f"(trades clotures + positions ouvertes) ===")
    print(f"    stop actuel: {cfg.get('stop_atr_multiple')} ATR | "
          f"trailing: {cfg.get('trailing_atr_multiple')} ATR\n")
    print(f"{'regle de sortie':38} {'PnL total':>11} {'moyenne':>9} "
          f"{'gagnants':>9}")
    base = None
    for r in regles:
        rendements, pnl = [], 0.0
        for c in cas:
            ret = rejouer(c["entree"], c["atr"], c["barres"], r)
            rendements.append(ret)
            pnl += ret * c["capital"]
        s = pd.Series(rendements)
        if base is None:
            base = pnl
        ecart = f"  ({pnl - base:+,.0f})" if r is not regles[0] else ""
        print(f"{r.nom:38} {pnl:+11,.0f} {100*s.mean():+8.2f}% "
              f"{100*(s > 0).mean():8.0f}%{ecart}")

    print("\n  PnL en USD sur le capital reellement engage. La regle ACTUELLE")
    print("  sert de reference; les ecarts sont entre parentheses.")


if __name__ == "__main__":
    main()
