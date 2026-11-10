# -*- coding: utf-8 -*-
"""Cours et divisions d'actions, pour comparer un prix a des comptes d'epoque.

LE PIEGE. Les cours du cache sont ajustes de toutes les divisions d'actions,
y compris celles qui ont eu lieu APRES la date consideree: Nvidia a divise
son action par 4 en 2021 puis par 10 en 2024, donc son cours "au 30 juin
2020" vaut 9,44 USD dans le cache alors qu'il cotait environ 380. Les comptes
EDGAR, eux, sont ceux publies a l'epoque: un benefice par action de 4,52.
Diviser l'un par l'autre donne un rendement beneficiaire de 48% au lieu de
1,2%.

Ce n'est pas une imprecision, c'est un regard vers l'avenir: seules les
actions qui ont beaucoup monte divisent leur titre. Un score "valeur" calcule
ainsi classe donc en tete, des annees a l'avance, les futurs grands gagnants.
Toute mesure de la famille valeur faite avant cette correction (IC d'aout
2026 compris) etait gonflee par ce biais.

LA CORRECTION. On ramene les comptes sur la meme base que le cours: un
benefice par action publie le jour D est divise par le produit des divisions
survenues APRES D; un nombre d'actions est multiplie par ce meme produit.
On utilise le "Close" de Yahoo, ajuste des divisions mais PAS des dividendes
(l'ajustement des dividendes abaisse artificiellement les cours passes et
ferait paraitre bon marche les societes a fort rendement).
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

from atlas.config import get_config

log = logging.getLogger(__name__)


def _dossier() -> Path:
    d = Path(get_config().cache_dir) / "prix_reels"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _fichier(ticker: str) -> Path:
    sur = ticker.replace("/", "_").replace("^", "_").replace(".", "_")
    return _dossier() / f"{sur}.parquet"


def charger(ticker: str) -> pd.DataFrame:
    """Colonnes: close (ajuste des divisions seulement), split (ratio ou 0)."""
    try:
        return pd.read_parquet(_fichier(ticker))
    except (FileNotFoundError, OSError):
        return pd.DataFrame()


def telecharger(tickers: list[str], start: str = "2009-01-01",
                taille_lot: int = 60) -> dict[str, int]:
    """Recupere cours non ajustes des dividendes et divisions, par lots."""
    import yfinance as yf

    bilan = {"obtenus": 0, "absents": 0}
    for debut in range(0, len(tickers), taille_lot):
        lot = tickers[debut:debut + taille_lot]
        try:
            brut = yf.download(lot, start=start, group_by="ticker",
                               auto_adjust=False, actions=True,
                               progress=False, threads=True)
        except Exception as exc:  # noqa: BLE001
            log.warning("lot en echec (%d titres): %s", len(lot), exc)
            bilan["absents"] += len(lot)
            continue
        for t in lot:
            try:
                df = brut[t] if len(lot) > 1 else brut
                df = df.dropna(subset=["Close"])
            except (KeyError, TypeError):
                df = pd.DataFrame()
            if df.empty:
                bilan["absents"] += 1
                continue
            propre = pd.DataFrame({
                "close": df["Close"].astype(float),
                "split": df.get("Stock Splits", 0.0),
            })
            propre["split"] = propre["split"].fillna(0.0).astype(float)
            propre.index = pd.DatetimeIndex(propre.index).tz_localize(None).normalize()
            propre.to_parquet(_fichier(t))
            bilan["obtenus"] += 1
        log.info("prix reels: %d/%d titres traites",
                 min(debut + taille_lot, len(tickers)), len(tickers))
    return bilan


def facteur_divisions(splits: pd.Series, dates) -> np.ndarray:
    """Produit des divisions survenues STRICTEMENT APRES chaque date.

    C'est le diviseur a appliquer a un benefice par action publie a cette
    date pour le ramener sur la base du cours Yahoo (et le multiplicateur a
    appliquer a un nombre d'actions). Vaut 1 pour une date posterieure a la
    derniere division.
    """
    dates = pd.DatetimeIndex(dates)
    evenements = splits[splits > 0]
    if evenements.empty:
        return np.ones(len(dates))
    jours = evenements.index.values
    # produit cumule depuis la fin: cumul[i] = produit des ratios a partir de i
    cumul = np.cumprod(evenements.to_numpy()[::-1])[::-1]
    cumul = np.append(cumul, 1.0)
    # premiere division strictement posterieure a la date
    position = np.searchsorted(jours, dates.values, side="right")
    return cumul[position]
