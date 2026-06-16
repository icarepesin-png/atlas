# Architecture ATLAS

## Vue d'ensemble

```mermaid
flowchart TB
    subgraph Sources
        Y[Yahoo Finance<br/>OHLCV + fondamentaux]
        P[Polygon / Databento<br/>extension 10k+ titres]
        F[FRED<br/>macro]
        E[SEC EDGAR / FMP<br/>fondamentaux point-in-time]
        N[News / Transcripts<br/>NLP futur]
    end

    subgraph Ingestion
        DP[data/ providers<br/>interface MarketDataProvider]
        CACHE[(Cache Parquet)]
    end

    subgraph Features
        TECH[features/technical<br/>EMA RSI MACD ATR ADX<br/>breakout pullback VCP stage]
        FUND[features/fundamental<br/>ROE ROIC marges croissance<br/>Piotroski Altman Beneish]
        MOM[features/momentum<br/>3/6/12m, 12-1, low vol, RS]
        MACRO[features/regime<br/>expansion / ralentissement /<br/>recession / reprise]
        SECT[features/sector<br/>rotation via ETFs]
        SENT[features/sentiment<br/>LLM local + RAG - interface]
    end

    subgraph Decision
        SCORE[scoring/composite<br/>35/25/15/15/10]
        SIG[signals/generator<br/>seuils 85/80/80/70 + liquidite]
        PORT[portfolio/construction<br/>EW IV VolTarget HRP]
        RISK[portfolio/risk<br/>drawdown correlation concentration]
    end

    subgraph Execution
        BT[backtest/engine<br/>couts, walk-forward, Monte Carlo]
        BROKER[execution/<br/>paper -> Alpaca -> IBKR]
    end

    subgraph Sorties
        DB[(SQLite / PostgreSQL)]
        API[FastAPI]
        DASH[Streamlit]
        LEARN[learning/feedback<br/>IC facteurs, hit rates,<br/>proposition de poids]
    end

    Y --> DP
    P -.futur.-> DP
    E -.futur.-> DP
    N -.futur.-> SENT
    F --> MACRO
    DP --> CACHE --> TECH & FUND & MOM
    DP --> SECT
    TECH & FUND & MOM & MACRO & SECT & SENT --> SCORE --> SIG --> PORT --> RISK
    PORT --> BT
    RISK --> BROKER
    SIG & SCORE & BROKER --> DB
    DB --> API & DASH & LEARN
    LEARN -.proposition validee par humain.-> SCORE
```

## Flux quotidien (pipeline daily_scan)

```mermaid
sequenceDiagram
    participant CRON as Scheduler (22h30 Paris)
    participant U as Universe
    participant D as Data providers
    participant FE as Features
    participant SC as Scoring
    participant SG as Signals
    participant RK as Risk
    participant EX as Broker
    participant DB as Store

    CRON->>U: build_universe()
    U->>D: OHLCV batch (cache-first)
    D->>FE: prix + fondamentaux + FRED + ETFs secteurs
    FE->>SC: piliers 0-100 par titre
    SC->>DB: save_scores(as_of)
    SC->>SG: composite > seuils ?
    SG->>DB: save_signals()
    SG->>RK: candidats + positions ouvertes
    RK->>EX: ordres (entrees sizees, sorties stop/trailing)
    EX->>DB: orders / positions / trades
    DB->>DB: learning: IC facteurs, hit rates
```

## Principes de conception

1. **Aucun vendor lock-in**: tout fournisseur de donnees implemente
   `MarketDataProvider` (data/base.py). Yahoo est le fallback gratuit;
   Polygon/Databento se branchent sans toucher au reste.
2. **Configuration = source de verite**: ponderations, seuils et contraintes
   vivent dans `config/config.yaml`. Le code ne contient aucun nombre magique
   de strategie. Le module learning PROPOSE des changements, un humain les
   applique (phases 1-2).
3. **Degradation gracieuse**: pas de cle FRED -> regime neutre (50). Pas de
   fondamentaux -> score neutre. Le pipeline ne casse jamais sur une donnee
   manquante; il degrade le score vers la neutralite.
4. **Separation decision / execution**: le moteur de scoring ne sait pas qui
   execute. Le broker ne sait pas pourquoi il achete. Le risk manager peut
   couper les deux.
5. **Garde-fous en dur**: tout broker non-paper exige `LIVE_TRADING_ACK` dans
   l'environnement. Les chemins critiques (sizing, stops) sont testes.

## Scalabilite (10 000+ actifs)

| Composant | MVP (aujourd'hui) | Production |
|-----------|-------------------|------------|
| Prix | Yahoo, ~1500 titres, sequentiel | Polygon flat files / Databento, ingestion parallele |
| Fondamentaux | Yahoo snapshot | FMP as-reported + EDGAR (point-in-time) |
| Stockage | SQLite + Parquet | PostgreSQL + Parquet partitionne (ou TimescaleDB) |
| Calcul features | boucle pandas | vectorisation wide-frame + Polars, workers paralleles |
| Orchestration | boucle docker / cron | Airflow ou Prefect, retries, SLA |
| Cache chaud | Parquet local | Redis (deja dans docker-compose) |

Le scoring cross-sectionnel est deja vectorise (DataFrame entier), seule la
collecte par ticker est sequentielle: c'est le point de parallelisation prevu.
