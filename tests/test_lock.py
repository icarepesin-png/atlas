# -*- coding: utf-8 -*-
"""Verrou d'execution: empeche deux runs simultanes.

Regression du 2026-08-08: deux rattrapages lances a la meme seconde ont
achete GEN et FTNT en double (positions a 10% pour un plafond de 5%).
"""

import os
from datetime import datetime, timedelta

import pytest

from atlas.pipelines.lock import DejaEnCours, _chemin, run_lock


@pytest.fixture(autouse=True)
def _nettoie():
    f = _chemin("test-verrou")
    f.unlink(missing_ok=True)
    yield
    f.unlink(missing_ok=True)


def test_un_seul_detenteur():
    with run_lock("test-verrou"):
        with pytest.raises(DejaEnCours):
            with run_lock("test-verrou"):
                pytest.fail("deux runs ont obtenu le verrou en meme temps")


def test_libere_a_la_sortie():
    with run_lock("test-verrou"):
        pass
    with run_lock("test-verrou"):
        pass  # doit pouvoir etre repris immediatement


def test_libere_meme_en_cas_d_erreur():
    with pytest.raises(ValueError):
        with run_lock("test-verrou"):
            raise ValueError("boum")
    assert not _chemin("test-verrou").exists()


def test_verrou_d_un_processus_mort_est_repris():
    """Un plantage ne doit pas bloquer ATLAS jusqu'a intervention manuelle."""
    f = _chemin("test-verrou")
    # PID invraisemblable + date recente: seul le PID mort justifie la reprise
    f.write_text(f"999999999 {datetime.now().isoformat()}", encoding="utf-8")
    with run_lock("test-verrou"):
        pass


def test_verrou_perime_est_repris():
    f = _chemin("test-verrou")
    vieux = (datetime.now() - timedelta(hours=5)).isoformat()
    f.write_text(f"{os.getpid()} {vieux}", encoding="utf-8")
    with run_lock("test-verrou", perime_apres=timedelta(hours=2)):
        pass


def test_verrou_illisible_est_repris():
    f = _chemin("test-verrou")
    f.write_text("contenu corrompu", encoding="utf-8")
    with run_lock("test-verrou"):
        pass


def test_verrou_du_processus_courant_tient():
    """Un verrou vivant et recent ne doit JAMAIS etre vole."""
    f = _chemin("test-verrou")
    f.write_text(f"{os.getpid()} {datetime.now().isoformat()}", encoding="utf-8")
    with pytest.raises(DejaEnCours):
        with run_lock("test-verrou"):
            pass
