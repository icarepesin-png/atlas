# -*- coding: utf-8 -*-
"""Prise partielle au premier objectif (TP1).

Contexte: tp1/tp2/tp3 etaient calcules, stockes et affiches depuis juin 2026
mais check_exits ne les regardait jamais. 13 trades sur 39 ont touche TP1
sans l'encaisser; la prise partielle d'un tiers valait +865 USD sur les
entrees reelles. Active le 2026-08-26 sur decision de l'utilisateur.
"""

import numpy as np
import pandas as pd
import pytest

from atlas.signals.generator import check_exits

ENTREE = 100.0
STOP = 90.0          # R = 10 -> TP1 (1.5R) = 115


def _serie(dernier_cours: float, n: int = 60) -> pd.DataFrame:
    """Serie plate au cours voulu, sans pic parasite avant l'entree."""
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
    close = np.full(n, dernier_cours)
    return pd.DataFrame({"open": close, "high": close * 1.005,
                         "low": close * 0.995, "close": close,
                         "volume": np.full(n, 1e6)}, index=idx)


def _position(qty=30.0, tp1_done=0) -> pd.DataFrame:
    hier = (pd.Timestamp.today().normalize() - pd.Timedelta(days=1))
    return pd.DataFrame([{
        "ticker": "TEST", "qty": qty, "avg_price": ENTREE,
        "opened_at": hier.isoformat() + "+00:00",
        "stop": STOP, "trailing_stop": STOP, "tp1_done": tp1_done,
    }])


def test_objectif_non_atteint_pas_de_vente():
    exits = check_exits(_position(), {"TEST": _serie(112.0)})
    assert exits[0]["side"] != "sell_partial"


def test_objectif_atteint_vend_un_tiers():
    exits = check_exits(_position(qty=30.0), {"TEST": _serie(116.0)})
    assert exits[0]["side"] == "sell_partial"
    assert exits[0]["qty"] == 10.0          # un tiers de 30
    assert "1.5R" in exits[0]["reason"]


def test_ne_reprend_pas_deux_fois():
    """Sans le drapeau tp1_done, on revendrait un tiers CHAQUE jour."""
    exits = check_exits(_position(tp1_done=1), {"TEST": _serie(116.0)})
    assert exits[0]["side"] != "sell_partial"


def test_ne_vide_jamais_la_position():
    """Une position d'un seul titre ne doit pas etre soldee par le TP."""
    exits = check_exits(_position(qty=1.0), {"TEST": _serie(116.0)})
    assert exits[0]["side"] != "sell_partial"


def test_stop_prioritaire_sur_objectif():
    """Cours sous le stop ET au-dessus de l'objectif est impossible, mais un
    cours effondre doit vendre TOUT, jamais un tiers."""
    exits = check_exits(_position(), {"TEST": _serie(80.0)})
    assert exits[0]["side"] == "sell"


@pytest.mark.parametrize("qty,attendu", [(3.0, 1.0), (30.0, 10.0), (99.0, 33.0)])
def test_taille_de_la_prise(qty, attendu):
    exits = check_exits(_position(qty=qty), {"TEST": _serie(116.0)})
    assert exits[0]["qty"] == attendu
