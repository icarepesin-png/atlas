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
                                market_of, next_open, seance_attendue,
                                seance_de_reference, session_state,
                                upcoming_holidays)
from atlas.data.store import is_cache_fresh, sans_barre_incomplete

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


def test_fraicheur_alignee_sur_la_seance_de_reference():
    """A 18h Paris, Paris a ferme mais New York cote encore.

    Le run en cours traite la seance americaine de la VEILLE. La barre
    parisienne du jour lui est donc posterieure: l'exiger ferait noter un
    titre avec une cloture plus recente que son prix d'execution.
    """
    now = datetime(2026, 8, 25, 18, 0, tzinfo=PARIS)
    veille = _cache(date(2026, 8, 24))
    assert is_cache_fresh("AAPL", veille, now)
    assert is_cache_fresh("TTE.PA", veille, now)


def test_place_fermee_un_jour_ferie_local():
    """1er mai: Paris est fermee, New York cote. Paris reste a la veille."""
    now = datetime(2026, 5, 1, 23, 0, tzinfo=PARIS)
    assert seance_attendue("AAPL", now) == date(2026, 5, 1)
    assert seance_attendue("TTE.PA", now) == date(2026, 4, 30)


# -- Seance de reference: le resultat ne depend plus de l'heure du run ---------

@pytest.mark.parametrize("quand,attendue", [
    (datetime(2026, 8, 25, 23, 0, tzinfo=PARIS), date(2026, 8, 25)),   # soir
    (datetime(2026, 8, 26, 12, 0, tzinfo=PARIS), date(2026, 8, 25)),   # rattrapage midi
    (datetime(2026, 8, 26, 18, 0, tzinfo=PARIS), date(2026, 8, 25)),   # en seance
    (datetime(2026, 8, 29, 11, 0, tzinfo=PARIS), date(2026, 8, 28)),   # samedi
    (datetime(2026, 8, 31, 9, 0, tzinfo=PARIS), date(2026, 8, 28)),    # lundi matin
])
def test_seance_de_reference(quand, attendue):
    """Un rattrapage du mercredi midi traite la seance de mardi, pas 'mercredi':
    en datant par le calendrier, la campagne 2 a produit 6 points d'equity
    dates d'un week-end et 5 doublons."""
    assert seance_de_reference(quand) == attendue


# -- Barres incompletes: une cloture qui n'en est pas une ----------------------

def _barres(dernier_jour: date, n: int = 5) -> pd.DataFrame:
    idx = pd.bdate_range(end=pd.Timestamp(dernier_jour), periods=n)
    return pd.DataFrame({"close": range(n)}, index=idx)


def test_barre_du_jour_retiree_pendant_la_seance():
    """19h05 a Paris = 13h05 a New York: la barre du jour n'est qu'un cours
    en cours de route. FICO a ete vendu ainsi a 613,51 pour une cloture
    finale a 617,87."""
    now = datetime(2026, 9, 29, 19, 5, tzinfo=PARIS)
    propre = sans_barre_incomplete("FICO", _barres(date(2026, 9, 29)), now)
    assert propre.index.max().date() == date(2026, 9, 28)


def test_barre_du_jour_conservee_apres_la_cloture():
    now = datetime(2026, 9, 29, 23, 0, tzinfo=PARIS)
    propre = sans_barre_incomplete("FICO", _barres(date(2026, 9, 29)), now)
    assert propre.index.max().date() == date(2026, 9, 29)


def test_barre_europeenne_du_jour_retiree_tant_que_new_york_cote():
    now = datetime(2026, 9, 29, 18, 0, tzinfo=PARIS)
    propre = sans_barre_incomplete("TTE.PA", _barres(date(2026, 9, 29)), now)
    assert propre.index.max().date() == date(2026, 9, 28)


def test_cache_jamais_ecrit_avec_une_barre_partielle(tmp_path, monkeypatch):
    """Le poison durable: une barre partielle en cache passait ensuite pour
    fraiche (elle est datee du jour) et n'etait plus jamais retelechargee."""
    from atlas.data import store

    monkeypatch.setattr(store, "cache_path",
                        lambda t: str(tmp_path / f"{t}.parquet"))
    now = datetime(2026, 9, 29, 19, 5, tzinfo=PARIS)
    store.save_ohlcv("FICO", _barres(date(2026, 9, 29)), now)
    relu = store.load_ohlcv("FICO")
    assert relu.index.max().date() == date(2026, 9, 28)
    # ... et ce cache est juge frais pour le run en cours, perime le soir
    assert store.is_cache_fresh("FICO", relu, now)
    soir = datetime(2026, 9, 29, 23, 0, tzinfo=PARIS)
    assert not store.is_cache_fresh("FICO", relu, soir)


def test_table_vide_inchangee():
    assert sans_barre_incomplete("AAPL", pd.DataFrame()).empty


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
