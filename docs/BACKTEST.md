# Methodologie de backtest

## Regles anti-biais

| Biais | Mesure prise | Statut MVP |
|-------|--------------|------------|
| Look-ahead | Decision a la cloture de t, execution a t+1. Le moteur ne passe a la strategie que `closes.loc[:t]`. Test automatise `test_no_lookahead`. | Elimine |
| Survivant | L'univers Yahoo = constituants actuels. Le backtest livre n'utilise QUE des facteurs prix. La table `index_membership_history` attend un flux de constituants historiques avant toute conclusion sur les facteurs fondamentaux. | Documente, partiellement elimine |
| Fondamentaux non point-in-time | Les fondamentaux Yahoo sont un snapshot. Ils sont EXCLUS du backtest. Production: FMP as-reported / EDGAR avec `filing_date`, requetes filtrees `filing_date <= date_simulation`. | Exclu du backtest |
| Data snooping / overfitting | Walk-forward obligatoire, Monte Carlo, stress tests, peu de parametres libres (top_n, lookback), pas d'optimisation fine. | Outils en place |
| Couts ignores | Commission 2bps + slippage 5bps + demi-spread 1.5bps sur chaque notionnel traite. | Inclus |

## Couts modelises

```
cout_par_rebalancement = equity * turnover * (commission + slippage + spread/2)
```

Valeurs par defaut (config.yaml): 2 + 5 + 1.5 = 8.5 bps par cote, calibrees
pour des large caps liquides via un broker retail. Pour des mid/small caps,
monter slippage a 10-20 bps. La latence n'est pas modelisee: la strategie est
quotidienne, l'execution a l'ouverture suivante absorbe ce point.

## Strategie de reference backtestable

`momentum_strategy` (backtest/engine.py): momentum 6 mois (en sautant le
dernier mois), filtre SMA200, ponderation inverse-volatilite, top 20,
rebalancement mensuel. C'est le PROXY prix du score composite: il valide la
poche technique/momentum sur 2000-aujourd'hui, crises comprises.

Le score composite complet (fondamental + secteur + macro) ne sera
backtestable honnetement qu'avec des fondamentaux point-in-time.

## Protocole de validation (obligatoire avant paper trading)

1. **Backtest complet** `python -m atlas.pipelines.run_backtest --validate`
2. **Walk-forward** (train 5 ans / test 1 an / pas 1 an):
   - Sharpe OOS moyen > 0.7
   - aucune fenetre OOS avec un Sharpe < -0.5
   - > 70% des fenetres profitables
3. **Monte Carlo** (1000 simulations, blocs de 21 jours):
   - P5 du multiple final > 1.0
   - P95 du max drawdown < limite config (15%)
4. **Stress tests**: drawdown contenu (< 1.5x le max drawdown du backtest
   complet) sur 2000-02, 2008, 2020, 2022.
5. **Stabilite des parametres**: faire varier top_n de +/- 50% et lookback de
   +/- 2 mois; le CAGR ne doit pas s'effondrer (sinon: overfit).

Les seuils ci-dessus sont les criteres de passage de la Phase 0 (recherche)
a la Phase 1 (paper trading), repris dans GO_LIVE.md.

## Ce que le backtest ne valide PAS (mesure du 2026-08-26)

Le proxy ci-dessus et le systeme qui tourne en paper sont **deux strategies
differentes**. Le proxy pondere les 20 meilleurs momentum et rebalance chaque
mois; le systeme live achete sur score composite >= 85, dimensionne par le
risque, et sort sur stop 2 ATR / trailing 2.75 ATR. Le moteur de backtest ne
connait ni stop, ni trailing, ni take-profit. Les 15% de CAGR et le Sharpe de
0.73 ne disent donc **rien** des regles reellement appliquees.

Mesures faites sur les donnees reellement produites depuis le 2026-06-11
(`scripts/pouvoir_predictif.py`, 16 250 observations, 46 dates):

| Pilier | IC 5j | IC 10j | IC 21j | Robustesse |
|--------|-------|--------|--------|------------|
| composite | -0.029 | -0.067 | -0.084 | negatif sur les 2 sous-periodes |
| fondamental | +0.054 | +0.082 | +0.094 | positif sur les 2 sous-periodes |
| technique | -0.105 | -0.214 | **-0.289** | negatif sur 30 dates / 30 |
| secteur | -0.086 | -0.090 | -0.014 | instable, change de signe |

Rendement moyen a 21 seances par tranche de score composite:

| Tranche | Observations | Rendement 21j |
|---------|--------------|---------------|
| 0-60 | 8 565 | +3.28% |
| 60-70 | 4 216 | +3.50% |
| 70-80 | 2 514 | +1.00% |
| 80-85 | 681 | +1.06% |
| **85-100 (seuil de signal)** | **274** | **-5.50%** |

La relation est monotone decroissante: **plus le score est haut, moins le
titre monte**. Le systeme achete donc, en moyenne, les titres qui baissent.

`scripts/simuler_regles_sortie.py` rejoue les 59 entrees reelles avec neuf
regles de sortie differentes: toutes perdent de l'argent. La meilleure (prise
partielle d'un tiers a 1.5R) ne recupere que 865 USD sur 2 506 de perte. Le
defaut n'est donc pas dans la sortie mais dans la SELECTION.

Limites de ces mesures, a garder en tete avant toute conclusion definitive:
2 mois et demi seulement, un seul regime de marche (SPY +3.75% sur la
periode), observations chevauchantes, et 274 points seulement au-dessus du
seuil 85. Un momentum puni pendant un trimestre n'est pas un momentum mort.
Ce qui est solide, c'est que le signal technique a ete negatif **chaque jour**
mesure: on ne peut pas continuer a l'acheter sans decision explicite.
