# -*- coding: utf-8 -*-
"""Composition HISTORIQUE du S&P 500, reconstituee depuis Wikipedia.

Corrige le biais du survivant, qui rendait toute mesure ininterpretable.
L'univers du projet etait fait des membres ACTUELS de l'indice: par
construction, des societes qui ont reussi. Celles qui ont fait faillite ou ont
ete rachetees apres avoir chute en sont absentes. Consequence mesuree le
2026-08-27: sur cet univers, plus un titre est volatil, meilleur il parait
(IC -0.064, t = -1.96) et le momentum lui-meme, effet le plus replique de la
litterature, ressort nul. Ce n'etaient pas les facteurs qui ne marchaient pas,
c'etait l'echantillon qui mentait.

Methode, entierement gratuite: Wikipedia conserve toutes les revisions de sa
page "List of S&P 500 companies". On demande a l'API MediaWiki la version la
plus proche avant chaque date voulue, et on en extrait la liste. La revision
de fin 2011 contient ainsi Alcoa et ACE Limited, sorties de l'indice depuis.

Limites assumees:
- Wikipedia n'est pas une source officielle. La page est bien tenue et
  largement relue, mais une erreur ponctuelle reste possible.
- un ticker peut changer de proprietaire au fil des annees (reattribution
  apres radiation). Les cas sont rares et concernent des titres peu liquides.
- avant 2010, la page etait moins structuree: on ne remonte pas plus loin.
"""

from __future__ import annotations

import io
import json
import logging
import time
from datetime import date
from pathlib import Path

import pandas as pd
import requests

from atlas.config import get_config

log = logging.getLogger(__name__)

API = "https://en.wikipedia.org/w/api.php"
TITRE = "List of S&P 500 companies"
UA = {"User-Agent": "ATLAS research bot (github.com/icarepesin-png/atlas)"}
DEBUT_FIABLE = date(2010, 1, 1)
PAUSE = 1.0                    # courtoisie envers Wikipedia
TENTATIVES = 5


def _dossier() -> Path:
    d = Path(get_config().cache_dir) / "univers_historique"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _demander(params: dict, timeout: int = 45) -> dict:
    """Appel API avec attente croissante en cas de bridage.

    Wikipedia renvoie 429 quand on va trop vite. Marteler ne ferait
    qu'allonger le bannissement: on double l'attente a chaque refus.
    """
    attente = PAUSE
    for essai in range(TENTATIVES):
        r = requests.get(API, headers=UA, timeout=timeout,
                         params={**params, "format": "json"})
        if r.status_code == 429:
            log.info("Wikipedia bride (429), pause de %.0fs", attente * 4)
            time.sleep(attente * 4)
            attente *= 2
            continue
        r.raise_for_status()
        time.sleep(PAUSE)
        return r.json()
    raise RuntimeError("Wikipedia refuse toujours apres plusieurs tentatives")


def _revision_avant(jour: date | str) -> dict | None:
    """Derniere revision de la page publiee avant `jour`."""
    horodatage = f"{pd.Timestamp(jour).date()}T00:00:00Z"
    donnees = _demander({
        "action": "query", "prop": "revisions", "titles": TITRE,
        "rvlimit": 1, "rvdir": "older", "rvstart": horodatage,
        "rvprop": "ids|timestamp"}, timeout=30)
    pages = donnees.get("query", {}).get("pages", {})
    revisions = next(iter(pages.values()), {}).get("revisions")
    return revisions[0] if revisions else None


def _tickers_de_revision(oldid: int) -> list[str]:
    """Tickers presents dans une version donnee de la page."""
    html = _demander({"action": "parse", "oldid": oldid,
                      "prop": "text"}, timeout=60)["parse"]["text"]["*"]
    tables = pd.read_html(io.StringIO(html))
    if not tables:
        return []
    # La table des composants est de loin la plus longue de la page.
    table = max(tables, key=len)
    # L'intitule de la colonne a change au fil des ans: "Ticker symbol"
    # jusque vers 2019, "Symbol" ensuite.
    colonne = next((c for c in table.columns
                    if str(c).strip().lower().split()[0] in ("symbol", "ticker")),
                   None)
    if colonne is None:
        return []
    tickers = []
    for brut in table[colonne].dropna():
        t = str(brut).strip().upper().split()[0]
        # Yahoo ecrit les actions de categorie B avec un tiret (BRK-B),
        # Wikipedia avec un point ou un tiret selon l'epoque.
        t = t.replace(".", "-")
        if t and t.isascii() and len(t) <= 6:
            tickers.append(t)
    return sorted(set(tickers))


def composition_au(jour: date | str, rafraichir: bool = False) -> list[str]:
    """Composition du S&P 500 a une date, avec cache disque.

    Une composition passee ne change jamais: une fois recuperee, elle est
    definitive.
    """
    jour = pd.Timestamp(jour).date()
    fichier = _dossier() / f"sp500_{jour}.json"
    if fichier.exists() and not rafraichir:
        return json.loads(fichier.read_text(encoding="utf-8"))["tickers"]

    revision = _revision_avant(jour)
    if not revision:
        return []
    tickers = _tickers_de_revision(revision["revid"])
    fichier.write_text(json.dumps({
        "date": str(jour), "revid": revision["revid"],
        "revision_du": revision["timestamp"][:10], "tickers": tickers},
        indent=1), encoding="utf-8")
    return tickers


def compositions(dates) -> dict[date, list[str]]:
    """Compositions successives, pour reconstituer un univers dans le temps."""
    out = {}
    for d in dates:
        jour = pd.Timestamp(d).date()
        if jour < DEBUT_FIABLE:
            log.warning("avant %s la page Wikipedia est peu structuree, ignore",
                        DEBUT_FIABLE)
            continue
        tickers = composition_au(jour)
        if tickers:
            out[jour] = tickers
    return out


def univers_elargi(dates) -> list[str]:
    """Tous les titres ayant appartenu a l'indice sur la periode.

    C'est l'univers a telecharger pour travailler sans biais du survivant:
    il contient les societes disparues, celles-la memes dont l'absence
    faussait toutes les mesures.
    """
    vus: set[str] = set()
    for tickers in compositions(dates).values():
        vus.update(tickers)
    return sorted(vus)
