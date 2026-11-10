# -*- coding: utf-8 -*-
"""Backtest FIDELE: simule les regles qui tournent reellement en paper.

L'ancien moteur (engine.py) simule un portefeuille de 20 titres equiponderes
rebalance chaque mois, sans stop ni objectif. Le systeme reel, lui, achete
sur signal, dimensionne par le risque et sort sur stop: ce sont deux
strategies differentes, et les 15% de CAGR de l'un ne disaient rien de
l'autre. Ce moteur-ci reproduit, jour par jour, la mecanique de
atlas/pipelines/paper_trade.py et atlas/signals/generator.py:

  cloture J    : classement des titres de l'indice, les mieux notes deviennent
                 des signaux; stop initial = cloture - 2 ATR.
  ouverture J+1: achat (glissement inclus) si le titre n'est ni detenu ni en
                 carence, taille = risque 0,5% du capital / distance au stop,
                 plafonnee a 5% du capital.
  cloture      : prise partielle d'un tiers a +1,5R; sinon sortie si la
                 cloture passe sous le stop effectif (stop initial ou stop
                 suiveur a 2,75 ATR sous le plus haut depuis l'entree).
  apres perte  : le titre est interdit de rachat pendant 20 jours.

Ecarts assumes avec le reel, a garder en tete en lisant les resultats:
- pas de plafond sectoriel (les secteurs historiques des societes disparues
  ne sont pas disponibles gratuitement);
- pas de modulation par le regime macro (exposition toujours pleine);
- deux tiers des societes sorties de l'indice n'ont plus de cours chez
  Yahoo: le biais du survivant est reduit, pas elimine.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from atlas.backtest.pit_data import Donnees


@dataclass
class Parametres:
    capital: float = 100_000.0
    stop_atr: float = 2.0
    trail_atr: float = 2.75
    tp_r: float | None = 1.5          # None = pas de prise partielle
    tp_part: float = 1 / 3
    risque_par_trade: float = 0.005
    poids_max: float = 0.05
    positions_max: int = 25
    carence_jours: int = 20
    selectivite: float = 0.006        # part de l'indice retenue chaque jour
    glissement: float = 0.0005        # 5 points de base, comme le broker paper

    @classmethod
    def depuis_config(cls, **surcharges) -> "Parametres":
        """Reprend les reglages reels de config.yaml."""
        from atlas.config import get_config

        cfg = get_config()
        sig, pf = cfg.signals, cfg.portfolio
        tp = sig.get("take_profit_r", [1.5])
        base = dict(
            capital=float(cfg.backtest.get("initial_capital", 100_000)),
            stop_atr=float(sig.get("stop_atr_multiple", 2.0)),
            trail_atr=float(sig.get("trailing_atr_multiple", 2.75)),
            tp_r=float(tp[0]) if tp else None,
            tp_part=float(sig.get("take_profit_part", 1 / 3)),
            risque_par_trade=float(pf.get("risk_per_trade", 0.005)),
            poids_max=float(pf.get("max_weight_per_position", 0.05)),
            positions_max=int(pf.get("max_positions", 25)),
            carence_jours=int(pf.get("cooldown_days", 0)),
            glissement=float(cfg.backtest.get("slippage_bps", 5)) / 10_000,
        )
        base.update(surcharges)
        return cls(**base)


@dataclass
class Position:
    qty: float
    prix: float                # prix d'entree, glissement inclus
    stop0: float               # stop initial, fixe au signal
    suiveur: float             # stop suiveur memorise (ne fait que monter)
    plus_haut: float
    jour_entree: int
    tp1: bool = False


@dataclass
class Resultat:
    equity: pd.Series
    trades: pd.DataFrame
    exposition: pd.Series      # part du capital investie, jour par jour
    params: Parametres = field(repr=False, default=None)


def simuler(d: Donnees, score: np.ndarray, p: Parametres | None = None,
            debut: str | None = None) -> Resultat:
    """Deroule la strategie sur toute la periode.

    score: matrice (jours x titres), NaN = titre non note ce jour-la.
    """
    p = p or Parametres()
    n_jours = len(d.cal)
    t0 = int(np.searchsorted(d.cal.values, np.datetime64(pd.Timestamp(debut)))) \
        if debut else 1
    t0 = max(t0, 1)

    # dernier jour de cotation de chaque titre: au-dela, il est radie
    cote = ~np.isnan(d.cloture)
    dernier = np.where(cote.any(axis=0),
                       n_jours - 1 - np.argmax(cote[::-1], axis=0), -1)

    cash = p.capital
    positions: dict[int, Position] = {}
    carence: dict[int, int] = {}          # titre -> premier jour ou il redevient achetable
    derniere_cloture = np.full(len(d.tickers), np.nan)
    candidats: list[int] = []             # signaux de la veille, tries par score
    stops_signal: dict[int, float] = {}
    equity = np.full(n_jours, np.nan)
    exposition = np.zeros(n_jours)
    equity_veille = p.capital
    trades: list[dict] = []

    def vendre(j: int, pos: Position, qty: float, prix: float, t: int,
               raison: str) -> float:
        nonlocal cash
        net = prix * (1 - p.glissement)
        cash += net * qty
        pnl = (net - pos.prix) * qty
        trades.append({
            "ticker": d.tickers[j], "entree": d.cal[pos.jour_entree],
            "sortie": d.cal[t], "qty": qty, "prix_entree": pos.prix,
            "prix_sortie": net, "pnl": pnl, "raison": raison,
            "jours": t - pos.jour_entree})
        return pnl

    for t in range(t0, n_jours):
        # 1. ENTREES a l'ouverture, sur les signaux de la cloture precedente
        for j in candidats:
            if len(positions) >= p.positions_max:
                break
            if j in positions or carence.get(j, 0) > t:
                continue
            ouverture = d.ouverture[t, j]
            stop = stops_signal.get(j, np.nan)
            if not (np.isfinite(ouverture) and np.isfinite(stop)
                    and ouverture > stop):
                continue
            taille_risque = equity_veille * p.risque_par_trade / (ouverture - stop)
            taille_plafond = equity_veille * p.poids_max / ouverture
            qty = float(int(max(min(taille_risque, taille_plafond), 0)))
            prix = ouverture * (1 + p.glissement)
            if qty <= 0 or prix * qty > cash:
                continue
            cash -= prix * qty
            positions[j] = Position(qty=qty, prix=prix, stop0=stop, suiveur=stop,
                                    plus_haut=d.haut[t, j]
                                    if np.isfinite(d.haut[t, j]) else ouverture,
                                    jour_entree=t)

        # 2. SORTIES a la cloture (les positions ouvertes ce matin attendent
        #    demain: en reel elles ne sont examinees qu'au run suivant)
        for j in list(positions):
            pos = positions[j]
            cloture = d.cloture[t, j]
            if np.isfinite(d.haut[t, j]):
                pos.plus_haut = max(pos.plus_haut, d.haut[t, j])
            if pos.jour_entree == t:
                continue
            if not np.isfinite(cloture):
                if t > dernier[j]:      # plus aucune cotation: radie ou rachete
                    vendre(j, pos, pos.qty, derniere_cloture[j], t, "radiation")
                    del positions[j]
                continue
            R = pos.prix - pos.stop0
            if p.tp_r and not pos.tp1 and R > 0 \
                    and cloture >= pos.prix + p.tp_r * R:
                part = max(1.0, round(pos.qty * p.tp_part))
                if part < pos.qty:
                    vendre(j, pos, part, cloture, t, "objectif")
                    pos.qty -= part
                    pos.tp1 = True
                    continue
            atr_j = d.atr[t, j]
            nouveau = (pos.plus_haut - p.trail_atr * atr_j
                       if np.isfinite(atr_j) else -np.inf)
            effectif = max(pos.stop0, pos.suiveur, nouveau)
            if cloture <= effectif:
                raison = "stop initial" if effectif <= pos.stop0 else "stop suiveur"
                pnl = vendre(j, pos, pos.qty, cloture, t, raison)
                del positions[j]
                if pnl < 0 and p.carence_jours:
                    # carence en jours CALENDAIRES, comme en reel
                    limite = d.cal[t] + pd.Timedelta(days=p.carence_jours)
                    carence[j] = int(np.searchsorted(d.cal.values,
                                                     np.datetime64(limite)))
            else:
                pos.suiveur = max(pos.suiveur, nouveau)

        # 3. VALORISATION a la cloture
        ligne = d.cloture[t]
        vus = np.isfinite(ligne)
        derniere_cloture[vus] = ligne[vus]
        investi = sum(pos.qty * derniere_cloture[j] for j, pos in positions.items())
        equity[t] = cash + investi
        exposition[t] = investi / equity[t] if equity[t] > 0 else 0.0
        equity_veille = equity[t]

        # 4. SIGNAUX pour demain: les mieux notes de l'indice
        s = score[t]
        notes = np.where(np.isfinite(s) & np.isfinite(d.atr[t])
                         & np.isfinite(ligne))[0]
        candidats, stops_signal = [], {}
        if len(notes):
            combien = max(1, int(round(p.selectivite * len(notes))))
            ordre = notes[np.argsort(-s[notes], kind="stable")][:combien]
            candidats = [int(j) for j in ordre]
            stops_signal = {int(j): ligne[j] - p.stop_atr * d.atr[t, j]
                            for j in ordre}

    serie = pd.Series(equity, index=d.cal).dropna()
    return Resultat(equity=serie, trades=pd.DataFrame(trades),
                    exposition=pd.Series(exposition, index=d.cal).loc[serie.index],
                    params=p)


def mesures(r: Resultat) -> dict:
    """Indicateurs usuels d'un resultat de backtest."""
    e = r.equity
    if len(e) < 2:
        return {}
    rendements = e.pct_change().dropna()
    annees = (e.index[-1] - e.index[0]).days / 365.25
    cagr = (e.iloc[-1] / e.iloc[0]) ** (1 / annees) - 1 if annees > 0 else 0.0
    vol = float(rendements.std() * np.sqrt(252))
    t = r.trades
    clos = t[t["raison"] != "objectif"] if len(t) else t
    gains = t.loc[t.pnl > 0, "pnl"].sum() if len(t) else 0.0
    pertes = -t.loc[t.pnl < 0, "pnl"].sum() if len(t) else 0.0
    return {
        "cagr": float(cagr),
        "volatilite": vol,
        "sharpe": float(rendements.mean() / rendements.std() * np.sqrt(252))
        if rendements.std() > 0 else 0.0,
        "drawdown_max": float((e / e.cummax() - 1).min()),
        "trades": int(len(clos)),
        "reussite": float((clos.pnl > 0).mean()) if len(clos) else 0.0,
        "profit_factor": float(gains / pertes) if pertes > 0 else float("inf"),
        "exposition_moyenne": float(r.exposition.mean()),
        "equity_finale": float(e.iloc[-1]),
    }
