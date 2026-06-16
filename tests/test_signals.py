"""check_exits tests: trailing stop must anchor on the high SINCE entry.

Historical bug: the chandelier anchored on the pre-entry 22-day high, so a
pullback entry (bought well below its recent high) was sold instantly.
"""

import numpy as np
import pandas as pd
import pytest

from atlas.signals.generator import check_exits


@pytest.fixture
def pullback_ohlcv() -> pd.DataFrame:
    """Stock that peaked at 200 ten days ago, now trading flat around 160."""
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=60)
    close = np.full(60, 160.0)
    high = np.full(60, 162.0)
    low = np.full(60, 158.0)
    high[45:50] = 200.0  # pic AVANT l'entree
    close[45:50] = 195.0
    return pd.DataFrame({"open": close, "high": high, "low": low,
                         "close": close, "volume": np.full(60, 1e6)}, index=idx)


def _positions(opened_at: str) -> pd.DataFrame:
    return pd.DataFrame([{
        "ticker": "TEST", "qty": 10.0, "avg_price": 160.0,
        "opened_at": opened_at, "stop": 145.0, "trailing_stop": 145.0,
    }])


def test_no_instant_exit_on_pullback_entry(pullback_ohlcv):
    """Opened today: the pre-entry high at 200 must NOT drive the trailing."""
    today = pd.Timestamp.today().normalize().isoformat() + "+00:00"
    exits = check_exits(_positions(today), {"TEST": pullback_ohlcv})
    assert len(exits) == 1
    assert exits[0]["side"] == "update_stop"  # pas de vente


def test_exit_when_stop_hit(pullback_ohlcv):
    today = pd.Timestamp.today().normalize().isoformat() + "+00:00"
    pos = _positions(today)
    pos.loc[0, "stop"] = 170.0  # stop au-dessus du dernier cours (160)
    exits = check_exits(pos, {"TEST": pullback_ohlcv})
    assert exits[0]["side"] == "sell"
    assert exits[0]["reason"] == "stop/trailing"


def test_trailing_rises_with_post_entry_high(pullback_ohlcv):
    """Opened before the 200 peak: the trailing must use that high."""
    opened = pullback_ohlcv.index[40].isoformat() + "+00:00"
    exits = check_exits(_positions(opened), {"TEST": pullback_ohlcv})
    # plus-haut depuis l'entree = 200, ATR ~4 -> trailing ~188 > cours 160: vente
    assert exits[0]["side"] == "sell"
