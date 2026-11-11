# -*- coding: utf-8 -*-
"""Surveillance croisee: le PC verifie que le gardien cloud tourne.

Regression du 2026-11-08: GitHub a desactive le workflow planifie apres 60
jours sans activite sur le depot. Le filet de securite est reste eteint trois
jours sans que rien ne le signale.
"""

from datetime import datetime, timezone

import pytest

from atlas.monitoring import gardien_cloud as gc

MAINTENANT = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)


class _Reponse:
    def __init__(self, contenu):
        self._contenu = contenu

    def raise_for_status(self):
        pass

    def json(self):
        return self._contenu


def _api(monkeypatch, state="active", dernier="2026-11-11T10:05:00Z",
         conclusion="success", workflows=None):
    def faux(url, **kwargs):
        if url.endswith("/workflows"):
            return _Reponse({"workflows": workflows if workflows is not None else [
                {"path": ".github/workflows/watchdog.yml", "state": state}]})
        runs = [] if dernier is None else [
            {"created_at": dernier, "conclusion": conclusion}]
        return _Reponse({"workflow_runs": runs})
    monkeypatch.setattr(gc.requests, "get", faux)


def test_gardien_sain(monkeypatch):
    _api(monkeypatch)
    assert gc.etat(MAINTENANT)["ok"] is True


def test_desactive_pour_inactivite(monkeypatch):
    """Le cas reel du 8 novembre."""
    _api(monkeypatch, state="disabled_inactivity", dernier="2026-11-08T16:33:00Z")
    e = gc.etat(MAINTENANT)
    assert e["ok"] is False
    assert "60 jours" in e["raison"]
    assert e["page"].endswith("watchdog.yml")


def test_actif_mais_muet(monkeypatch):
    """Etat 'active' mais plus aucune execution: tout aussi inquietant."""
    _api(monkeypatch, dernier="2026-11-05T10:00:00Z")
    e = gc.etat(MAINTENANT)
    assert e["ok"] is False and "depuis 6 jours" in e["raison"]


def test_derniere_execution_en_echec(monkeypatch):
    _api(monkeypatch, conclusion="failure")
    e = gc.etat(MAINTENANT)
    assert e["ok"] is False and "echec" in e["raison"]


def test_workflow_supprime(monkeypatch):
    _api(monkeypatch, workflows=[])
    assert gc.etat(MAINTENANT)["ok"] is False


def test_panne_reseau_n_est_pas_une_alerte(monkeypatch):
    """Le PC sans connexion ne doit pas crier que le gardien est mort."""
    def casse(url, **kwargs):
        raise ConnectionError("pas de reseau")
    monkeypatch.setattr(gc.requests, "get", casse)
    e = gc.etat(MAINTENANT)
    assert e["ok"] is None


@pytest.mark.parametrize("gardien,attendu", [
    ({"ok": False, "raison": "desactive par GitHub", "page": "https://x/y"}, True),
    ({"ok": True, "raison": "actif"}, False),
    ({"ok": None, "raison": "verification impossible"}, False),
    ({}, False),
])
def test_rapport_du_soir(gardien, attendu):
    from atlas.monitoring.notify import format_run_summary

    message = format_run_summary({
        "status": "ok", "scan": {"as_of": "2026-11-10"},
        "paper": {"equity": 96_500.0, "risk_actions": []},
        "gardien_cloud": gardien})
    assert ("HORS SERVICE" in message) is attendu
