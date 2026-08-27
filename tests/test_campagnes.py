# -*- coding: utf-8 -*-
"""Campagnes de test: numeroter les periodes au lieu d'effacer l'historique.

Changer de strategie en cours de route et melanger les trades avant/apres rend
toute statistique ininterpretable. Mais effacer le passe quand le resultat
deplait est pire encore. D'ou la numerotation.
"""

from sqlalchemy import create_engine, text

from atlas.data.store import campagne_courante


def _base(tmp_path, lignes=()):
    engine = create_engine(f"sqlite:///{tmp_path/'c.db'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE campagnes (id INTEGER PRIMARY KEY,"
                          " nom TEXT, debut TEXT, fin TEXT)"))
        for id_, fin in lignes:
            conn.execute(text("INSERT INTO campagnes (id, nom, debut, fin)"
                              " VALUES (:i, 'x', '2026-01-01', :f)"),
                         {"i": id_, "f": fin})
    return engine


def test_sans_table_la_campagne_est_1(tmp_path):
    """Une base d'avant le mecanisme doit rester lisible."""
    engine = create_engine(f"sqlite:///{tmp_path/'vide.db'}")
    assert campagne_courante(engine) == 1


def test_aucune_campagne_declaree(tmp_path):
    assert campagne_courante(_base(tmp_path)) == 1


def test_campagne_ouverte(tmp_path):
    engine = _base(tmp_path, [(1, "2026-08-27T10:00:00"), (2, None)])
    assert campagne_courante(engine) == 2


def test_toutes_closes_ne_remonte_pas_le_temps(tmp_path):
    """Si tout est ferme, on ne doit pas repartir sur une campagne close."""
    engine = _base(tmp_path, [(1, "2026-08-27T10:00:00")])
    assert campagne_courante(engine) == 1


def test_plusieurs_campagnes_la_derniere_ouverte_gagne(tmp_path):
    engine = _base(tmp_path, [(1, "2026-06-01T00:00:00"),
                              (2, "2026-08-01T00:00:00"), (3, None)])
    assert campagne_courante(engine) == 3
