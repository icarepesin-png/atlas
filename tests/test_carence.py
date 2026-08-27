# -*- coding: utf-8 -*-
"""Delai de carence apres une sortie perdante.

Sur les 39 premiers trades, 8 titres re-trades concentraient -3 921 USD, soit
72% de la perte totale (WDC 5 fois, EOG 4 fois). Le systeme rachetait ce qui
venait de le faire sortir.
"""

from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine, text

from atlas.pipelines.paper_trade import _en_carence


@pytest.fixture
def base(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path/'t.db'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE trades (ticker TEXT, closed_at TEXT,"
                          " pnl REAL, exit_reason TEXT)"))
    return engine


def _ajoute(engine, ticker, jours, pnl, raison="stop initial"):
    quand = (date.today() - timedelta(days=jours)).isoformat() + "T23:00:00"
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO trades VALUES (:t, :c, :p, :r)"),
                     {"t": ticker, "c": quand, "p": pnl, "r": raison})


def test_sortie_perdante_recente_bloque(base):
    _ajoute(base, "WDC", 5, -400.0)
    assert "WDC" in _en_carence(base, 20)


def test_sortie_perdante_ancienne_ne_bloque_plus(base):
    _ajoute(base, "WDC", 40, -400.0)
    assert "WDC" not in _en_carence(base, 20)


def test_sortie_gagnante_ne_bloque_pas(base):
    """Reprendre un titre qui a bien travaille n'a rien de suspect."""
    _ajoute(base, "NTAP", 5, +800.0)
    assert "NTAP" not in _en_carence(base, 20)


def test_carence_desactivee(base):
    _ajoute(base, "WDC", 1, -400.0)
    assert _en_carence(base, 0) == {}


def test_la_derniere_sortie_fait_foi(base):
    """Un titre gagnant puis perdant reste bloque par la perte."""
    _ajoute(base, "EOG", 30, -200.0)
    _ajoute(base, "EOG", 2, -150.0)
    assert "EOG" in _en_carence(base, 20)


def test_plusieurs_titres(base):
    _ajoute(base, "WDC", 3, -400.0)
    _ajoute(base, "STX", 10, -200.0)
    _ajoute(base, "MU", 60, -900.0)
    assert set(_en_carence(base, 20)) == {"WDC", "STX"}


def test_vente_de_correction_ne_bloque_pas(base):
    """Reparer un doublon d'execution n'est pas une these qui echoue."""
    _ajoute(base, "FTNT", 2, -197.0,
            raison="correction: doublon d'execution du 2026-08-08")
    assert "FTNT" not in _en_carence(base, 20)
