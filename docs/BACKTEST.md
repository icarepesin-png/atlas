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

## Mesure du pilier fondamental point-in-time (2026-08-27)

Grace aux depots EDGAR (1 037 193 faits, 510 societes, 2006-2026), le pilier
fondamental a enfin pu etre mesure sans look-ahead: a chaque date, chaque titre
est note avec les comptes REELLEMENT publies ce jour-la.

Score fondamental agrege, 66 dates trimestrielles de 2010 a 2026:

| Horizon | IC moyen | Positif | t |
|---------|----------|---------|---|
| 21 seances | -0.003 | 44% du temps | -0.30 |
| 63 seances | +0.000 | 46% du temps | +0.03 |

Par facteur, seuls ceux de VALEUR sortent legerement du bruit et dans le bon
sens: fcf_yield (+0.014 / +0.021), pe (+0.019 / +0.015), ps (+0.009 / +0.042).
Les facteurs de QUALITE sont neutres ou negatifs: roe (-0.012 / +0.003),
marges operationnelles (-0.021 / -0.044).

### Le test temoin, et pourquoi il interdit de conclure

Avant d'en tirer que "le fondamental ne marche pas", on a mesure sur le MEME
univers deux facteurs dont l'effet est documente depuis des decennies:

| Facteur temoin | IC 21j | IC 63j | t (63j) |
|----------------|--------|--------|---------|
| Momentum 12-1 mois | -0.013 | +0.003 | +0.15 |
| Volatilite faible | -0.052 | -0.064 | **-1.96** |

Le momentum, effet le plus replique de la litterature academique, ressort NUL
lui aussi. Et la volatilite ressort franchement inversee: sur cet univers, plus
un titre est volatil, mieux il a performe.

Ce dernier point est la signature du BIAIS DU SURVIVANT. L'univers est
constitue des membres ACTUELS du S&P 500, c'est-a-dire des societes qui ont
reussi. Les titres volatils qui ont explose a la hausse y sont; ceux qui ont
coule en sont sortis et n'y figurent pas. Mecaniquement, "volatil = gagnant"
et les facteurs de qualite et de valeur perdent leur pouvoir, puisque les
pieges de valorisation qu'ils servaient a eviter ont disparu de l'echantillon.

CONCLUSION: ces mesures ne permettent PAS de conclure que le pilier fondamental
est sans valeur. Elles montrent qu'aucun facteur, pas meme les plus etablis,
n'est mesurable sur un univers biaise par le survivant. La correction de ce
biais (constituants historiques des indices, phase 2.2 de la feuille de route)
devient donc le prealable a toute conclusion, et non plus une amelioration
parmi d'autres.

Ce que la mesure etablit malgre le biais: le systeme n'a aucun avantage
DEMONTRE a ce jour, ni par le technique, ni par le fondamental.

## Correction du biais du survivant (2026-08-27, second temps)

L'univers a ete reconstitue trimestre par trimestre depuis les revisions de la
page Wikipedia "List of S&P 500 companies" (gratuit, `atlas/universe/
historique.py`). Resultat: **880 titres ont appartenu a l'indice entre 2010 et
2026, dont 376 absents de l'univers actuel** - 43%. Yahoo a rendu 138 de ces
376 series; les autres, surtout des societes rachetees ou renommees
(Activision, Alexion, Anthem), ne sont plus servies sous leur ancien symbole.
La correction est donc PARTIELLE: environ un tiers des disparus recuperes.

### Preuve que le biais fabriquait les resultats

Meme mesure, deux univers (`scripts/comparer_biais_survivant.py`):

| Facteur temoin | Univers biaise | Univers corrige |
|----------------|----------------|-----------------|
| Volatilite faible | -0.063 (t = **-1.94**) | -0.013 (t = -0.38) |
| Momentum 12-1 | +0.005 (t = +0.26) | -0.003 (t = -0.12) |

La "prime a la volatilite", qui n'a aucun sens economique, s'effondre des qu'on
rend a l'echantillon une partie de ses perdants. Le diagnostic est confirme:
c'etait l'echantillon qui mentait. Le momentum, lui, reste nul dans les deux
cas - la neutralisation du pilier technique reste donc justifiee.

### Le pilier fondamental, mesure proprement

| Facteur | Biaise (63j) | Corrige (63j) |
|---------|--------------|---------------|
| PER | +0.015 | **+0.025** |
| Price/Sales | +0.042 | +0.032 |
| Rendement du cash-flow libre | +0.021 | **+0.024** |
| ROE | +0.003 | **+0.018** |
| ROIC | +0.009 | **+0.021** |
| Croissance du chiffre d'affaires | -0.002 | -0.009 |
| Croissance du BPA | -0.006 | -0.011 |
| **Score agrege** | **+0.000** (t=+0.03) | **+0.013** (t=+0.87) |

Trois enseignements:

1. **La correction ameliore tout dans le bon sens.** Ce n'est pas un hasard de
   mesure: les facteurs redeviennent coherents avec la litterature.
2. **La VALEUR est la seule famille qui ressort** (PER, Price/Sales, cash-flow:
   +0.024 a +0.032, zone "faible mais exploitable"). La QUALITE est marginale
   (+0.01 a +0.02) et la CROISSANCE est negative.
3. **Le score agrege reste sans avantage demontre** (t = +0.87, tres loin du
   seuil de 2). Melanger valeur, qualite et croissance dans une seule note
   dilue le seul signal qui fonctionne.

Piste que ces chiffres designent: un score centre sur la VALEUR, plutot que le
melange actuel a poids egaux. A tester, pas a decreter.
