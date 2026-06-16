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
