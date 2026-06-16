"""Currency detection and USD conversion tests."""

import pytest

from atlas.data.fx import currency_of, to_usd

RATES = {"USD": 1.0, "EUR": 1.08, "GBP": 1.27, "GBp": 0.0127, "CHF": 1.11}


def test_currency_detection():
    assert currency_of("AAPL") == "USD"
    assert currency_of("MC.PA") == "EUR"
    assert currency_of("SAP.DE") == "EUR"
    assert currency_of("SHEL.L") == "GBp"      # Londres cote en pence
    assert currency_of("NESN.SW") == "CHF"
    assert currency_of("NOVO-B.CO") == "DKK"


def test_to_usd():
    assert to_usd(100.0, "USD", RATES) == 100.0
    assert to_usd(100.0, "EUR", RATES) == pytest.approx(108.0)
    # 400 pence = 4 GBP = 5.08 USD : sans conversion l'erreur serait x100
    assert to_usd(400.0, "GBp", RATES) == pytest.approx(5.08)


def test_unknown_currency_passthrough():
    assert to_usd(50.0, "XYZ", RATES) == 50.0
