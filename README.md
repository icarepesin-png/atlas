# ATLAS - Adaptive Trading & Learning Allocation System

Plateforme quantitative de gestion d'un portefeuille d'actions mondial.
Objectif: detecter et exploiter des avantages statistiques reproductibles,
pas predire les marches. Tout est backtestable, explicable et controlable.

## Capacites

1. Scan automatique de l'univers (S&P 500, Nasdaq 100, STOXX 600 echantillon, extensible)
2. Scoring fondamental (rentabilite, croissance, qualite F/Z/M, valorisation)
3. Analyse technique multi-setup (trend, breakout, pullback, VCP, stage analysis)
4. Regime macro (FRED: inflation, chomage, courbe des taux, M2)
5. Rotation sectorielle (momentum + force relative via ETFs proxys)
6. Score composite pondere (fondamental 35 / technique 25 / macro 15 / secteur 15 / sentiment 10)
7. Signaux d'entree avec stop ATR, trailing stop, 3 take-profits en multiples de R
8. Sizing par risque (0.75%/trade), Kelly bride, vol targeting
9. Construction de portefeuille: equal weight, inverse vol, vol targeting, HRP
10. Backtest avec couts (commission + slippage + spread), sans look-ahead
11. Validation: walk-forward, Monte Carlo (block bootstrap), stress tests 2000/2008/2020/2022
12. Risk management continu (drawdown, correlation, concentration) avec actions automatiques
13. Auto-amelioration: IC des facteurs, hit-rate par bucket de score, proposition de ponderations (validee par un humain)

## Demarrage rapide

```powershell
cd "C:\bot trading\atlas"
.\.venv\Scripts\Activate.ps1
pip install -e .
copy .env.example .env        # remplir FRED_API_KEY (gratuit) si souhaite

# 1. Scan quotidien (test rapide sur 100 titres; sans --limit: univers complet)
python -m atlas.pipelines.daily_scan --limit 100

# 2. Execution paper des signaux + gestion des stops
python -m atlas.pipelines.paper_trade

# 3. Scan + paper en un seul appel (utilise par la tache planifiee Windows
#    "ATLAS Daily Run", soirs de semaine 23h00; logs dans data/daily_run.log)
python -m atlas.pipelines.daily_run

# 4. Backtest avec validation complete
python -m atlas.pipelines.run_backtest --limit 100 --validate

# 5. Dashboard
streamlit run atlas/dashboard/app.py

# 6. API REST
uvicorn atlas.api.main:app --port 8000     # docs sur /docs

# 7. Tests
pytest
```

La tache planifiee se gere avec:

```powershell
Get-ScheduledTask "ATLAS Daily Run"          # etat
Start-ScheduledTask "ATLAS Daily Run"        # run manuel
Unregister-ScheduledTask "ATLAS Daily Run"   # suppression
```

## Structure

```
atlas/
  config/config.yaml      ponderations, seuils, univers (source de verite)
  atlas/
    config.py             chargement YAML + secrets .env
    universe/             constitution de l'univers + filtre liquidite
    data/                 providers (Yahoo MVP, interfaces Polygon/FMP), FRED, cache, store SQL
    features/             technique, fondamental (F/Z/M), momentum, regime macro, secteurs, sentiment
    scoring/              z-scores sectoriels-neutres, score composite
    signals/              regles d'entree/sortie, stops, take-profits
    portfolio/            construction (EW/IV/VT/HRP), sizing, risk management
    backtest/             moteur, metriques, walk-forward, Monte Carlo, stress tests
    execution/            broker abstrait, paper broker, stubs Alpaca/IBKR
    learning/             IC facteurs, calibration probas, proposition de poids
    api/                  FastAPI
    dashboard/            Streamlit
    pipelines/            daily_scan, paper_trade, daily_run, run_backtest,
                          sentiment_ghost (LLM local, poids nul), reconcile (broker vs base)
  db/schema.sql           schema PostgreSQL de production
  docs/                   architecture, backtest, deploiement, go-live, roadmap
  tests/                  pytest
```

## Limites assumees du MVP (lire avant toute conclusion)

- **Donnees**: Yahoo Finance. Suffisant pour ~1500 titres quotidiens. Les 10 000+
  actifs exigent Polygon/Databento (interfaces prevues dans `atlas/data/base.py`).
- **Biais du survivant**: l'univers utilise les constituants ACTUELS des indices.
  Les resultats de backtest sur les facteurs fondamentaux sont donc optimistes.
  Le backtest fourni n'utilise que des facteurs prix (point-in-time par nature).
  La table `index_membership_history` du schema attend un flux historique.
- **Fondamentaux**: snapshot courant, pas point-in-time. Pour un backtest
  fondamental honnete: FMP as-reported ou SEC EDGAR avec dates de publication.
- **Sentiment/NLP**: le pilier composite reste neutre (50/100). Un MODE
  FANTOME note les titres chaque nuit via Ollama (llama3.1:8b local, titres
  de presse Yahoo) dans la table sentiment_scores, a poids nul. Le pilier ne
  sera active qu'apres validation de son IC sur plusieurs mois.
- **Execution reelle**: verrouillee par `LIVE_TRADING_ACK`. Paper d'abord,
  procedure complete dans `docs/GO_LIVE.md`.

## Documentation

- [Architecture et flux de donnees](docs/ARCHITECTURE.md)
- [Methodologie de backtest et biais](docs/BACKTEST.md)
- [Deploiement cloud](docs/DEPLOYMENT.md)
- [Procedure paper -> demo -> reel](docs/GO_LIVE.md)
- [Plan d'amelioration sur 5 ans](docs/ROADMAP.md)

## Avertissement

Ce logiciel est un outil de recherche. Rien ici ne constitue un conseil en
investissement. Le passage en reel engage votre seule responsabilite et doit
suivre la procedure de validation documentee.
