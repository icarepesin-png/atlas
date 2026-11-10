# -*- coding: utf-8 -*-
"""Ratios fondamentaux POINT-IN-TIME, calcules depuis les faits EDGAR.

Difference avec `atlas/features/fundamental.py`: celui-ci part de chiffres
dont on connait la date de publication, donc il peut repondre a "quel etait
le ROE d'Apple tel qu'un investisseur pouvait le calculer le 15 mars 2018 ?".
L'autre part d'un instantane Yahoo et ne le peut pas.

CHOIX ASSUME - on ne retient que les exercices ANNUELS (10-K):
- un resultat trimestriel doit etre cumule sur douze mois glissants pour etre
  comparable, ce qui suppose de recoller quatre depots successifs dont les
  perimetres changent (cessions, changements de calendrier fiscal);
- les ratios de qualite et de valeur bougent lentement: une mesure par an
  suffit largement a repondre a la question qui nous occupe, celle de savoir
  si le pilier fondamental a un pouvoir predictif.
Les donnees trimestrielles restent dans les faits bruts: passer au douze mois
glissants plus tard ne demandera pas de retelecharger quoi que ce soit.

Un ratio dont une composante manque vaut None, jamais zero: une societe qui
ne publie pas sa marge brute (les banques, par exemple) ne doit pas se
retrouver avec une marge de 0% et un mauvais rang.
"""

from __future__ import annotations

import bisect
import logging
from datetime import date

import pandas as pd

from atlas.data.edgar import connu_au

log = logging.getLogger(__name__)

FORMULAIRES_ANNUELS = ("10-K", "20-F", "40-F")


def _valeur(photo: pd.DataFrame, grandeur: str) -> float | None:
    ligne = photo[photo["grandeur"] == grandeur]
    if ligne.empty:
        return None
    v = float(ligne["valeur"].iloc[0])
    return v if pd.notna(v) else None


def _ratio(numerateur: float | None, denominateur: float | None) -> float | None:
    """Division qui refuse de mentir: None si une piece manque ou si le
    denominateur est nul ou negatif (des capitaux propres negatifs rendent un
    ROE ininterpretable, mieux vaut ne rien dire)."""
    if numerateur is None or denominateur is None or denominateur <= 0:
        return None
    return numerateur / denominateur


JOURS_EXERCICE = (300, 400)   # duree plausible d'un exercice annuel


def photo_annuelle(faits: pd.DataFrame, as_of: date | str,
                   rang: int = 0) -> pd.DataFrame:
    """Exercice annuel connu a `as_of`. rang=1 donne le precedent.

    PIEGE MAJEUR: un depot 10-K contient aussi les TRIMESTRES de l'exercice.
    Se contenter de la periode la plus recente comparait l'annee 2018 de
    Micron (30,4 Md USD) a son seul trimestre de mai (7,8 Md), soit une
    croissance affichee de +290%. On ne retient donc que les periodes dont la
    duree est celle d'un exercice; les soldes de bilan, qui n'ont pas de date
    de debut, sont conserves tels quels.
    """
    if faits.empty:
        return faits
    vus = faits[(faits["depot"] <= pd.Timestamp(as_of))
                & (faits["formulaire"].isin(FORMULAIRES_ANNUELS))].copy()
    if vus.empty:
        return vus
    debut = (pd.to_datetime(vus["debut"], errors="coerce") if "debut" in vus.columns
             else pd.Series(pd.NaT, index=vus.index))
    jours = (vus["fin"] - debut).dt.days
    # sans date de debut = solde de bilan, instantane, toujours valable
    vus = vus[debut.isna() | jours.between(*JOURS_EXERCICE)]
    if vus.empty:
        return vus

    # Les cloture d'exercice sont les dates portant un FLUX annuel; un bilan
    # seul ne suffit pas a identifier une fin d'exercice.
    flux = vus[debut.reindex(vus.index).notna()] if "debut" in vus.columns else vus
    candidates = sorted(flux["fin"].unique()) if not flux.empty         else sorted(vus["fin"].unique())
    if len(candidates) <= rang:
        return vus.iloc[0:0]
    cible = candidates[-1 - rang]

    # Pour une meme periode, on retient le DERNIER chiffre publie a `as_of`.
    # Un 10-K republie les comparatifs de l'exercice precedent sur la base
    # du jour (divisions d'actions, reclassements): prendre la premiere
    # publication ferait comparer un benefice par action d'apres division a
    # un autre d'avant division, soit une "croissance" de -75% le jour ou
    # une societe divise son titre par 4.
    lot = vus[vus["fin"] == cible].sort_values("depot", ascending=False)
    if "priorite" in lot.columns:
        lot = lot.sort_values("priorite", kind="stable")
    return lot.groupby("grandeur", as_index=False).first()


GRANDEURS = ("revenue", "net_income", "assets", "equity", "gross_profit",
             "operating_income", "cash_from_ops", "capex", "eps_diluted",
             "shares_diluted", "liabilities", "long_term_debt")

# Au-dela, une societe qui n'a rien depose depuis est consideree comme sortie
# du radar (radiee, rachetee): ses derniers comptes ne decrivent plus rien.
ANCIENNETE_MAX_JOURS = 550


def composantes_au(faits: pd.DataFrame, as_of: date | str) -> dict:
    """Grandeurs BRUTES du dernier exercice publie a `as_of`.

    Separees du calcul des ratios pour deux raisons: les ratios de
    valorisation dependent du cours du jour alors que les comptes ne changent
    qu'au depot suivant, et un backtest a besoin de relire ces grandeurs des
    centaines de milliers de fois sans refiltrer la table des faits.
    """
    actuel = photo_annuelle(faits, as_of)
    if actuel.empty:
        return {}
    precedent = photo_annuelle(faits, as_of, rang=1)
    c: dict = {g: _valeur(actuel, g) for g in GRANDEURS}
    # La croissance compare deux exercices qui devaient TOUS DEUX etre publies
    c["revenue_prec"] = _valeur(precedent, "revenue") if not precedent.empty else None
    c["eps_prec"] = _valeur(precedent, "eps_diluted") if not precedent.empty else None
    c["_exercice"] = str(actuel["fin"].iloc[0].date())
    c["_depot"] = str(actuel["depot"].iloc[0].date())
    return c


def ratios_depuis(c: dict, cours: float | None = None) -> dict[str, float | None]:
    """Ratios a partir de grandeurs brutes (voir `composantes_au`).

    `cours` (facultatif) debloque les ratios de valorisation. ATTENTION: il
    doit etre sur la meme base que les comptes. Un cours ajuste de divisions
    d'actions posterieures, rapproche d'un benefice par action d'epoque,
    fabrique un regard vers l'avenir (voir atlas/data/prix_reels.py).
    """
    if not c:
        return {}
    revenu = c.get("revenue")
    resultat = c.get("net_income")
    fonds_propres = c.get("equity")
    resultat_exploitation = c.get("operating_income")
    tresorerie_exploitation = c.get("cash_from_ops")
    investissements = c.get("capex")
    bpa = c.get("eps_diluted")
    actions = c.get("shares_diluted")

    out: dict[str, float | None] = {
        "roe": _ratio(resultat, fonds_propres),
        "roa": _ratio(resultat, c.get("assets")),
        "gross_margin": _ratio(c.get("gross_profit"), revenu),
        "operating_margin": _ratio(resultat_exploitation, revenu),
        "net_margin": _ratio(resultat, revenu),
    }

    # ROIC approche: resultat d'exploitation rapporte aux capitaux engages
    # (fonds propres + dettes). Approximation assumee - le calcul exact
    # demande le detail des dettes financieres et le taux d'impot effectif.
    dette = c.get("long_term_debt")
    out["roic"] = (_ratio(resultat_exploitation, fonds_propres + dette)
                   if fonds_propres is not None and dette is not None else None)

    revenu_avant = c.get("revenue_prec")
    bpa_avant = c.get("eps_prec")
    out["revenue_growth"] = (
        revenu / revenu_avant - 1
        if revenu is not None and revenu_avant is not None and revenu_avant > 0
        else None)
    # Un BPA qui passe par zero ou le negatif rend la croissance absurde
    out["eps_growth"] = (
        bpa / bpa_avant - 1
        if bpa is not None and bpa_avant is not None and bpa_avant > 0
        else None)

    if cours and cours > 0:
        capitalisation = cours * actions if actions else None
        out["pe"] = _ratio(cours, bpa) if bpa and bpa > 0 else None
        out["ps"] = _ratio(capitalisation, revenu)
        flux_libre = (tresorerie_exploitation - investissements
                      if tresorerie_exploitation is not None
                      and investissements is not None else None)
        out["fcf_yield"] = _ratio(flux_libre, capitalisation)
        # Rendement beneficiaire: l'inverse du PER, mais defini aussi pour
        # les societes en perte (un PER negatif n'a pas de sens, un rendement
        # negatif si). Evite d'ecarter les deficitaires du classement valeur.
        out["earnings_yield"] = (bpa / cours if bpa is not None else None)
        croissance = out.get("eps_growth")
        out["peg"] = (out["pe"] / (croissance * 100)
                      if out.get("pe") and croissance and croissance > 0
                      else None)
    else:
        out["pe"] = out["ps"] = out["fcf_yield"] = None
        out["earnings_yield"] = out["peg"] = None

    # Levier: utile en soi et composante du Altman Z
    out["debt_to_equity"] = _ratio(c.get("liabilities"), fonds_propres)
    out["_exercice"] = c.get("_exercice")
    out["_depot"] = c.get("_depot")
    return out


def ratios_au(faits: pd.DataFrame, as_of: date | str,
              cours: float | None = None) -> dict[str, float | None]:
    """Ratios calculables avec ce qui etait publie a `as_of`."""
    return ratios_depuis(composantes_au(faits, as_of), cours)


# -- acces rapide: les comptes comme fonction en escalier ----------------------

def table_depots(faits: pd.DataFrame) -> list[tuple[pd.Timestamp, dict]]:
    """Les comptes d'un titre, depot annuel par depot annuel.

    Entre deux depots rien ne change: la connaissance qu'on a d'une societe
    est une fonction en escalier dont les marches sont les dates de depot.
    Calculer une fois chaque marche (une quinzaine par titre) remplace des
    centaines de milliers de filtrages de la table des faits: mesurer 15 ans
    d'historique passe de plusieurs heures a quelques secondes.
    """
    if faits.empty:
        return []
    annuels = faits[faits["formulaire"].isin(FORMULAIRES_ANNUELS)]
    marches = []
    for d in sorted(annuels["depot"].unique()):
        c = composantes_au(faits, d)
        if c:
            marches.append((pd.Timestamp(d), c))
    return marches


def composantes_connues(marches: list[tuple[pd.Timestamp, dict]],
                        as_of: date | str,
                        anciennete_max_jours: int = ANCIENNETE_MAX_JOURS) -> dict:
    """Derniere marche publiee a `as_of` (recherche dichotomique).

    Renvoie {} si rien n'etait publie, ou si le dernier depot est trop ancien
    pour decrire encore la societe.
    """
    if not marches:
        return {}
    quand = pd.Timestamp(as_of)
    i = bisect.bisect_right([d for d, _ in marches], quand) - 1
    if i < 0:
        return {}
    depot, c = marches[i]
    if (quand - depot).days > anciennete_max_jours:
        return {}
    return c


def construire_comptes(faits_univers: pd.DataFrame) -> dict[str, list]:
    """Tables de depots de tout un univers: {ticker: marches}."""
    return {ticker: table_depots(f)
            for ticker, f in faits_univers.groupby("ticker")}


def panel(faits_univers: pd.DataFrame, dates, cours: dict | None = None
          ) -> pd.DataFrame:
    """Table (date, ticker) -> ratios, pour tout un univers.

    C'est l'entree du backtest fondamental honnete: a chaque date, chaque
    titre est note avec ce qui etait REELLEMENT publie ce jour-la.
    """
    comptes = construire_comptes(faits_univers)
    lignes = []
    for ticker, marches in comptes.items():
        for d in dates:
            px = (cours or {}).get((ticker, d))
            r = ratios_depuis(composantes_connues(marches, d), cours=px)
            if not r:
                continue
            r["ticker"] = ticker
            r["date"] = pd.Timestamp(d)
            lignes.append(r)
    if not lignes:
        return pd.DataFrame()
    return pd.DataFrame(lignes).set_index(["date", "ticker"]).sort_index()
