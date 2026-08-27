# -*- coding: utf-8 -*-
"""Fondamentaux POINT-IN-TIME depuis SEC EDGAR.

Le probleme que ce module resout: les fondamentaux Yahoo sont un instantane
d'aujourd'hui. Ils repondent a "quel est le resultat net de 2024 ?" mais pas a
"que savait-on le 15 mars 2024 ?". Backtester un score fondamental avec eux,
c'est acheter en 2024 en connaissant des chiffres publies en 2025 - le score
parait genial et ne vaut rien.

EDGAR publie chaque fait comptable avec sa DATE DE DEPOT (`filed`). Exemple
reel: le resultat net de l'exercice Micron clos le 2024-08-29 (778 M USD) a ete
depose le 2024-10-04. Avant cette date il etait inconnu. C'est cette date, et
elle seule, qui permet de reconstituer ce qu'on savait a un instant donne.

Contraintes de l'API SEC, apprises a ses depens:
- un `User-Agent` identifiant avec un contact REEL est obligatoire, sinon 403
  "Your Request Originates from an Undeclared Automated Tool". Il vit dans
  .env (SEC_USER_AGENT) et jamais dans le code: le depot est public.
- debit limite. On se tient sous la limite annoncee de 10 requetes/seconde.
- `companyfacts` renvoie ~4 Mo par societe: on extrait les quelques concepts
  utiles et on jette le reste, sinon l'univers pese plusieurs Go.
"""

from __future__ import annotations

import gzip
import json
import logging
import os
import threading
import time
from datetime import date
from pathlib import Path

import pandas as pd
import requests

from atlas.config import get_config

log = logging.getLogger(__name__)

BASE_FACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
URL_TICKERS = "https://www.sec.gov/files/company_tickers.json"

# La SEC annonce 10 requetes/seconde. On garde une marge: un blocage coute
# bien plus cher que les quelques minutes gagnees.
DEBIT_MAX = 8.0
_verrou = threading.Lock()
_dernier_appel = 0.0

# Concepts XBRL retenus. Plusieurs noms possibles pour une meme grandeur:
# la norme a evolue (ASC 606 en 2018 a remplace `Revenues` par
# `RevenueFromContractWithCustomer...`), et toutes les societes n'ont pas
# migre en meme temps. On essaie dans l'ordre.
CONCEPTS: dict[str, list[str]] = {
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax",
                "Revenues", "SalesRevenueNet"],
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "gross_profit": ["GrossProfit"],
    "operating_income": ["OperatingIncomeLoss"],
    "assets": ["Assets"],
    "liabilities": ["Liabilities"],
    "equity": ["StockholdersEquity",
               "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "cash_from_ops": ["NetCashProvidedByUsedInOperatingActivities",
                      "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment"],
    "eps_diluted": ["EarningsPerShareDiluted"],
    "shares_diluted": ["WeightedAverageNumberOfDilutedSharesOutstanding"],
    "current_assets": ["AssetsCurrent"],
    "current_liabilities": ["LiabilitiesCurrent"],
    "long_term_debt": ["LongTermDebtNoncurrent", "LongTermDebt"],
    "inventory": ["InventoryNet"],
}


class SecUserAgentManquant(RuntimeError):
    """SEC_USER_AGENT absent: l'API refuse tout sans contact declare."""


def entetes() -> dict[str, str]:
    ua = os.environ.get("SEC_USER_AGENT", "").strip()
    if not ua or "@" not in ua:
        raise SecUserAgentManquant(
            "SEC_USER_AGENT absent ou sans adresse de contact. La SEC refuse "
            "les outils automatises non declares (403). Ajouter dans .env:\n"
            "  SEC_USER_AGENT=Nom du projet contact@exemple.com\n"
            "Ne JAMAIS le mettre dans le code: le depot est public.")
    return {"User-Agent": ua, "Accept-Encoding": "gzip, deflate"}


def _attendre_son_tour() -> None:
    """Espace les appels pour rester sous la limite de debit de la SEC."""
    global _dernier_appel
    with _verrou:
        creux = 1.0 / DEBIT_MAX - (time.monotonic() - _dernier_appel)
        if creux > 0:
            time.sleep(creux)
        _dernier_appel = time.monotonic()


def _dossier_cache() -> Path:
    d = Path(get_config().cache_dir) / "edgar"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _get(url: str, timeout: int = 60) -> requests.Response:
    _attendre_son_tour()
    r = requests.get(url, headers=entetes(), timeout=timeout)
    if r.status_code == 403:
        raise SecUserAgentManquant(
            "403 de la SEC. User-Agent refuse ou debit depasse. "
            f"Reponse: {r.text[:120]}")
    r.raise_for_status()
    return r


def table_cik(rafraichir: bool = False) -> dict[str, int]:
    """Correspondance ticker -> CIK, mise en cache sur disque.

    Le CIK est l'identifiant SEC d'une societe. Le fichier fait ~1 Mo et ne
    change qu'a la marge: inutile de le retelecharger a chaque appel.
    """
    fichier = _dossier_cache() / "company_tickers.json"
    if rafraichir or not fichier.exists():
        log.info("telechargement du mapping ticker -> CIK")
        fichier.write_text(_get(URL_TICKERS, timeout=30).text, encoding="utf-8")
    brut = json.loads(fichier.read_text(encoding="utf-8"))
    return {v["ticker"].upper(): int(v["cik_str"]) for v in brut.values()}


def cik_de(ticker: str) -> int | None:
    """CIK d'un ticker. None hors des Etats-Unis (EDGAR ne couvre que la SEC)."""
    return table_cik().get(ticker.upper().replace(".", "-"))


def faits_bruts(cik: int, max_age_days: int = 30) -> dict:
    """companyfacts d'une societe, avec cache disque COMPRESSE.

    Les societes deposent au plus quelques fois par trimestre: un cache de
    30 jours evite de retelecharger 4 Mo pour rien. Le JSON brut est conserve
    (gzip, ~10x plus petit) plutot que jete apres extraction: ajouter un
    concept a CONCEPTS ne doit pas obliger a retelecharger tout l'univers.
    Sans compression, 513 societes pesent plus de 2 Go.
    """
    fichier = _dossier_cache() / f"CIK{cik:010d}.json.gz"
    if fichier.exists():
        age = (time.time() - fichier.stat().st_mtime) / 86400
        if age <= max_age_days:
            try:
                with gzip.open(fichier, "rt", encoding="utf-8") as f:
                    return json.load(f)
            except (OSError, json.JSONDecodeError):
                pass  # cache corrompu: on retelecharge
    r = _get(BASE_FACTS.format(cik=cik))
    with gzip.open(fichier, "wt", encoding="utf-8") as f:
        f.write(r.text)
    return r.json()


def extraire(brut: dict, ticker: str) -> pd.DataFrame:
    """Aplatit companyfacts en table: un fait comptable par ligne.

    Colonnes: ticker, grandeur, fin (de periode), valeur, depot, formulaire,
    exercice. `depot` est la colonne qui donne tout son interet au module.
    """
    gaap = (brut.get("facts") or {}).get("us-gaap", {})
    lignes = []
    for grandeur, candidats in CONCEPTS.items():
        for rang, concept in enumerate(candidats):
            bloc = gaap.get(concept)
            if not bloc:
                continue
            for unite, faits in bloc.get("units", {}).items():
                if unite not in ("USD", "USD/shares", "shares"):
                    continue
                for f in faits:
                    if f.get("val") is None or not f.get("filed"):
                        continue
                    lignes.append({
                        "ticker": ticker,
                        "grandeur": grandeur,
                        "concept": concept,
                        "priorite": rang,
                        "debut": f.get("start"),
                        "fin": f.get("end"),
                        "valeur": float(f["val"]),
                        "depot": f["filed"],
                        "formulaire": f.get("form"),
                        "exercice": f.get("fy"),
                        "periode": f.get("fp"),
                    })
            # PAS de break: on collecte TOUS les intitules candidats. La
            # norme comptable change (ASC 606 en 2018 a remplace `Revenues`
            # par `RevenueFromContractWithCustomer...`), donc s'arreter au
            # premier trouve perdait tout l'historique anterieur - Micron et
            # Apple n'avaient plus aucune marge avant 2018. `priorite`
            # departage ensuite, periode par periode.
    if not lignes:
        return pd.DataFrame()
    df = pd.DataFrame(lignes)
    for col in ("debut", "fin", "depot"):
        df[col] = pd.to_datetime(df[col], errors="coerce")
    return df.dropna(subset=["fin", "depot"])


def connu_au(df: pd.DataFrame, as_of: date | str,
             formulaires=("10-K", "10-Q", "20-F", "40-F"),
             anciennete_max_mois: int = 18) -> pd.DataFrame:
    """Ce qui etait PUBLIQUEMENT connu a la date `as_of`.

    Coeur du module: on ne garde que les faits deposes au plus tard ce jour-la,
    puis, pour chaque grandeur, la periode la plus recente. Un chiffre corrige
    plus tard n'ecrase donc pas ce qu'on croyait savoir a l'epoque.

    `anciennete_max_mois` ecarte les grandeurs perimees. Sans ce garde-fou,
    une societe qui cesse de publier un concept (la norme XBRL evolue, les
    intitules changent) voit sa derniere valeur ressortir indefiniment: Micron
    renvoyait une dette long terme de 2013 comme donnee "connue" en 2024.
    Techniquement vrai, comptablement absurde.
    """
    if df.empty:
        return df
    limite = pd.Timestamp(as_of)
    vu = df[(df["depot"] <= limite) & (df["formulaire"].isin(formulaires))]
    if vu.empty:
        return vu
    plancher = limite - pd.DateOffset(months=anciennete_max_mois)
    vu = vu[vu["fin"] >= plancher]
    if vu.empty:
        return vu
    # Derniere periode connue, et parmi les depots la version deposee en
    # premier (la publication d'origine, pas une reformulation ulterieure).
    tri = ["grandeur", "fin"] + (["priorite"] if "priorite" in vu.columns else [])
    vu = vu.sort_values(tri + ["depot"])
    # last() sur (grandeur, fin) croissant = periode la plus recente; la
    # priorite ayant ete triee en amont, le concept de reference l'emporte.
    return vu.groupby("grandeur", as_index=False).last()


def historique(ticker: str) -> pd.DataFrame:
    """Tous les faits retenus d'un titre, prets pour `connu_au`."""
    cik = cik_de(ticker)
    if cik is None:
        return pd.DataFrame()
    try:
        return extraire(faits_bruts(cik), ticker)
    except SecUserAgentManquant:
        raise
    except Exception as exc:  # noqa: BLE001
        log.warning("EDGAR %s (CIK %s) indisponible: %s", ticker, cik, exc)
        return pd.DataFrame()
