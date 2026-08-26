# -*- coding: utf-8 -*-
"""Calendrier multi-places et fraicheur du cache de cours.

Le test central est `test_cache_veille_est_perime`: il verrouille la
correction du bug qui faisait decider ATLAS sur les cours de la veille un
jour sur deux (equity gelee, trailing stops non releves).
"""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from atlas.data.markets import (MARKETS, easter_sunday, is_open,
                                last_expected_session, market_by_code,
                                market_of, next_open, session_state,
                                upcoming_holidays)
from atlas.data.store import is_cache_fresh

PARIS = ZoneInfo("Europe/Paris")
US = market_by_code("US")
PAR = market_by_code("PAR")
LSE = market_by_code("LSE")


def _cache(dernier_jour: date) -> pd.DataFrame:
    """Cache OHLCV dont la derniere barre est `dernier_jour`."""
    idx = pd.date_range(end=pd.Timestamp(dernier_jour), periods=5, freq="D")
    return pd.DataFrame({"close": [1.0] * 5}, index=idx)


# -- Paques et jours mobiles ---------------------------------------------------

@pytest.mark.parametrize("annee,attendu", [
    (2026, date(2026, 4, 5)),
    (2027, date(2027, 3, 28)),
])
def test_computus(annee, attendu):
    assert easter_sunday(annee) == attendu


def test_feries_us_coherents_avec_la_liste_verifiee_nyse():
    """Les regles doivent reproduire la liste NYSE verifiee a la main."""
    from atlas.data.calendar import US_MARKET_HOLIDAYS

    for annee in (2026, 2027):
        calcules = set(US.feries(annee))
        listes = {d for d in US_MARKET_HOLIDAYS if d.year == annee}
        assert listes <= calcules, f"feries NYSE perdus en {annee}"


# -- Rattachement des titres a leur place --------------------------------------

@pytest.mark.parametrize("ticker,code", [
    ("AAPL", "US"), ("MU", "US"), ("BRK-B", "US"),
    ("SHEL.L", "LSE"), ("TTE.PA", "PAR"), ("ASML.AS", "AMS"),
    ("BAS.DE", "XETRA"), ("NESN.SW", "SIX"), ("ENI.MI", "MIL"),
    ("ITX.MC", "BME"), ("NOVO-B.CO", "CPH"), ("7203.T", "TSE"),
])
def test_market_of(ticker, code):
    assert market_of(ticker).code == code


# -- Derniere seance close -----------------------------------------------------

def test_apres_cloture_us_la_seance_du_jour_compte():
    """Mardi 23h Paris = 17h New York: la seance du jour est close."""
    now = datetime(2026, 8, 25, 23, 0, tzinfo=PARIS)
    assert last_expected_session(US, now) == date(2026, 8, 25)


def test_avant_ouverture_us_on_reste_sur_la_veille():
    """Midi a Paris = 6h a New York: exiger la barre du jour serait absurde."""
    now = datetime(2026, 8, 25, 12, 0, tzinfo=PARIS)
    assert last_expected_session(US, now) == date(2026, 8, 24)


def test_week_end_recule_au_vendredi():
    now = datetime(2026, 8, 23, 20, 0, tzinfo=PARIS)  # dimanche
    assert last_expected_session(US, now) == date(2026, 8, 21)


def test_ferie_est_saute():
    """3 juillet 2026 (Independence Day observe, vendredi): on recule au 2."""
    now = datetime(2026, 7, 3, 23, 30, tzinfo=PARIS)
    assert last_expected_session(US, now) == date(2026, 7, 2)


def test_places_europeennes_closes_a_23h_paris():
    now = datetime(2026, 8, 25, 23, 0, tzinfo=PARIS)
    for code in ("PAR", "AMS", "XETRA", "SIX", "MIL", "BME", "LSE"):
        m = market_by_code(code)
        assert last_expected_session(m, now) == date(2026, 8, 25), code


# -- Fraicheur du cache: la regression a ne plus jamais reintroduire -----------

def test_cache_veille_est_perime():
    """LE bug: mardi 23h, un cache arrete a lundi n'est PAS frais."""
    now = datetime(2026, 8, 25, 23, 0, tzinfo=PARIS)
    assert not is_cache_fresh("AAPL", _cache(date(2026, 8, 24)), now)


def test_cache_du_jour_est_frais():
    now = datetime(2026, 8, 25, 23, 0, tzinfo=PARIS)
    assert is_cache_fresh("AAPL", _cache(date(2026, 8, 25)), now)


def test_cache_veille_frais_le_week_end():
    """Samedi, le cache de vendredi est le plus recent possible."""
    now = datetime(2026, 8, 22, 12, 0, tzinfo=PARIS)
    assert is_cache_fresh("AAPL", _cache(date(2026, 8, 21)), now)


def test_cache_vide_jamais_frais():
    assert not is_cache_fresh("AAPL", pd.DataFrame())


def test_fraicheur_tient_compte_de_la_place():
    """A 18h Paris, Paris a ferme mais New York cote encore."""
    now = datetime(2026, 8, 25, 18, 0, tzinfo=PARIS)
    veille = _cache(date(2026, 8, 24))
    assert is_cache_fresh("AAPL", veille, now)          # NY pas encore close
    assert not is_cache_fresh("TTE.PA", veille, now)    # Paris close a 17h30


# -- Etat de seance et affichage ----------------------------------------------

def test_session_state_us():
    zone = ZoneInfo("America/New_York")
    assert session_state(US, datetime(2026, 8, 25, 10, 0, tzinfo=zone)) == "ouvert"
    assert session_state(US, datetime(2026, 8, 25, 8, 0, tzinfo=zone)) == "avant"
    assert session_state(US, datetime(2026, 8, 25, 17, 0, tzinfo=zone)) == "apres"
    assert session_state(US, datetime(2026, 8, 22, 12, 0, tzinfo=zone)) == "week-end"
    assert session_state(US, datetime(2026, 7, 3, 12, 0, tzinfo=zone)) == "ferie"


def test_pause_dejeuner_tokyo():
    tse = market_by_code("TSE")
    zone = ZoneInfo("Asia/Tokyo")
    assert session_state(tse, datetime(2026, 8, 25, 12, 0, tzinfo=zone)) == "pause"
    assert session_state(tse, datetime(2026, 8, 25, 13, 0, tzinfo=zone)) == "ouvert"


def test_next_open_saute_le_week_end():
    now = datetime(2026, 8, 22, 12, 0, tzinfo=PARIS)  # samedi
    assert next_open(PAR, now).date() == date(2026, 8, 24)


def test_upcoming_holidays_trie_et_borne():
    items = upcoming_holidays(LSE, date(2026, 1, 1), n=3)
    assert len(items) == 3
    assert [d for d, _ in items] == sorted(d for d, _ in items)


def test_toutes_les_places_sont_coherentes():
    codes = [m.code for m in MARKETS]
    assert len(codes) == len(set(codes))
    for m in MARKETS:
        assert m.ouverture < m.fermeture, m.code
        assert is_open(m, datetime(2026, 8, 22, 12, 0, tzinfo=PARIS)) is False
