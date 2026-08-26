# -*- coding: utf-8 -*-
"""Places de cotation: fuseau, horaires de seance, feries, derniere cloture.

Pourquoi ce module: ATLAS detient des titres sur 8 places dont les seances
n'ouvrent ni ne ferment aux memes heures. Deux besoins en decoulent:

1. FRAICHEUR DES DONNEES (critique). Savoir si le cache de cours est a jour
   ne peut pas se decider en "jours calendaires" - un cache d'un jour est
   frais un dimanche et perime un mardi soir. `last_expected_session` donne
   la derniere date dont la seance est CLOSE pour une place donnee: c'est la
   barre que le cache doit contenir, sinon il faut retelecharger.
2. AFFICHAGE. Statut de chaque marche dans le dashboard (ouvert, ferme,
   ferie, week-end) et prochaine ouverture.

FERIES: calcules par regles (Paques via computus, lundis mobiles anglais,
dates fixes) plutot que recopies a la main - une liste figee se perime et
personne ne s'en apercoit. Ces regles couvrent les fermetures ordinaires;
elles ne pretendent pas connaitre les fermetures exceptionnelles (deuil
national, panne). C'est pourquoi la fraicheur reelle est TOUJOURS recoupee
avec les donnees observees (`atlas.data.sessions`): si une place n'a pas
cote alors que le calendrier l'attendait, les donnees font foi.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo


# -- Paques et jours mobiles ---------------------------------------------------

@lru_cache(maxsize=64)
def easter_sunday(year: int) -> date:
    """Dimanche de Paques (computus gregorien, algorithme de Meeus/Jones)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    lm = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * lm) // 451
    month, day = divmod(h + lm - 7 * m + 114, 31)
    return date(year, month, day + 1)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """n-ieme `weekday` du mois (n=-1 pour le dernier)."""
    if n > 0:
        d = date(year, month, 1)
        shift = (weekday - d.weekday()) % 7
        return d + timedelta(days=shift + 7 * (n - 1))
    nxt = date(year + (month == 12), month % 12 + 1, 1)
    d = nxt - timedelta(days=1)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def _observed(d: date) -> date:
    """Ferie US tombant un week-end: observe le vendredi/lundi adjacent."""
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


# -- Jeux de feries par place --------------------------------------------------

def _holidays_us(y: int) -> dict[date, str]:
    e = easter_sunday(y)
    return {
        _observed(date(y, 1, 1)): "Jour de l'An",
        _nth_weekday(y, 1, 0, 3): "Martin Luther King Jr. Day",
        _nth_weekday(y, 2, 0, 3): "Presidents' Day",
        e - timedelta(days=2): "Vendredi saint",
        _nth_weekday(y, 5, 0, -1): "Memorial Day",
        _observed(date(y, 6, 19)): "Juneteenth",
        _observed(date(y, 7, 4)): "Independence Day",
        _nth_weekday(y, 9, 0, 1): "Labor Day",
        _nth_weekday(y, 11, 3, 4): "Thanksgiving",
        _observed(date(y, 12, 25)): "Noel",
    }


def _holidays_uk(y: int) -> dict[date, str]:
    e = easter_sunday(y)
    return {
        date(y, 1, 1): "Jour de l'An",
        e - timedelta(days=2): "Vendredi saint",
        e + timedelta(days=1): "Lundi de Paques",
        _nth_weekday(y, 5, 0, 1): "Early May Bank Holiday",
        _nth_weekday(y, 5, 0, -1): "Spring Bank Holiday",
        _nth_weekday(y, 8, 0, -1): "Summer Bank Holiday",
        date(y, 12, 25): "Noel",
        date(y, 12, 26): "Boxing Day",
    }


def _holidays_euronext(y: int) -> dict[date, str]:
    """Paris, Amsterdam, Bruxelles, Lisbonne: calendrier Euronext commun."""
    e = easter_sunday(y)
    return {
        date(y, 1, 1): "Jour de l'An",
        e - timedelta(days=2): "Vendredi saint",
        e + timedelta(days=1): "Lundi de Paques",
        date(y, 5, 1): "Fete du Travail",
        date(y, 12, 25): "Noel",
        date(y, 12, 26): "Lendemain de Noel",
    }


def _holidays_xetra(y: int) -> dict[date, str]:
    h = _holidays_euronext(y)
    h[date(y, 12, 24)] = "Reveillon de Noel"
    h[date(y, 12, 31)] = "Saint-Sylvestre"
    return h


def _holidays_six(y: int) -> dict[date, str]:
    e = easter_sunday(y)
    h = _holidays_euronext(y)
    h.update({
        date(y, 1, 2): "Berchtoldstag",
        e + timedelta(days=39): "Ascension",
        e + timedelta(days=50): "Lundi de Pentecote",
        date(y, 8, 1): "Fete nationale suisse",
        date(y, 12, 24): "Reveillon de Noel",
        date(y, 12, 31): "Saint-Sylvestre",
    })
    return h


def _holidays_milan(y: int) -> dict[date, str]:
    h = _holidays_euronext(y)
    h[date(y, 8, 15)] = "Assomption"
    h[date(y, 12, 24)] = "Reveillon de Noel"
    h[date(y, 12, 31)] = "Saint-Sylvestre"
    return h


def _holidays_madrid(y: int) -> dict[date, str]:
    """BME suit le calendrier Euronext. Verifie sur les cotations observees:
    Madrid COTE les 24 et 31 decembre (contrairement a Francfort ou Milan)
    et ferme bien le 26."""
    return _holidays_euronext(y)


def _holidays_copenhagen(y: int) -> dict[date, str]:
    e = easter_sunday(y)
    return {
        date(y, 1, 1): "Jour de l'An",
        e - timedelta(days=3): "Jeudi saint",
        e - timedelta(days=2): "Vendredi saint",
        e + timedelta(days=1): "Lundi de Paques",
        e + timedelta(days=39): "Ascension",
        # Vendredi suivant l'Ascension: pont observe sur les cotations 2026.
        e + timedelta(days=40): "Lendemain de l'Ascension",
        e + timedelta(days=50): "Lundi de Pentecote",
        date(y, 6, 5): "Constitution",
        date(y, 12, 24): "Reveillon de Noel",
        date(y, 12, 25): "Noel",
        date(y, 12, 26): "Lendemain de Noel",
        date(y, 12, 31): "Saint-Sylvestre",
    }


# -- Registre des places -------------------------------------------------------

@dataclass(frozen=True)
class Market:
    code: str
    nom: str
    tz: str
    ouverture: time
    fermeture: time
    devise: str
    suffixes: tuple[str, ...]
    drapeau: str
    _feries: object = field(repr=False, default=None)
    # Pause dejeuner (Tokyo, Hong Kong): (debut, fin) en heure locale
    pause: tuple[time, time] | None = None

    def zone(self) -> ZoneInfo:
        return ZoneInfo(self.tz)

    def feries(self, year: int) -> dict[date, str]:
        return self._feries(year) if self._feries else {}

    def ferie_le(self, d: date) -> str | None:
        return self.feries(d.year).get(d)


MARKETS: tuple[Market, ...] = (
    Market("US", "New York", "America/New_York", time(9, 30), time(16, 0),
           "USD", (), "US", _holidays_us),
    Market("LSE", "Londres", "Europe/London", time(8, 0), time(16, 30),
           "GBp", (".L",), "GB", _holidays_uk),
    Market("PAR", "Paris", "Europe/Paris", time(9, 0), time(17, 30),
           "EUR", (".PA",), "FR", _holidays_euronext),
    Market("AMS", "Amsterdam", "Europe/Amsterdam", time(9, 0), time(17, 30),
           "EUR", (".AS",), "NL", _holidays_euronext),
    Market("BRU", "Bruxelles", "Europe/Brussels", time(9, 0), time(17, 30),
           "EUR", (".BR",), "BE", _holidays_euronext),
    Market("LIS", "Lisbonne", "Europe/Lisbon", time(8, 0), time(16, 30),
           "EUR", (".LS",), "PT", _holidays_euronext),
    Market("XETRA", "Francfort", "Europe/Berlin", time(9, 0), time(17, 30),
           "EUR", (".DE", ".F"), "DE", _holidays_xetra),
    Market("SIX", "Zurich", "Europe/Zurich", time(9, 0), time(17, 30),
           "CHF", (".SW",), "CH", _holidays_six),
    Market("MIL", "Milan", "Europe/Rome", time(9, 0), time(17, 30),
           "EUR", (".MI",), "IT", _holidays_milan),
    Market("BME", "Madrid", "Europe/Madrid", time(9, 0), time(17, 30),
           "EUR", (".MC",), "ES", _holidays_madrid),
    Market("CPH", "Copenhague", "Europe/Copenhagen", time(9, 0), time(17, 0),
           "DKK", (".CO",), "DK", _holidays_copenhagen),
    Market("STO", "Stockholm", "Europe/Stockholm", time(9, 0), time(17, 30),
           "SEK", (".ST",), "SE", _holidays_euronext),
    Market("OSL", "Oslo", "Europe/Oslo", time(9, 0), time(16, 20),
           "NOK", (".OL",), "NO", _holidays_euronext),
    Market("TSE", "Tokyo", "Asia/Tokyo", time(9, 0), time(15, 0),
           "JPY", (".T",), "JP", None, (time(11, 30), time(12, 30))),
    Market("HKEX", "Hong Kong", "Asia/Hong_Kong", time(9, 30), time(16, 0),
           "HKD", (".HK",), "HK", None, (time(12, 0), time(13, 0))),
    Market("TSX", "Toronto", "America/Toronto", time(9, 30), time(16, 0),
           "CAD", (".TO", ".V"), "CA", None),
    Market("ASX", "Sydney", "Australia/Sydney", time(10, 0), time(16, 0),
           "AUD", (".AX",), "AU", None),
)

_US = MARKETS[0]


def market_of(ticker: str) -> Market:
    """Place de cotation deduite du suffixe. Sans suffixe connu: US."""
    for m in MARKETS:
        for suf in m.suffixes:
            if ticker.endswith(suf):
                return m
    return _US


def markets_of(tickers) -> dict[str, list[str]]:
    """Regroupe des tickers par code de place."""
    out: dict[str, list[str]] = {}
    for t in tickers:
        out.setdefault(market_of(t).code, []).append(t)
    return out


@lru_cache(maxsize=32)
def market_by_code(code: str) -> Market | None:
    return next((m for m in MARKETS if m.code == code), None)


# -- Etat d'une seance ---------------------------------------------------------

def is_session_day(m: Market, d: date) -> bool:
    """Jour de bourse ordinaire (ni week-end ni ferie connu)."""
    return d.weekday() < 5 and m.ferie_le(d) is None


def session_state(m: Market, now: datetime | None = None) -> str:
    """'ouvert' | 'pause' | 'avant' | 'apres' | 'ferie' | 'week-end'."""
    local = (now or datetime.now(m.zone())).astimezone(m.zone())
    d, t = local.date(), local.time()
    if d.weekday() >= 5:
        return "week-end"
    if m.ferie_le(d):
        return "ferie"
    if t < m.ouverture:
        return "avant"
    if t >= m.fermeture:
        return "apres"
    if m.pause and m.pause[0] <= t < m.pause[1]:
        return "pause"
    return "ouvert"


def is_open(m: Market, now: datetime | None = None) -> bool:
    return session_state(m, now) == "ouvert"


def last_expected_session(m: Market, now: datetime | None = None) -> date:
    """Derniere date dont la seance est CLOSE sur cette place.

    C'est la barre que le cache de cours doit contenir. Avant la cloture du
    jour, la reference reste la seance precedente: on ne peut pas exiger une
    barre qui n'existe pas encore.
    """
    local = (now or datetime.now(m.zone())).astimezone(m.zone())
    d = local.date()
    if not (is_session_day(m, d) and local.time() >= m.fermeture):
        d -= timedelta(days=1)
    while not is_session_day(m, d):
        d -= timedelta(days=1)
    return d


def next_open(m: Market, now: datetime | None = None) -> datetime:
    """Prochaine ouverture (heure locale de la place, tz-aware)."""
    local = (now or datetime.now(m.zone())).astimezone(m.zone())
    d = local.date()
    if not (is_session_day(m, d) and local.time() < m.ouverture):
        d += timedelta(days=1)
        while not is_session_day(m, d):
            d += timedelta(days=1)
    return datetime.combine(d, m.ouverture, tzinfo=m.zone())


def upcoming_holidays(m: Market, from_date: date | None = None,
                      n: int = 5) -> list[tuple[date, str]]:
    """Les n prochaines fermetures de cette place."""
    start = from_date or date.today()
    items: list[tuple[date, str]] = []
    for year in (start.year, start.year + 1):
        items += [(d, nom) for d, nom in m.feries(year).items() if d >= start]
    return sorted(items)[:n]
