# -*- coding: utf-8 -*-
"""Surveillance de l'IC des piliers.

Regression: la table factor_performance est restee vide de juin a aout 2026
alors que le pilier technique produisait un IC de -0.289. La mesure existait,
rien ne l'appelait.
"""

import numpy as np
import pytest
import pandas as pd

from atlas.learning.feedback import compute_factor_ic


def _scores(n=60, graine=0):
    rng = np.random.default_rng(graine)
    return pd.DataFrame({
        "fundamental": rng.uniform(0, 100, n),
        "technical": rng.uniform(0, 100, n),
        "macro": np.full(n, 80.0),          # pilier constant
    }, index=[f"T{i}" for i in range(n)])


def test_ic_detecte_un_signal_a_l_envers():
    """Un pilier parfaitement inverse doit ressortir tres negatif."""
    s = _scores()
    fwd = pd.Series(-s["technical"].to_numpy() / 100, index=s.index)
    ic = compute_factor_ic(s, fwd, factors=["technical"])
    assert ic["technical"] < -0.9


def test_ic_detecte_un_bon_signal():
    s = _scores()
    fwd = pd.Series(s["fundamental"].to_numpy() / 100, index=s.index)
    ic = compute_factor_ic(s, fwd, factors=["fundamental"])
    assert ic["fundamental"] > 0.9


def test_pilier_constant_ne_donne_pas_d_ic():
    """macro identique pour tous: l'IC est indefini, pas 0."""
    s = _scores()
    fwd = pd.Series(np.linspace(-0.1, 0.1, len(s)), index=s.index)
    ic = compute_factor_ic(s, fwd, factors=["macro"])
    assert np.isnan(ic["macro"])


def test_echantillon_trop_petit_refuse():
    s = _scores(n=10)
    fwd = pd.Series(np.linspace(-0.1, 0.1, 10), index=s.index)
    assert compute_factor_ic(s, fwd) == {}


# -- alerte: un pilier qui pese alors que son signal est inverse ----------------

def _historique(monkeypatch, lignes):
    from atlas.pipelines import suivi_facteurs

    monkeypatch.setattr(suivi_facteurs, "read_table",
                        lambda table: pd.DataFrame(lignes))
    return suivi_facteurs


def _nuits(facteur, ic, n=20, horizon=21):
    return [{"as_of_date": f"2026-09-{j + 1:02d}", "factor": facteur,
             "ic": ic, "forward_days": horizon} for j in range(n)]


def test_pilier_actif_a_l_envers_declenche_l_alerte(monkeypatch):
    sf = _historique(monkeypatch, _nuits("fundamental", -0.08))
    alertes = sf.piliers_a_l_envers()
    assert [a["pilier"] for a in alertes] == ["fundamental"]
    assert alertes[0]["ic"] == pytest.approx(-0.08)


def test_pilier_neutralise_ne_declenche_rien(monkeypatch):
    """Le technique est a poids nul: son IC negatif n'est plus un danger."""
    sf = _historique(monkeypatch, _nuits("technical", -0.20))
    assert sf.piliers_a_l_envers() == []


def test_trois_nuits_de_bruit_ne_suffisent_pas(monkeypatch):
    sf = _historique(monkeypatch, _nuits("fundamental", -0.30, n=3))
    assert sf.piliers_a_l_envers() == []


def test_pilier_sain_ne_declenche_rien(monkeypatch):
    sf = _historique(monkeypatch, _nuits("fundamental", +0.04))
    assert sf.piliers_a_l_envers() == []


def test_alerte_visible_dans_le_rapport_du_soir():
    from atlas.monitoring.notify import format_run_summary

    sante = {"status": "ok", "scan": {"as_of": "2026-11-10"},
             "paper": {"equity": 96_500.0, "risk_actions": []},
             "facteurs": {"alertes": [{"pilier": "fundamental", "ic": -0.081,
                                       "mesures": 20, "poids": 0.7}]}}
    message = format_run_summary(sante)
    assert "fundamental" in message and "-0.081" in message
    assert "l'envers" in message
