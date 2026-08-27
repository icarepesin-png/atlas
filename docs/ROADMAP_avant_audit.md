# Plan d'amelioration sur 5 ans

## Annee 1 - Fiabiliser et valider

- T1: validation complete de la strategie momentum (walk-forward, MC, stress).
  FRED branche, scan quotidien automatise, paper trading lance.
- T2: fondamentaux point-in-time (FMP as-reported ou EDGAR + filing dates).
  Constituants historiques des indices (kill du biais du survivant).
  Premier backtest honnete du score composite complet.
- T3: connecteur Alpaca demo + reconciliation. Module sentiment v1
  (Ollama local + embeddings sur 10-K/10-Q, score 0-100 avec confiance).
- T4: passage reel progressif (10% du capital) si tous les criteres GO_LIVE
  sont verts. Univers etendu: STOXX 600 complet + FTSE 350.

## Annee 2 - Etendre l'univers et les donnees

- Polygon ou Databento: 10 000+ titres quotidiens, ingestion parallele.
- Migration PostgreSQL/TimescaleDB + Parquet partitionne S3.
- Russell 3000, Nikkei 225, ASX 200 (gestion devises: exposition FX mesuree,
  couverture optionnelle via futures/ETFs hedges).
- Moteur de revisions analystes + flux de capitaux sectoriels (payant).
- Orchestration Prefect/Airflow, monitoring Grafana complet.

## Annee 3 - Multi-strategies et regimes

- Poches independantes: trend equity (existante), mean reversion court terme,
  qualite long terme faible rotation; allocation entre poches par regime macro
  (la table factor_performance par regime existe deja pour ca).
- ETFs et REITs dans l'univers; obligations en poche defensive.
- Couverture systematique: regles de hedge (puts indiciels ou short futures)
  quand correlation moyenne et drawdown depassent les seuils simultanement.
- Walk-forward continu automatise (chaque trimestre, re-validation glissante).

## Annee 4 - ML disciplinee

- Remplacement progressif des ponderations lineaires par un modele
  (gradient boosting sur les facteurs, cible = rendement forward ajuste du
  risque), avec validation purged k-fold + embargo deja implementee.
- Meta-labeling: le ML ne choisit pas les titres, il filtre les signaux de la
  strategie de base (reduction du taux de faux positifs).
- NLP v2: surprise de tonalite entre deux publications consecutives,
  detection de changements strategiques.
- Execution: ordres adaptatifs (VWAP/TWAP sur la journee) si la taille du
  portefeuille commence a bouger les prix.

## Annee 5 - Autonomie controlee

- Boucle d'auto-amelioration entierement automatisee sous bornes dures
  (voir GO_LIVE.md, section auto-amelioration).
- Allocation multi-comptes / multi-devises.
- Matieres premieres et crypto en poches satellites (< 10% chacune),
  reutilisant les moteurs existants.
- Audit annuel externe du code de risque et des performances.

## Principe directeur

A chaque etape: une seule nouveaute majeure a la fois, validee par le meme
protocole (walk-forward + Monte Carlo + paper) avant de toucher au capital.
La complexite qui n'ameliore pas le Sharpe OOS est retiree.
