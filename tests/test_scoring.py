"""Composite score tests, including pillar renormalization."""

import pandas as pd
import pytest

from atlas.scoring.composite import composite_score


def test_renormalization_without_macro_sentiment():
    """Missing pillars must not dilute the composite toward 50."""
    f = pd.Series({"A": 100.0, "B": 0.0})
    t = pd.Series({"A": 100.0, "B": 0.0})
    s = pd.Series({"A": 100.0, "B": 0.0})
    df = composite_score(fundamental=f, technical=t, sector=s)
    assert df.loc["A", "composite"] == pytest.approx(100.0)
    assert df.loc["B", "composite"] == pytest.approx(0.0)
    # colonnes neutres presentes pour le stockage
    assert df.loc["A", "macro"] == 50.0
    assert df.loc["A", "sentiment"] == 50.0


def test_full_pillars_weighting():
    """La ponderation doit suivre la config, sans valeur codee en dur.

    L'ancienne version figeait 0.75/0.25: elle est tombee en panne le jour ou
    les poids ont change (audit du 2026-08-26). On recalcule desormais
    l'attendu a partir de la config elle-meme: c'est la MECANIQUE de
    ponderation qu'on teste, pas un jeu de poids particulier.
    """
    from atlas.config import get_config

    w = get_config().scoring_weights.normalized()
    f = pd.Series({"A": 80.0})
    t = pd.Series({"A": 80.0})
    s = pd.Series({"A": 80.0})
    df = composite_score(fundamental=f, technical=t, sector=s,
                         macro=50.0, sentiment=pd.Series({"A": 50.0}))
    attendu = (80.0 * (w["fundamental"] + w["technical"] + w["sector"])
               + 50.0 * (w["macro"] + w["sentiment"]))
    assert df.loc["A", "composite"] == pytest.approx(attendu, abs=0.1)


def test_pilier_technique_neutralise():
    """Verrou: le pilier technique ne doit plus peser sur le classement.

    Mesure du 2026-08-26 sur 2010-2026: IC de -0.008, et le top 10% de ce
    score fait PIRE que l'univers entier. Si quelqu'un lui redonne un poids,
    ce test tombe et oblige a justifier le choix.
    """
    from atlas.config import get_config

    assert get_config().scoring_weights.normalized()["technical"] == 0.0

    idx = ["A", "B", "C"]
    f = pd.Series([90.0, 60.0, 30.0], index=idx)
    sec = pd.Series([90.0, 60.0, 30.0], index=idx)
    fort = pd.Series([95.0, 95.0, 95.0], index=idx)
    faible = pd.Series([5.0, 5.0, 5.0], index=idx)
    a = composite_score(f, fort, sec, macro=80.0,
                        sentiment=pd.Series(50.0, index=idx))
    b = composite_score(f, faible, sec, macro=80.0,
                        sentiment=pd.Series(50.0, index=idx))
    assert (a["composite"].sort_index() == b["composite"].sort_index()).all()


def test_fundamental_score_spreads_to_percentiles():
    """The aggregated fundamental score must span the 0-100 range, not
    compress around 50 (rank-of-ranks)."""
    import numpy as np

    from atlas.scoring.composite import fundamental_score

    rng = np.random.default_rng(5)
    n = 200
    raw = pd.DataFrame({
        "roe": rng.normal(0.15, 0.1, n),
        "gross_margin": rng.normal(0.4, 0.15, n),
        "revenue_growth": rng.normal(0.08, 0.1, n),
        "pe": rng.lognormal(3.0, 0.5, n),
        "fcf_yield": rng.normal(0.04, 0.03, n),
    }, index=[f"T{i}" for i in range(n)])
    s = fundamental_score(raw)
    assert s.max() > 95
    assert s.min() < 5
    assert (s >= 80).sum() == pytest.approx(n * 0.2, abs=2)


def test_sorted_descending():
    f = pd.Series({"A": 10.0, "B": 90.0})
    t = pd.Series({"A": 10.0, "B": 90.0})
    s = pd.Series({"A": 10.0, "B": 90.0})
    df = composite_score(fundamental=f, technical=t, sector=s)
    assert list(df.index) == ["B", "A"]
