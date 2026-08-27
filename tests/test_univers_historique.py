# -*- coding: utf-8 -*-
"""Composition historique du S&P 500 (correction du biais du survivant).

Ce que ces tests protegent: la capacite a retrouver les societes SORTIES de
l'indice. Sans elles, l'echantillon ne contient que des gagnants et toute
mesure de facteur devient ininterpretable - on a mesure une prime a la
volatilite (t = -1.96) et un momentum nul, ce qui n'a aucun sens autrement.
"""

import json

import pandas as pd
import pytest

from atlas.universe import historique


TABLE_ANCIENNE = """
<table class="wikitable"><tr>
  <th>Ticker symbol</th><th>Company</th><th>GICS Sector</th></tr>
  <tr><td>AA</td><td>Alcoa</td><td>Materials</td></tr>
  <tr><td>AAPL</td><td>Apple Inc.</td><td>Information Technology</td></tr>
  <tr><td>BRK.B</td><td>Berkshire Hathaway</td><td>Financials</td></tr>
</table>
<table class="wikitable"><tr><th>x</th></tr><tr><td>1</td></tr></table>
"""

TABLE_RECENTE = """
<table class="wikitable"><tr>
  <th>Symbol</th><th>Security</th><th>GICS Sector</th></tr>
  <tr><td>AAPL</td><td>Apple Inc.</td><td>Information Technology</td></tr>
  <tr><td>NVDA</td><td>Nvidia</td><td>Information Technology</td></tr>
</table>
"""


@pytest.fixture(autouse=True)
def _cache_isole(tmp_path, monkeypatch):
    monkeypatch.setattr(historique, "_dossier", lambda: tmp_path)
    monkeypatch.setattr(historique.time, "sleep", lambda *_: None)


def _repondeur(html, monkeypatch, revid=123):
    """Simule l'API MediaWiki: une revision, puis son contenu."""
    def faux(params, timeout=45):
        if params["action"] == "query":
            return {"query": {"pages": {"1": {"revisions": [
                {"revid": revid, "timestamp": "2012-12-28T10:00:00Z"}]}}}}
        return {"parse": {"text": {"*": html}}}
    monkeypatch.setattr(historique, "_demander", faux)


# -- extraction ----------------------------------------------------------------

def test_ancien_intitule_de_colonne(monkeypatch):
    """Jusque vers 2019 la colonne s'appelait 'Ticker symbol'."""
    _repondeur(TABLE_ANCIENNE, monkeypatch)
    tickers = historique.composition_au("2013-01-01")
    assert "AA" in tickers, "Alcoa doit etre retrouve: c'est tout l'interet"
    assert "AAPL" in tickers


def test_intitule_recent(monkeypatch):
    _repondeur(TABLE_RECENTE, monkeypatch)
    assert set(historique.composition_au("2024-01-01")) == {"AAPL", "NVDA"}


def test_normalisation_des_categories_b(monkeypatch):
    """Wikipedia ecrit BRK.B, Yahoo attend BRK-B."""
    _repondeur(TABLE_ANCIENNE, monkeypatch)
    assert "BRK-B" in historique.composition_au("2013-01-01")


def test_la_plus_grande_table_est_retenue(monkeypatch):
    """La page contient des tables annexes: seule celle des composants compte."""
    _repondeur(TABLE_ANCIENNE, monkeypatch)
    assert len(historique.composition_au("2013-01-01")) == 3


# -- cache ---------------------------------------------------------------------

def test_composition_mise_en_cache(monkeypatch, tmp_path):
    _repondeur(TABLE_RECENTE, monkeypatch)
    historique.composition_au("2024-01-01")
    fichier = tmp_path / "sp500_2024-01-01.json"
    assert fichier.exists()
    contenu = json.loads(fichier.read_text(encoding="utf-8"))
    assert contenu["revid"] == 123 and "AAPL" in contenu["tickers"]


def test_relecture_sans_reseau(monkeypatch, tmp_path):
    """Une composition passee ne change jamais: pas de second appel."""
    _repondeur(TABLE_RECENTE, monkeypatch)
    historique.composition_au("2024-01-01")

    def interdit(*a, **k):
        raise AssertionError("le cache aurait du suffire")

    monkeypatch.setattr(historique, "_demander", interdit)
    assert set(historique.composition_au("2024-01-01")) == {"AAPL", "NVDA"}


# -- garde-fous ----------------------------------------------------------------

def test_avant_2010_ignore(monkeypatch):
    """La page etait trop peu structuree pour etre exploitable."""
    _repondeur(TABLE_ANCIENNE, monkeypatch)
    assert historique.compositions([pd.Timestamp("2005-01-01")]) == {}


def test_page_sans_revision(monkeypatch):
    monkeypatch.setattr(historique, "_demander",
                        lambda p, timeout=45: {"query": {"pages": {"1": {}}}})
    assert historique.composition_au("2013-01-01") == []


def test_table_sans_colonne_ticker(monkeypatch):
    _repondeur("<table><tr><th>Company</th></tr><tr><td>Apple</td></tr></table>",
               monkeypatch)
    assert historique.composition_au("2013-01-01") == []


def test_univers_elargi_cumule_les_periodes(monkeypatch, tmp_path):
    """L'univers de travail doit contenir les sortis ET les entres."""
    for jour, html in (("2013-01-01", TABLE_ANCIENNE),
                       ("2024-01-01", TABLE_RECENTE)):
        _repondeur(html, monkeypatch)
        historique.composition_au(jour)
    monkeypatch.setattr(historique, "_demander",
                        lambda *a, **k: pytest.fail("cache attendu"))
    elargi = historique.univers_elargi([pd.Timestamp("2013-01-01"),
                                        pd.Timestamp("2024-01-01")])
    assert {"AA", "NVDA"} <= set(elargi)
