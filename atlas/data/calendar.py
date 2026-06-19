"""Jours feries de la bourse americaine (NYSE / Nasdaq).

Liste statique 2026-2027 (a prolonger chaque annee). Sert a AFFICHER les
prochaines fermetures dans le dashboard. La detection du jour courant se fait
en plus par la fraicheur des donnees de marche (independante de cette liste),
donc meme un ferie non liste serait detecte comme "marche ferme".

Dates verifiees sur le calendrier officiel NYSE. Quand un ferie tombe un
samedi, il est observe le vendredi precedent; un dimanche, le lundi suivant.
"""

from __future__ import annotations

from datetime import date

US_MARKET_HOLIDAYS: dict[date, str] = {
    # 2026
    date(2026, 1, 1): "Jour de l'An",
    date(2026, 1, 19): "Martin Luther King Jr. Day",
    date(2026, 2, 16): "Presidents' Day",
    date(2026, 4, 3): "Vendredi saint",
    date(2026, 5, 25): "Memorial Day",
    date(2026, 6, 19): "Juneteenth",
    date(2026, 7, 3): "Independence Day (observe)",
    date(2026, 9, 7): "Labor Day",
    date(2026, 11, 26): "Thanksgiving",
    date(2026, 12, 25): "Noel",
    # 2027
    date(2027, 1, 1): "Jour de l'An",
    date(2027, 1, 18): "Martin Luther King Jr. Day",
    date(2027, 2, 15): "Presidents' Day",
    date(2027, 3, 26): "Vendredi saint",
    date(2027, 5, 31): "Memorial Day",
    date(2027, 6, 18): "Juneteenth (observe)",
    date(2027, 7, 5): "Independence Day (observe)",
    date(2027, 9, 6): "Labor Day",
    date(2027, 11, 25): "Thanksgiving",
    date(2027, 12, 24): "Noel (observe)",
}


def is_market_holiday(d: date) -> str | None:
    """Nom du jour ferie si d est ferie boursier US, sinon None."""
    return US_MARKET_HOLIDAYS.get(d)


def upcoming_holidays(from_date: date, n: int = 6) -> list[tuple[date, str]]:
    """Les n prochains jours feries a partir de from_date (inclus)."""
    items = sorted((d, name) for d, name in US_MARKET_HOLIDAYS.items()
                   if d >= from_date)
    return items[:n]
