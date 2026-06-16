"""Macro data via FRED (Federal Reserve Economic Data). Free API key.

Returns each configured series as a pandas Series. Without an API key the
module degrades gracefully: empty data -> neutral macro regime downstream.
"""

from __future__ import annotations

import logging

import pandas as pd

from atlas.config import get_config, get_settings

log = logging.getLogger(__name__)


def fetch_macro_series() -> dict[str, pd.Series]:
    """Fetch all series declared in config.macro.fred_series."""
    settings = get_settings()
    series_map: dict[str, str] = get_config().macro.get("fred_series", {})
    if not settings.fred_api_key:
        log.warning("FRED_API_KEY absent: macro neutre (score 50).")
        return {}
    try:
        from fredapi import Fred
    except ImportError:
        log.warning("fredapi non installe: macro neutre.")
        return {}
    fred = Fred(api_key=settings.fred_api_key)
    out: dict[str, pd.Series] = {}
    for name, code in series_map.items():
        try:
            s = fred.get_series(code)
            s.index = pd.to_datetime(s.index)
            out[name] = s.dropna()
        except Exception as exc:
            log.warning("FRED %s (%s) failed: %s", name, code, exc)
    return out
