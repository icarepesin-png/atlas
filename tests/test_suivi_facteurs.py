# -*- coding: utf-8 -*-
"""Surveillance de l'IC des piliers.

Regression: la table factor_performance est restee vide de juin a aout 2026
alors que le pilier technique produisait un IC de -0.289. La mesure existait,
rien ne l'appelait.
"""

import numpy as np
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
