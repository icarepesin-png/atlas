# -*- coding: utf-8 -*-
"""Courbe d'equity recalculee depuis les ordres.

Ce que ces tests protegent: une courbe qui ne depend ni de l'heure ni du jour
ou les runs ont tourne, et qui ne confond jamais des pence avec des dollars.
"""

from datetime import datetime, timezone

import pandas as pd
import pytest

from atlas.pipelines import equity_recalc as er


# -- rattachement d'un ordre a sa seance ---------------------------------------

def test_ordre_recent_porte_sa_seance():
    assert er.seance_d_un_ordre("2026-11-09", "2026-11-10T19:05:00+00:00") \
        == pd.Timestamp("2026-11-09")


@pytest.mark.parametrize("execute_le,attendue", [
    ("2026-09-29T21:30:00+00:00", "2026-09-29"),   # 23h30 Paris: seance close
    ("2026-09-29T17:05:00+00:00", "2026-09-28"),   # en pleine seance: la veille
    ("2026-09-30T10:00:00+00:00", "2026-09-29"),   # rattrapage du lendemain midi
    ("2026-11-07T11:40:00+00:00", "2026-11-06"),   # samedi: seance de vendredi
])
def test_ordre_ancien_rattache_a_la_seance_du_run(execute_le, attendue):
    """Sans colonne `seance`, on deduit de l'horodatage la seance traitee."""
    assert er.seance_d_un_ordre(None, execute_le) == pd.Timestamp(attendue)


def test_horodatage_sans_fuseau_lu_comme_utc():
    assert er.seance_d_un_ordre(None, "2026-09-29T21:30:00") \
        == pd.Timestamp("2026-09-29")


# -- taux de change ------------------------------------------------------------

def _fx():
    jours = pd.to_datetime(["2026-10-01", "2026-10-02"])
    return {"GBp": pd.Series([0.0130, 0.0131], index=jours),
            "EUR": pd.Series([1.10, 1.11], index=jours)}


def test_usd_vaut_toujours_un():
    assert er._taux({}, "USD", pd.Timestamp("2020-01-01")) == 1.0


def test_taux_du_jour_ou_dernier_connu():
    assert er._taux(_fx(), "EUR", pd.Timestamp("2026-10-02")) == 1.11
    assert er._taux(_fx(), "EUR", pd.Timestamp("2026-10-05")) == 1.11


def test_pas_de_repli_a_un_pour_une_devise_etrangere():
    """Avant le debut de l'historique, on prend le plus ancien taux connu.

    Un repli silencieux sur 1,0 comptait une action Shell a 3 371 pence pour
    3 371 dollars: le cash recalcule de la campagne 1 ressortait a -352 781.
    """
    assert er._taux(_fx(), "GBp", pd.Timestamp("2026-06-11")) == 0.0130


# -- reconstruction ------------------------------------------------------------

@pytest.fixture
def base(tmp_path, monkeypatch):
    from sqlalchemy import create_engine, text

    engine = create_engine(f"sqlite:///{tmp_path/'e.db'}")
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE orders (id INTEGER PRIMARY KEY, ticker TEXT, side TEXT,"
            " qty REAL, filled_price REAL, filled_at TEXT, status TEXT,"
            " campagne INTEGER, seance TEXT)"))
    jours = pd.bdate_range("2026-10-05", "2026-10-09")
    cours = pd.DataFrame({"close": [100.0, 102.0, 104.0, 103.0, 105.0]}, index=jours)
    monkeypatch.setattr(er, "load_ohlcv",
                        lambda t: cours if t == "AAA" else pd.DataFrame())
    monkeypatch.setattr(er, "_series_fx", lambda depuis=None: {})
    monkeypatch.setattr(er, "seance_de_reference",
                        lambda now=None: (now.date() if now else
                                          pd.Timestamp("2026-10-09").date()))
    return engine


def _ordre(engine, ticker, side, qty, prix, seance, campagne=1):
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO orders (ticker, side, qty, filled_price, filled_at,"
            " status, campagne, seance) VALUES (:t, :s, :q, :p, :f, 'filled',"
            " :c, :se)"), {"t": ticker, "s": side, "q": qty, "p": prix,
                           "f": f"{seance}T21:30:00+00:00", "c": campagne,
                           "se": seance})


def test_une_valeur_par_seance_sans_trou(base):
    _ordre(base, "AAA", "buy", 10, 100.0, "2026-10-05")
    courbe = er.reconstruire(base, 1, 10_000.0)
    assert list(courbe.date) == ["2026-10-05", "2026-10-06", "2026-10-07",
                                 "2026-10-08", "2026-10-09"]
    # 9 000 de cash + 10 titres valorises a la cloture de chaque seance
    assert list(courbe.equity) == [10_000.0, 10_020.0, 10_040.0, 10_030.0, 10_050.0]


def test_vente_fige_le_resultat(base):
    _ordre(base, "AAA", "buy", 10, 100.0, "2026-10-05")
    _ordre(base, "AAA", "sell", 10, 104.0, "2026-10-07")
    courbe = er.reconstruire(base, 1, 10_000.0)
    assert courbe.equity.iloc[-1] == 10_040.0
    assert courbe.positions.iloc[-1] == 0


def test_les_campagnes_ne_se_melangent_pas(base):
    _ordre(base, "AAA", "buy", 10, 100.0, "2026-10-05", campagne=1)
    _ordre(base, "AAA", "buy", 50, 102.0, "2026-10-06", campagne=2)
    c1 = er.reconstruire(base, 1, 10_000.0)
    c2 = er.reconstruire(base, 2, 10_000.0)
    assert c1.positions.iloc[-1] == 1 and c1.equity.iloc[-1] == 10_050.0
    assert c2.date.iloc[0] == "2026-10-06"
    assert c2.equity.iloc[-1] == pytest.approx(10_000 + 50 * (105 - 102))


def test_campagne_sans_ordre_part_de_sa_date_de_debut(base):
    courbe = er.reconstruire(base, 3, 10_000.0, debut="2026-10-07T09:00:00")
    assert list(courbe.equity) == [10_000.0] * 3
