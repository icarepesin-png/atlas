# -*- coding: utf-8 -*-
"""Ratios fondamentaux point-in-time.

Deux exigences se croisent ici et aucune n'est negociable:
- ne jamais utiliser un chiffre qui n'etait pas encore publie;
- ne jamais inventer un ratio dont une composante manque (une banque qui ne
  publie pas de marge brute ne doit pas se retrouver avec 0% et un mauvais
  rang, elle doit rester sans note sur ce critere).
"""

import pandas as pd
import pytest

from atlas.features.fundamental_pit import photo_annuelle, ratios_au


def _faits(lignes):
    """Meme conversion que `edgar.extraire`: les trois dates sont typees."""
    df = pd.DataFrame(lignes)
    for col in ("debut", "fin", "depot"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")
    return df


def _exercice(fin, depot, form="10-K", **grandeurs):
    return [{"ticker": "X", "grandeur": g, "valeur": float(v), "fin": fin,
             "depot": depot, "formulaire": form, "concept": g,
             "exercice": int(fin[:4]), "periode": "FY", "debut": None}
            for g, v in grandeurs.items()]


@pytest.fixture
def societe():
    """Deux exercices publies, plus un trimestre qui ne doit jamais servir."""
    return _faits(
        _exercice("2023-12-31", "2024-02-15", revenue=1000.0, net_income=100.0,
                  assets=2000.0, equity=500.0, gross_profit=400.0,
                  operating_income=150.0, eps_diluted=2.0,
                  shares_diluted=50.0, cash_from_ops=200.0, capex=50.0,
                  liabilities=1500.0, long_term_debt=300.0)
        + _exercice("2024-12-31", "2025-02-20", revenue=1200.0,
                    net_income=150.0, assets=2200.0, equity=600.0,
                    gross_profit=520.0, operating_income=200.0,
                    eps_diluted=3.0, shares_diluted=50.0,
                    cash_from_ops=260.0, capex=60.0, liabilities=1600.0,
                    long_term_debt=320.0)
        + _exercice("2025-06-30", "2025-07-25", form="10-Q",
                    revenue=9999.0, net_income=9999.0))


# -- point-in-time -------------------------------------------------------------

def test_exercice_non_publie_invisible(societe):
    """Le 1er janvier 2025, l'exercice 2024 n'est pas encore depose."""
    r = ratios_au(societe, "2025-01-01")
    assert r["_exercice"] == "2023-12-31"
    assert r["roe"] == pytest.approx(100.0 / 500.0)


def test_exercice_apparait_apres_depot(societe):
    r = ratios_au(societe, "2025-03-01")
    assert r["_exercice"] == "2024-12-31"
    assert r["roe"] == pytest.approx(150.0 / 600.0)


def test_trimestre_ignore(societe):
    """Un 10-Q ne doit pas ecraser l'exercice annuel de reference."""
    r = ratios_au(societe, "2025-08-01")
    assert r["_exercice"] == "2024-12-31"
    assert r["net_margin"] == pytest.approx(150.0 / 1200.0)


def test_avant_toute_publication(societe):
    assert ratios_au(societe, "2020-01-01") == {}


# -- calculs -------------------------------------------------------------------

def test_marges(societe):
    r = ratios_au(societe, "2025-03-01")
    assert r["gross_margin"] == pytest.approx(520.0 / 1200.0)
    assert r["operating_margin"] == pytest.approx(200.0 / 1200.0)
    assert r["roa"] == pytest.approx(150.0 / 2200.0)


def test_croissance_exige_deux_exercices_publies(societe):
    """Au 1er janvier 2025, un seul exercice est connu: pas de croissance."""
    assert ratios_au(societe, "2025-01-01")["revenue_growth"] is None
    r = ratios_au(societe, "2025-03-01")
    assert r["revenue_growth"] == pytest.approx(1200.0 / 1000.0 - 1)
    assert r["eps_growth"] == pytest.approx(3.0 / 2.0 - 1)


def test_valorisation_exige_le_cours(societe):
    sans = ratios_au(societe, "2025-03-01")
    assert sans["pe"] is None and sans["ps"] is None
    avec = ratios_au(societe, "2025-03-01", cours=30.0)
    assert avec["pe"] == pytest.approx(30.0 / 3.0)
    assert avec["ps"] == pytest.approx(30.0 * 50.0 / 1200.0)
    assert avec["fcf_yield"] == pytest.approx((260.0 - 60.0) / (30.0 * 50.0))


# -- refus de mentir -----------------------------------------------------------

def test_composante_manquante_donne_none():
    """Sans marge brute publiee, pas de marge brute - surtout pas zero."""
    faits = _faits(_exercice("2024-12-31", "2025-02-20", revenue=1000.0,
                             net_income=100.0, equity=500.0))
    r = ratios_au(faits, "2025-03-01")
    assert r["gross_margin"] is None
    assert r["roe"] == pytest.approx(0.2)


def test_capitaux_propres_negatifs_donnent_none():
    """Un ROE calcule sur des fonds propres negatifs n'a aucun sens."""
    faits = _faits(_exercice("2024-12-31", "2025-02-20", revenue=1000.0,
                             net_income=100.0, equity=-200.0))
    assert ratios_au(faits, "2025-03-01")["roe"] is None


def test_bpa_precedent_negatif_pas_de_croissance():
    """Passer d'une perte a un benefice ne se mesure pas en pourcentage."""
    faits = _faits(
        _exercice("2023-12-31", "2024-02-15", eps_diluted=-1.0, revenue=100.0)
        + _exercice("2024-12-31", "2025-02-20", eps_diluted=2.0, revenue=120.0))
    assert ratios_au(faits, "2025-03-01")["eps_growth"] is None


def test_pe_sur_perte_est_none():
    faits = _faits(_exercice("2024-12-31", "2025-02-20", eps_diluted=-2.0,
                             revenue=100.0, net_income=-50.0))
    assert ratios_au(faits, "2025-03-01", cours=30.0)["pe"] is None


def test_photo_vide_sur_table_vide():
    assert photo_annuelle(pd.DataFrame(), "2025-01-01").empty
    assert ratios_au(pd.DataFrame(), "2025-01-01") == {}


# -- le piege des trimestres caches dans un depot annuel -----------------------

def _periode(debut, fin, depot, form="10-K", **grandeurs):
    return [{"ticker": "X", "grandeur": g, "valeur": float(v), "fin": fin,
             "debut": debut, "depot": depot, "formulaire": form, "concept": g,
             "exercice": int(fin[:4]), "periode": "FY"}
            for g, v in grandeurs.items()]


@pytest.fixture
def depot_annuel_avec_trimestres():
    """Un 10-K reel contient l'exercice ET ses trimestres.

    Cas Micron: comparer l'annee au dernier trimestre affichait +290% de
    croissance au lieu de +49%.
    """
    return _faits(
        _periode("2016-09-02", "2017-08-31", "2018-10-15", revenue=20322.0)
        + _periode("2017-09-01", "2018-08-30", "2018-10-15", revenue=30391.0)
        + _periode("2018-03-02", "2018-05-31", "2018-10-15", revenue=7797.0)
        + _periode("2018-06-01", "2018-08-30", "2018-10-15", revenue=8440.0))


def test_trimestre_du_depot_annuel_ignore(depot_annuel_avec_trimestres):
    photo = photo_annuelle(depot_annuel_avec_trimestres, "2019-06-30")
    assert photo[photo.grandeur == "revenue"].valeur.iloc[0] == 30391.0


def test_croissance_compare_deux_exercices(depot_annuel_avec_trimestres):
    r = ratios_au(depot_annuel_avec_trimestres, "2019-06-30")
    assert r["revenue_growth"] == pytest.approx(30391.0 / 20322.0 - 1, abs=1e-6)
    assert r["revenue_growth"] < 0.6, "croissance aberrante: trimestre compare a une annee"


def test_solde_de_bilan_sans_date_de_debut_conserve():
    """Actif et capitaux propres sont des instantanes: pas de date de debut,
    donc pas de filtre de duree a leur appliquer."""
    faits = _faits(_periode(None, "2024-12-31", "2025-02-20", revenue=1000.0)
                   + [{"ticker": "X", "grandeur": "assets", "valeur": 5000.0,
                       "fin": "2024-12-31", "debut": None,
                       "depot": "2025-02-20", "formulaire": "10-K",
                       "concept": "Assets", "exercice": 2024, "periode": "FY"}])
    photo = photo_annuelle(faits, "2025-03-01")
    assert "assets" in set(photo.grandeur)
