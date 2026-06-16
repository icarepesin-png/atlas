"""Currency handling: detect listing currency from ticker suffix and convert
to USD via Yahoo FX pairs (cached like any other price series).

Yahoo quotes London (.L) prices in PENCE (GBp = GBP/100).
Degrades gracefully: unknown currency or failed FX fetch -> rate 1.0 + warning,
never a crash.
"""

from __future__ import annotations

import logging

import pandas as pd

log = logging.getLogger(__name__)

# Suffixe de place de cotation -> devise de cotation Yahoo
SUFFIX_CURRENCY = {
    ".L": "GBp",    # Londres, en pence
    ".PA": "EUR", ".AS": "EUR", ".DE": "EUR", ".MI": "EUR",
    ".MC": "EUR", ".BR": "EUR", ".LS": "EUR", ".HE": "EUR", ".VI": "EUR",
    ".SW": "CHF",
    ".CO": "DKK", ".ST": "SEK", ".OL": "NOK",
    ".T": "JPY",
    ".AX": "AUD",
    ".TO": "CAD",
    ".HK": "HKD",
}

# Paires Yahoo a telecharger (devise -> ticker du taux devise/USD)
FX_PAIRS = {
    "EUR": "EURUSD=X", "GBP": "GBPUSD=X", "CHF": "CHFUSD=X",
    "DKK": "DKKUSD=X", "SEK": "SEKUSD=X", "NOK": "NOKUSD=X",
    "JPY": "JPYUSD=X", "AUD": "AUDUSD=X", "CAD": "CADUSD=X",
    "HKD": "HKDUSD=X",
}


def currency_of(ticker: str) -> str:
    """Listing currency inferred from the ticker suffix. Default USD."""
    for suffix, cur in SUFFIX_CURRENCY.items():
        if ticker.endswith(suffix):
            return cur
    return "USD"


def get_usd_rates(provider=None) -> dict[str, float]:
    """Latest close of each FX pair, cache-first. Always contains USD=1.0
    and GBp (pence) derived from GBP."""
    rates: dict[str, float] = {"USD": 1.0}
    try:
        if provider is None:
            from atlas.data.yahoo import YahooProvider
            provider = YahooProvider()
        from atlas.data.store import get_ohlcv_batch_cached
        frames = get_ohlcv_batch_cached(list(FX_PAIRS.values()), provider,
                                        start=str(pd.Timestamp.today().date()
                                                  - pd.Timedelta(days=30)))
        for cur, pair in FX_PAIRS.items():
            df = frames.get(pair, pd.DataFrame())
            if not df.empty:
                rates[cur] = float(df["close"].iloc[-1])
    except Exception as exc:
        log.warning("recuperation FX echouee (%s): taux 1.0 par defaut", exc)
    if "GBP" in rates:
        rates["GBp"] = rates["GBP"] / 100.0
    return rates


def to_usd(amount: float, currency: str, rates: dict[str, float]) -> float:
    """Convert an amount in `currency` to USD. Unknown -> assume USD + warn."""
    if currency in rates:
        return amount * rates[currency]
    if currency not in ("USD", None, ""):
        log.warning("devise inconnue '%s': traitee comme USD", currency)
    return amount
