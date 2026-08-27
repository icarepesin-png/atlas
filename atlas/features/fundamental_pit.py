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


def photo_annuelle(faits: pd.DataFrame, as_of: date | str,
                   rang: int = 0) -> pd.DataFrame:
    """Exercice annuel connu a `as_of`. rang=1 donne le precedent.

    Sert a la croissance: comparer deux exercices dont les DEUX etaient
    publies a la date consideree.
    """
    if faits.empty:
        return faits
    vus = faits[(faits["depot"] <= pd.Timestamp(as_of))
                & (faits["formulaire"].isin(FORMULAIRES_ANNUELS))]
    if vus.empty:
        return vus
    exercices = sorted(vus["fin"].unique())
    if len(exercices) <= rang:
        return vus.iloc[0:0]
    cible = exercices[-1 - rang]
    lot = vus[vus["fin"] == cible].sort_values("depot")
    return lot.groupby("grandeur", as_index=False).first()


def ratios_au(faits: pd.DataFrame, as_of: date | str,
              cours: float | None = None) -> dict[str, float | None]:
    """Ratios calculables avec ce qui etait publie a `as_of`.

    `cours` (facultatif) debloque les ratios de valorisation, qui ont besoin
    du prix du jour en plus des comptes.
    """
    actuel = photo_annuelle(faits, as_of)
    if actuel.empty:
        return {}
    precedent = photo_annuelle(faits, as_of, rang=1)

    revenu = _valeur(actuel, "revenue")
    resultat = _valeur(actuel, "net_income")
    actif = _valeur(actuel, "assets")
    fonds_propres = _valeur(actuel, "equity")
    marge_brute = _valeur(actuel, "gross_profit")
    resultat_exploitation = _valeur(actuel, "operating_income")
    tresorerie_exploitation = _valeur(actuel, "cash_from_ops")
    investissements = _valeur(actuel, "capex")
    bpa = _valeur(actuel, "eps_diluted")
    actions = _valeur(actuel, "shares_diluted")
    passif = _valeur(actuel, "liabilities")

    out: dict[str, float | None] = {
        "roe": _ratio(resultat, fonds_propres),
        "roa": _ratio(resultat, actif),
        "gross_margin": _ratio(marge_brute, revenu),
        "operating_margin": _ratio(resultat_exploitation, revenu),
        "net_margin": _ratio(resultat, revenu),
    }

    # ROIC approche: resultat d'exploitation rapporte aux capitaux engages
    # (fonds propres + dettes). Approximation assumee - le calcul exact
    # demande le detail des dettes financieres et le taux d'impot effectif.
    dette = _valeur(actuel, "long_term_debt")
    if fonds_propres is not None and dette is not None:
        out["roic"] = _ratio(resultat_exploitation, fonds_propres + dette)
    else:
        out["roic"] = None

    # Croissance: les deux exercices doivent avoir ete publies a `as_of`
    if not precedent.empty:
        revenu_avant = _valeur(precedent, "revenue")
        bpa_avant = _valeur(precedent, "eps_diluted")
        out["revenue_growth"] = (
            revenu / revenu_avant - 1
            if revenu is not None and revenu_avant not in (None, 0)
            and revenu_avant > 0 else None)
        # Un BPA qui passe par zero ou le negatif rend la croissance absurde
        out["eps_growth"] = (
            bpa / bpa_avant - 1
            if bpa is not None and bpa_avant is not None and bpa_avant > 0
            else None)
    else:
        out["revenue_growth"] = out["eps_growth"] = None

    # Valorisation: necessite le cours du jour
    if cours and cours > 0:
        capitalisation = cours * actions if actions else None
        out["pe"] = _ratio(cours, bpa) if bpa and bpa > 0 else None
        out["ps"] = _ratio(capitalisation, revenu)
        flux_libre = (tresorerie_exploitation - investissements
                      if tresorerie_exploitation is not None
                      and investissements is not None else None)
        out["fcf_yield"] = _ratio(flux_libre, capitalisation)
        croissance = out.get("eps_growth")
        out["peg"] = (out["pe"] / (croissance * 100)
                      if out.get("pe") and croissance and croissance > 0
                      else None)
    else:
        out["pe"] = out["ps"] = out["fcf_yield"] = out["peg"] = None

    # Levier: utile en soi et composante du Altman Z
    out["debt_to_equity"] = _ratio(passif, fonds_propres)
    out["_exercice"] = str(actuel["fin"].iloc[0].date())
    out["_depot"] = str(actuel["depot"].iloc[0].date())
    return out


def panel(faits_univers: pd.DataFrame, dates, cours: dict | None = None
          ) -> pd.DataFrame:
    """Table (date, ticker) -> ratios, pour tout un univers.

    C'est l'entree du backtest fondamental honnete: a chaque date, chaque
    titre est note avec ce qui etait REELLEMENT publie ce jour-la.
    """
    lignes = []
    for ticker, faits in faits_univers.groupby("ticker"):
        for d in dates:
            px = (cours or {}).get((ticker, d))
            r = ratios_au(faits, d, cours=px)
            if not r:
                continue
            r["ticker"] = ticker
            r["date"] = pd.Timestamp(d)
            lignes.append(r)
    if not lignes:
        return pd.DataFrame()
    return pd.DataFrame(lignes).set_index(["date", "ticker"]).sort_index()
