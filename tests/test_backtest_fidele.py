# -*- coding: utf-8 -*-
"""Backtest fidele: chaque regle du systeme reel, verifiee sur un cas d'ecole.

Si ce moteur s'ecarte de ce que fait paper_trade.py, ses resultats ne disent
plus rien de la strategie qui tourne - c'est exactement le defaut de l'ancien
backtest, qui simulait un portefeuille rebalance mensuellement sans stops.
"""

import numpy as np
import pandas as pd
import pytest

from atlas.backtest.fidele import Parametres, mesures, simuler
from atlas.backtest.pit_data import (Donnees, _matrice_escalier, rang,
                                     scores_familles)

GLISSE = 0.0005


def donnees(prix: dict[str, list[float]], atr: float = 2.0) -> Donnees:
    """Univers jouet: ouverture = cloture de la veille, haut = cloture."""
    tickers = sorted(prix)
    c = np.array([prix[t] for t in tickers], dtype=float).T
    o = np.vstack([c[:1], c[:-1]])
    cal = pd.bdate_range("2020-01-01", periods=len(c))
    return Donnees(cal=cal, tickers=tickers, ouverture=o, haut=c.copy(),
                   bas=c.copy(), cloture=c, atr=np.full_like(c, atr),
                   membre=np.ones_like(c, dtype=bool))


def partout(d: Donnees, valeur: float = 1.0) -> np.ndarray:
    return np.full(d.cloture.shape, valeur)


P = Parametres(selectivite=1.0)


# -- entree --------------------------------------------------------------------

def test_achat_a_l_ouverture_du_lendemain():
    """Signal a la cloture J, execution a l'ouverture J+1, glissement inclus."""
    d = donnees({"A": [100.0] * 6})
    r = simuler(d, partout(d), P)
    # 50 titres (plafond 5%) achetes 100 x 1.0005: seul le glissement coute
    assert r.equity.iloc[-1] == pytest.approx(100_000 - 50 * 100 * GLISSE)
    assert r.trades.empty


def test_taille_plafonnee_a_5_pourcent():
    """Stop proche (ATR 2 -> 4 de risque): la taille 'risque' serait de 125
    titres, le plafond de poids la ramene a 50."""
    d = donnees({"A": [100.0] * 6}, atr=2.0)
    r = simuler(d, partout(d), P)
    assert r.exposition.iloc[-1] == pytest.approx(0.05, abs=0.001)


def test_taille_par_le_risque_quand_le_stop_est_loin():
    """ATR 10 -> stop a 80: risquer 0,5% de 100 000 = 500 / 20 = 25 titres."""
    d = donnees({"A": [100.0] * 6}, atr=10.0)
    r = simuler(d, partout(d), P)
    assert r.exposition.iloc[-1] == pytest.approx(25 * 100 / 100_000, abs=0.001)


def test_titre_non_note_jamais_achete():
    d = donnees({"A": [100.0] * 6, "B": [50.0] * 6})
    score = partout(d)
    score[:, d.tickers.index("B")] = np.nan
    r = simuler(d, score, P)
    assert r.exposition.iloc[-1] == pytest.approx(0.05, abs=0.001)  # A seul


def test_positions_max_respecte():
    d = donnees({f"T{i}": [100.0] * 8 for i in range(6)})
    r = simuler(d, partout(d), Parametres(selectivite=1.0, positions_max=3))
    assert r.exposition.max() == pytest.approx(0.15, abs=0.002)


# -- sorties -------------------------------------------------------------------

def test_stop_initial_puis_carence():
    """Cloture sous le stop: vente totale, puis 20 jours sans rachat."""
    prix = [100.0] * 4 + [90.0] + [100.0] * 40
    d = donnees({"A": prix})
    r = simuler(d, partout(d), P)
    premier = r.trades.iloc[0]
    assert premier.raison == "stop initial"
    assert premier.prix_sortie == pytest.approx(90 * (1 - GLISSE))
    assert premier.pnl < 0
    # le rachat ne peut intervenir qu'apres la carence
    rachat = r.exposition[r.exposition.index > premier.sortie]
    premier_jour_investi = rachat[rachat > 0].index[0]
    assert (premier_jour_investi - premier.sortie).days >= 20


def test_sans_carence_le_rachat_est_immediat():
    prix = [100.0] * 4 + [90.0] + [100.0] * 10
    d = donnees({"A": prix})
    r = simuler(d, partout(d), Parametres(selectivite=1.0, carence_jours=0))
    sortie = r.trades.iloc[0].sortie
    apres = r.exposition[r.exposition.index > sortie]
    assert (apres[apres > 0].index[0] - sortie).days <= 4


def test_prise_partielle_une_seule_fois():
    """+1,5R atteint: un tiers est vendu, et un tiers seulement."""
    prix = [100.0] * 3 + [108.0] * 6
    d = donnees({"A": prix})
    r = simuler(d, partout(d), P)
    objectifs = r.trades[r.trades.raison == "objectif"]
    assert len(objectifs) == 1
    assert objectifs.iloc[0].qty == 17          # round(50 / 3)
    assert objectifs.iloc[0].pnl > 0


def test_stop_suiveur_encaisse_un_gain_sans_carence():
    """Le titre monte, le stop le suit, puis il redescend: sortie en gain."""
    prix = [100.0] * 3 + [108.0, 112.0, 112.0, 105.0] + [105.0] * 5
    d = donnees({"A": prix})
    r = simuler(d, partout(d), P)
    fin = r.trades[r.trades.raison == "stop suiveur"]
    assert len(fin) == 1 and fin.iloc[0].pnl > 0
    # une sortie gagnante n'interdit pas le rachat
    apres = r.exposition[r.exposition.index > fin.iloc[0].sortie]
    assert (apres > 0).any()


def test_sans_prise_partielle_si_desactivee():
    prix = [100.0] * 3 + [108.0] * 6
    d = donnees({"A": prix})
    r = simuler(d, partout(d), Parametres(selectivite=1.0, tp_r=None))
    assert r.trades.empty


def test_titre_radie_solde_au_dernier_cours():
    """Une societe rachetee ou en faillite disparait de la cote: la position
    doit etre soldee, pas rester valorisee indefiniment."""
    prix = [100.0] * 5 + [np.nan] * 5
    d = donnees({"A": prix, "B": [50.0] * 10})
    score = partout(d)
    score[:, d.tickers.index("B")] = np.nan
    r = simuler(d, score, P)
    assert list(r.trades.raison) == ["radiation"]
    assert r.trades.iloc[0].prix_sortie == pytest.approx(100 * (1 - GLISSE))
    assert r.exposition.iloc[-1] == 0


# -- integrite -----------------------------------------------------------------

def _marche_aleatoire(n_jours=260, n_titres=8, graine=3) -> Donnees:
    rng = np.random.default_rng(graine)
    pas = rng.normal(0.0004, 0.02, (n_jours, n_titres))
    c = 100 * np.exp(np.cumsum(pas, axis=0))
    return donnees({f"T{i}": list(c[:, i]) for i in range(n_titres)}, atr=3.0)


def test_aucun_regard_vers_l_avenir():
    """Tronquer les donnees ne doit rien changer au passe deja simule."""
    complet = _marche_aleatoire()
    score = np.random.default_rng(1).random(complet.cloture.shape)
    court = Donnees(cal=complet.cal[:180], tickers=complet.tickers,
                    ouverture=complet.ouverture[:180], haut=complet.haut[:180],
                    bas=complet.bas[:180], cloture=complet.cloture[:180],
                    atr=complet.atr[:180], membre=complet.membre[:180])
    p = Parametres(selectivite=0.5)
    a = simuler(complet, score, p).equity.iloc[:179]
    b = simuler(court, score[:180], p).equity.iloc[:179]
    pd.testing.assert_series_equal(a, b)


def test_le_cash_ne_passe_jamais_sous_zero():
    d = _marche_aleatoire(n_titres=40)
    r = simuler(d, np.random.default_rng(2).random(d.cloture.shape),
                Parametres(selectivite=1.0, positions_max=40))
    assert r.exposition.max() <= 1.0 + 1e-9
    assert (r.equity > 0).all()


def test_mesures_completes():
    d = _marche_aleatoire()
    m = mesures(simuler(d, np.random.default_rng(4).random(d.cloture.shape),
                        Parametres(selectivite=0.5)))
    for cle in ("cagr", "sharpe", "drawdown_max", "trades", "reussite",
                "profit_factor", "exposition_moyenne"):
        assert cle in m
    assert -1 <= m["drawdown_max"] <= 0


# -- donnees: comptes en escalier et classements --------------------------------

def test_escalier_respecte_les_dates_de_depot():
    cal = pd.bdate_range("2024-01-01", "2026-12-31")
    marches = [(pd.Timestamp("2024-03-01"), {"revenue": 100.0}),
               (pd.Timestamp("2025-03-03"), {"revenue": 130.0})]
    col = pd.Series(_matrice_escalier(marches, cal)["revenue"], index=cal)
    assert np.isnan(col["2024-02-29"])           # avant le premier depot
    assert np.isnan(col["2024-03-01"])           # le jour du depot: trop tot
    assert col["2024-03-04"] == 100.0            # exploitable le lendemain ouvre
    assert col["2025-03-03"] == 100.0            # l'exercice 2024 pas encore la
    assert col["2025-03-04"] == 130.0
    assert np.isnan(col["2026-12-31"])           # muet depuis plus de 18 mois


# -- divisions d'actions: le regard vers l'avenir a ne jamais reintroduire ------

def _divisions() -> pd.Series:
    """Nvidia: division par 4 en 2021, par 10 en 2024."""
    return pd.Series([4.0, 10.0], index=pd.DatetimeIndex(["2021-07-20",
                                                          "2024-06-10"]))


def test_facteur_divisions():
    from atlas.data.prix_reels import facteur_divisions

    f = facteur_divisions(_divisions(), ["2020-06-30", "2022-01-03",
                                         "2025-01-02"])
    assert list(f) == [40.0, 10.0, 1.0]
    assert list(facteur_divisions(pd.Series(dtype=float), ["2020-01-01"])) == [1.0]


def test_benefice_par_action_ramene_sur_la_base_du_cours():
    """Un BPA de 4,52 publie debut 2020 vaut 0,113 sur la base d'un cours
    ajuste de deux divisions ulterieures (x4 puis x10). Sans cette
    correction, Nvidia affichait 48% de rendement beneficiaire au lieu de
    1,2% et se classait en tete de la 'valeur' des annees avant sa hausse."""
    cal = pd.bdate_range("2020-01-01", "2020-12-31")
    marches = [(pd.Timestamp("2020-02-20"),
                {"eps_diluted": 4.52, "shares_diluted": 618.0,
                 "revenue": 10_918.0})]
    brut = _matrice_escalier(marches, cal)
    juste = _matrice_escalier(marches, cal, splits=_divisions())
    dernier = -1
    assert brut["eps_diluted"][dernier] == 4.52
    assert juste["eps_diluted"][dernier] == pytest.approx(4.52 / 40)
    assert juste["shares_diluted"][dernier] == pytest.approx(618.0 * 40)
    assert juste["revenue"][dernier] == 10_918.0   # un montant global ne bouge pas


def test_capitalisation_invariante_par_division():
    """Cours ajuste x actions ajustees = capitalisation reelle de l'epoque."""
    cal = pd.bdate_range("2020-06-01", "2020-06-30")
    marches = [(pd.Timestamp("2020-02-20"), {"shares_diluted": 618.0})]
    actions = _matrice_escalier(marches, cal, splits=_divisions())["shares_diluted"]
    cours_reel, cours_yahoo = 380.0, 380.0 / 40
    assert actions[-1] * cours_yahoo == pytest.approx(618.0 * cours_reel)


def test_rang_ignore_les_titres_hors_indice():
    mat = np.array([[1.0, 2.0, 3.0, 99.0]])
    masque = np.array([[True, True, True, False]])
    r = rang(mat, masque)
    assert np.isnan(r[0, 3])
    assert r[0, 2] == pytest.approx(1.0)


def test_score_de_famille_exige_plusieurs_facteurs():
    """Un titre note sur un seul ratio n'a pas de score de famille."""
    d = donnees({f"T{i}": [100.0] * 3 for i in range(5)})
    vide = np.full(d.cloture.shape, np.nan)
    d.comptes = {c: vide.copy() for c in (
        "revenue", "net_income", "assets", "equity", "gross_profit",
        "operating_income", "cash_from_ops", "capex", "eps_diluted",
        "shares_diluted", "liabilities", "long_term_debt", "revenue_prec",
        "eps_prec")}
    d.comptes["eps_diluted"] = np.tile([1.0, 2.0, 3.0, 4.0, 5.0], (3, 1))
    s = scores_familles(d)
    assert np.isnan(s["valeur"]).all()           # earnings_yield seul: insuffisant
    d.comptes["revenue"] = np.tile([10.0, 20.0, 30.0, 40.0, 50.0], (3, 1))
    d.comptes["shares_diluted"] = np.full(d.cloture.shape, 10.0)
    s = scores_familles(d)
    assert np.isfinite(s["valeur"]).all()        # deux ratios: note
    assert s["valeur"][0].argmax() == 4          # le moins cher est en tete
