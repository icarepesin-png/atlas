# -*- coding: utf-8 -*-
"""Fondamentaux point-in-time EDGAR.

Le test qui compte est `test_un_chiffre_non_encore_depose_est_invisible`: si
un jour il tombe, le backtest se remet a acheter le passe en connaissant
l'avenir, et tous ses resultats redeviennent des mirages.

Aucun appel reseau ici: on fabrique des faits comme l'API les renvoie.
"""

import os

import pandas as pd
import pytest

from atlas.data.edgar import (SecUserAgentManquant, connu_au, entetes,
                              extraire)


def _fait(val, fin, depot, form="10-Q"):
    return {"val": val, "end": fin, "filed": depot, "form": form,
            "fy": int(fin[:4]), "fp": "Q2", "start": None}


@pytest.fixture
def brut():
    """companyfacts miniature: deux exercices de resultat net et un actif."""
    return {"facts": {"us-gaap": {
        "NetIncomeLoss": {"units": {"USD": [
            _fait(100.0, "2024-05-30", "2024-06-27"),
            _fait(778.0, "2024-08-29", "2024-10-04", "10-K"),
            _fait(900.0, "2025-08-28", "2025-10-03", "10-K"),
        ]}},
        "Assets": {"units": {"USD": [
            _fait(66_255.0, "2024-05-30", "2024-06-27"),
            _fait(69_416.0, "2024-08-29", "2024-10-04", "10-K"),
        ]}},
        # Concept abandonne depuis 2013: ne doit pas ressortir comme actuel
        "LongTermDebt": {"units": {"USD": [
            _fait(3_267.0, "2013-05-30", "2013-07-08"),
        ]}},
    }}}


# -- identification exigee par la SEC ------------------------------------------

def test_user_agent_manquant_leve_une_erreur_explicite(monkeypatch):
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    with pytest.raises(SecUserAgentManquant) as e:
        entetes()
    assert "SEC_USER_AGENT" in str(e.value)


def test_user_agent_sans_contact_est_refuse(monkeypatch):
    """La SEC exige un moyen de contact: un UA sans adresse sera bloque."""
    monkeypatch.setenv("SEC_USER_AGENT", "ATLAS")
    with pytest.raises(SecUserAgentManquant):
        entetes()


def test_user_agent_valide(monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", "ATLAS research contact@exemple.com")
    assert "@" in entetes()["User-Agent"]


# -- extraction ----------------------------------------------------------------

def test_extraction_aplatit_les_faits(brut):
    df = extraire(brut, "MU")
    assert set(df["grandeur"]) == {"net_income", "assets", "long_term_debt"}
    assert df["ticker"].unique().tolist() == ["MU"]
    assert pd.api.types.is_datetime64_any_dtype(df["depot"])


def test_extraction_ignore_les_valeurs_vides():
    brut = {"facts": {"us-gaap": {"Assets": {"units": {"USD": [
        {"val": None, "end": "2024-05-30", "filed": "2024-06-27", "form": "10-Q"},
        {"val": 5.0, "end": "2024-05-30", "filed": None, "form": "10-Q"},
    ]}}}}}
    assert extraire(brut, "X").empty


def test_extraction_sans_donnees_us_gaap():
    assert extraire({"facts": {}}, "X").empty


# -- LE test: point-in-time ----------------------------------------------------

def test_un_chiffre_non_encore_depose_est_invisible(brut):
    """Le resultat annuel depose le 2024-10-04 ne doit PAS exister le 01/09."""
    df = extraire(brut, "MU")
    avant = connu_au(df, "2024-09-01")
    net = avant[avant["grandeur"] == "net_income"].iloc[0]
    assert net["valeur"] == 100.0          # le trimestre de mai
    assert str(net["fin"].date()) == "2024-05-30"


def test_le_meme_chiffre_apparait_apres_son_depot(brut):
    df = extraire(brut, "MU")
    apres = connu_au(df, "2024-10-10")
    net = apres[apres["grandeur"] == "net_income"].iloc[0]
    assert net["valeur"] == 778.0
    assert str(net["fin"].date()) == "2024-08-29"


def test_aucun_depot_anterieur_renvoie_vide(brut):
    assert connu_au(extraire(brut, "MU"), "2020-01-01").empty


def test_grandeur_perimee_ecartee(brut):
    """Une dette longue de 2013 n'est pas une donnee 'connue' en 2024.

    Techniquement elle a bien ete deposee avant; comptablement elle n'a plus
    aucun sens. Sans ce filtre, Micron sortait un endettement vieux de 11 ans.
    """
    connu = connu_au(extraire(brut, "MU"), "2024-09-01")
    assert "long_term_debt" not in set(connu["grandeur"])


def test_anciennete_configurable(brut):
    large = connu_au(extraire(brut, "MU"), "2024-09-01",
                     anciennete_max_mois=12 * 20)
    assert "long_term_debt" in set(large["grandeur"])


def test_formulaires_filtres(brut):
    """Un 8-K (communique) n'est pas un etat financier verifie."""
    df = extraire(brut, "MU")
    assert connu_au(df, "2024-10-10", formulaires=("20-F",)).empty


def test_table_vide_ne_casse_pas():
    assert connu_au(pd.DataFrame(), "2024-01-01").empty
