# -*- coding: utf-8 -*-
"""Donnees du backtest fidele, sous forme de matrices (jours x titres).

Trois sources, toutes gratuites et toutes datees:
- les cours Yahoo, y compris ceux des societes sorties de l'indice;
- la composition du S&P 500 trimestre par trimestre (revisions Wikipedia),
  pour ne noter chaque jour que les titres qui etaient REELLEMENT dans
  l'indice ce jour-la;
- les comptes EDGAR avec leur date de depot, pour ne jamais utiliser un
  chiffre avant sa publication.

Tout est range en matrices numpy alignees sur un calendrier commun: le
backtest relit ces grandeurs des millions de fois, et un filtrage pandas par
titre et par date prendrait des heures la ou une matrice prend des secondes.
"""

from __future__ import annotations

import json
import logging
import pickle
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from atlas.config import get_config
from atlas.data import prix_reels
from atlas.data.store import load_ohlcv
from atlas.features.fundamental_pit import (ANCIENNETE_MAX_JOURS, GRANDEURS,
                                            construire_comptes)
from atlas.features.technical import atr

log = logging.getLogger(__name__)

COMPOSANTES = GRANDEURS + ("revenue_prec", "eps_prec")


@dataclass
class Donnees:
    cal: pd.DatetimeIndex
    tickers: list[str]
    ouverture: np.ndarray
    haut: np.ndarray
    bas: np.ndarray
    cloture: np.ndarray
    atr: np.ndarray
    membre: np.ndarray                      # bool: dans l'indice ce jour-la
    comptes: dict[str, np.ndarray] = field(default_factory=dict)
    # Cours servant aux ratios de valorisation: ajuste des divisions mais pas
    # des dividendes, et coherent avec `comptes` (voir prix_reels.py). Absent
    # (None) dans les univers d'essai: on retombe alors sur `cloture`.
    cours_valo: np.ndarray | None = None
    couverture: dict = field(default_factory=dict)


def _dossier_cache() -> Path:
    return Path(get_config().cache_dir)


def comptes_univers(rafraichir: bool = False) -> dict[str, list]:
    """Tables de depots de tout l'univers, mises en cache sur disque.

    Le calcul prend une a deux minutes (une quinzaine de depots pour chacune
    des 633 societes); le cache est invalide des que la moisson EDGAR change.
    """
    faits = _dossier_cache() / "edgar" / "faits_edgar.parquet"
    cache = _dossier_cache() / "edgar" / "comptes_annuels.pkl"
    if (cache.exists() and not rafraichir
            and cache.stat().st_mtime >= faits.stat().st_mtime):
        with cache.open("rb") as f:
            return pickle.load(f)
    log.info("construction des tables de depots (1 a 2 minutes)...")
    comptes = construire_comptes(pd.read_parquet(faits))
    with cache.open("wb") as f:
        pickle.dump(comptes, f)
    return comptes


AJUSTEES_PAR_ACTION = ("eps_diluted", "eps_prec")     # divisees par le facteur
AJUSTEES_EN_NOMBRE = ("shares_diluted",)              # multipliees


def _matrice_escalier(marches: list, cal: pd.DatetimeIndex,
                      splits: pd.Series | None = None) -> dict[str, np.ndarray]:
    """Projette les marches d'un titre sur le calendrier (une colonne par
    composante). NaN avant le premier depot et au-dela de l'anciennete max.

    Un depot du jour J n'est exploitable qu'a partir de J+1: beaucoup de
    rapports sont deposes apres la cloture, les utiliser le jour meme serait
    connaitre le soir ce qui n'est public que dans la nuit.

    `splits` ramene les grandeurs par action sur la base du cours Yahoo
    (voir atlas/data/prix_reels.py); sans lui, elles restent telles que
    publiees.
    """
    n = len(cal)
    vide = {c: np.full(n, np.nan) for c in COMPOSANTES}
    if not marches:
        return vide
    depots = np.array([d.to_datetime64() for d, _ in marches])
    idx = np.searchsorted(depots, cal.values, side="left") - 1
    valide = idx >= 0
    age = np.zeros(n)
    age[valide] = (cal.values[valide] - depots[idx[valide]]) / np.timedelta64(1, "D")
    valide &= age <= ANCIENNETE_MAX_JOURS
    facteur = (prix_reels.facteur_divisions(splits, [d for d, _ in marches])
               if splits is not None else np.ones(len(marches)))
    for c in COMPOSANTES:
        vals = np.array([np.nan if m.get(c) is None else float(m[c])
                         for _, m in marches])
        if c in AJUSTEES_PAR_ACTION:
            vals = vals / facteur
        elif c in AJUSTEES_EN_NOMBRE:
            vals = vals * facteur
        col = np.full(n, np.nan)
        col[valide] = vals[idx[valide]]
        vide[c] = col
    return vide


def charger(debut: str = "2009-06-01", fin: str | None = None) -> Donnees:
    """Assemble toutes les matrices. Le calendrier est celui du SPY."""
    spy = load_ohlcv("SPY")
    if spy.empty:
        raise RuntimeError("SPY absent du cache: lancer un scan d'abord")
    cal = pd.DatetimeIndex(spy.index).normalize()
    cal = cal[cal >= pd.Timestamp(debut)]
    if fin:
        cal = cal[cal <= pd.Timestamp(fin)]

    f = _dossier_cache() / "univers_historique" / "compositions.json"
    compositions = {pd.Timestamp(d): set(lot) for d, lot in
                    json.loads(f.read_text(encoding="utf-8")).items()}
    tous = sorted(set().union(*compositions.values()))

    series = {}
    for t in tous:
        df = load_ohlcv(t)
        if df.empty or len(df) < 60:
            continue
        df = df.copy()
        df.index = pd.DatetimeIndex(df.index).normalize()
        df = df[~df.index.duplicated(keep="last")]
        df["_atr"] = atr(df)
        series[t] = df.reindex(cal)
    tickers = sorted(series)
    n, m = len(cal), len(tickers)

    def mat(col: str) -> np.ndarray:
        out = np.full((n, m), np.nan)
        for j, t in enumerate(tickers):
            out[:, j] = series[t][col].to_numpy(dtype=float)
        return out

    # Appartenance a l'indice: la composition du dernier trimestre connu.
    trimestres = sorted(compositions)
    membre = np.zeros((n, m), dtype=bool)
    position = {t: j for j, t in enumerate(tickers)}
    bornes = np.searchsorted(np.array([q.to_datetime64() for q in trimestres]),
                             cal.values, side="right") - 1
    present, total = np.zeros(n), np.zeros(n)
    for k, q in enumerate(trimestres):
        lignes = np.where(bornes == k)[0]
        if not len(lignes):
            continue
        cols = [position[t] for t in compositions[q] if t in position]
        membre[np.ix_(lignes, cols)] = True
        present[lignes] = len(cols)
        total[lignes] = len(compositions[q])

    comptes_par_titre = comptes_univers()
    comptes = {c: np.full((n, m), np.nan) for c in COMPOSANTES}
    cours_valo = np.full((n, m), np.nan)
    avec_comptes = avec_cours_reels = 0
    for j, t in enumerate(tickers):
        reel = prix_reels.charger(t)
        if reel.empty:
            continue        # sans cours coherent, pas de ratio de valorisation
        avec_cours_reels += 1
        cours_valo[:, j] = reel["close"].reindex(cal).to_numpy(dtype=float)
        marches = comptes_par_titre.get(t)
        if not marches:
            continue
        avec_comptes += 1
        projete = _matrice_escalier(marches, cal, splits=reel["split"])
        for c in COMPOSANTES:
            comptes[c][:, j] = projete[c]

    actifs = total > 0
    return Donnees(
        cal=cal, tickers=tickers, ouverture=mat("open"), haut=mat("high"),
        bas=mat("low"), cloture=mat("close"), atr=mat("_atr"), membre=membre,
        comptes=comptes, cours_valo=cours_valo,
        couverture={
            "titres_historiques": len(tous), "avec_cours": m,
            "avec_comptes": avec_comptes,
            "avec_cours_reels": avec_cours_reels,
            "membres_couverts_min": float((present[actifs] / total[actifs]).min()),
            "membres_couverts_moy": float((present[actifs] / total[actifs]).mean()),
        })


# -- scores -------------------------------------------------------------------

def _div(a: np.ndarray, b: np.ndarray, positif: bool = True) -> np.ndarray:
    """a / b, NaN si le denominateur est absent (ou non positif)."""
    with np.errstate(divide="ignore", invalid="ignore"):
        out = a / b
    out[~np.isfinite(out)] = np.nan
    if positif:
        out[~(b > 0)] = np.nan
    return out


def ratios(d: Donnees) -> dict[str, np.ndarray]:
    """Ratios quotidiens (jours x titres). Les comptes ne bougent qu'aux
    depots, les ratios de valorisation bougent chaque jour avec le cours."""
    k = d.comptes
    cours = d.cours_valo if d.cours_valo is not None else d.cloture
    capi = cours * k["shares_diluted"]
    flux_libre = k["cash_from_ops"] - k["capex"]
    return {
        # valeur
        "earnings_yield": _div(k["eps_diluted"], cours),
        "fcf_yield": _div(flux_libre, capi),
        "sales_yield": _div(k["revenue"], capi),
        # qualite
        "roe": _div(k["net_income"], k["equity"]),
        "roa": _div(k["net_income"], k["assets"]),
        "roic": _div(k["operating_income"], k["equity"] + k["long_term_debt"]),
        "operating_margin": _div(k["operating_income"], k["revenue"]),
        "net_margin": _div(k["net_income"], k["revenue"]),
        "gross_margin": _div(k["gross_profit"], k["revenue"]),
        # croissance
        "revenue_growth": _div(k["revenue"], k["revenue_prec"]) - 1,
        "eps_growth": _div(k["eps_diluted"], k["eps_prec"]) - 1,
    }


FAMILLES = {
    "valeur": ("earnings_yield", "fcf_yield", "sales_yield"),
    "qualite": ("roe", "roa", "roic", "operating_margin", "net_margin",
                "gross_margin"),
    "croissance": ("revenue_growth", "eps_growth"),
}


def rang(mat: np.ndarray, masque: np.ndarray) -> np.ndarray:
    """Rang percentile par jour, parmi les titres du masque (0..1)."""
    df = pd.DataFrame(np.where(masque, mat, np.nan))
    return df.rank(axis=1, pct=True).to_numpy()


def scores_familles(d: Donnees, min_facteurs: int = 2) -> dict[str, np.ndarray]:
    """Score de chaque famille = moyenne des rangs de ses facteurs.

    Un titre doit avoir au moins `min_facteurs` facteurs renseignes dans la
    famille, sinon il n'est pas note: une note fondee sur un seul ratio est
    trop fragile pour le placer en tete de classement.
    """
    r = ratios(d)
    out = {}
    for famille, facteurs in FAMILLES.items():
        pile = np.stack([rang(r[f], d.membre) for f in facteurs])
        renseignes = np.sum(~np.isnan(pile), axis=0)
        with np.errstate(invalid="ignore"):
            moyenne = np.nanmean(pile, axis=0)
        moyenne[renseignes < min(min_facteurs, len(facteurs))] = np.nan
        out[famille] = moyenne
    # Le melange du pilier fondamental tel qu'il tourne aujourd'hui en reel
    # (atlas/scoring/composite.py: qualite 45%, croissance 25%, valeur 30%).
    poids = {"qualite": 0.45, "croissance": 0.25, "valeur": 0.30}
    num = sum(np.nan_to_num(out[f]) * w for f, w in poids.items())
    den = sum((~np.isnan(out[f])) * w for f, w in poids.items())
    with np.errstate(divide="ignore", invalid="ignore"):
        melange = num / den
    melange[den < 0.5] = np.nan
    out["melange_actuel"] = melange
    return out


def hasard(d: Donnees, graine: int) -> np.ndarray:
    """Score tire au sort: le temoin. Toute strategie doit le battre, sinon
    sa selection n'apporte rien de plus que les regles de sortie."""
    rng = np.random.default_rng(graine)
    s = rng.random(d.cloture.shape)
    s[~d.membre | np.isnan(d.cloture)] = np.nan
    return s
