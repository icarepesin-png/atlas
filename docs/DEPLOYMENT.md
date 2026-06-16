# Plan de deploiement cloud

## Etape 0 - Local (aujourd'hui)

Venv + SQLite + Parquet. Scan manuel ou via le Planificateur de taches Windows.
Suffisant pour la recherche et le paper trading.

## Etape 1 - VPS unique (paper trading 24/7)

Cible: VPS 2 vCPU / 8 Go (Hetzner, OVH, Lightsail), ~10-20 EUR/mois.

```bash
git clone <repo> && cd atlas
cp .env.example .env   # remplir les cles
docker compose up -d   # api + dashboard + scheduler + postgres + redis
```

- `docker-compose.yml` fournit les 5 services. Le scheduler lance le scan
  quotidien; le remplacer par un cron systemd si on veut un horaire precis:
  `30 22 * * 1-5 docker compose run --rm api python -m atlas.pipelines.daily_scan`
- Sauvegardes: `pg_dump` quotidien vers un stockage objet (S3/B2).
- Acces: dashboard derriere un reverse proxy (Caddy/Traefik) + auth basique.
  Ne JAMAIS exposer l'API sans authentification des que l'execution est active.

## Etape 2 - Production managee (demo puis reel)

| Composant | Service |
|-----------|---------|
| API + workers | ECS Fargate / Cloud Run (image Docker existante) |
| Orchestration | Prefect Cloud ou Airflow (MWAA) remplace le scheduler boucle |
| Base | RDS PostgreSQL / Cloud SQL, sauvegardes automatiques |
| Cache | ElastiCache Redis |
| Donnees froides | S3 + Parquet partitionne (annee/mois), Athena pour l'ad hoc |
| Secrets | AWS Secrets Manager / GCP Secret Manager (plus de .env) |
| Monitoring | Grafana + alerting (voir ci-dessous) |

## Monitoring minimal avant tout argent reel

- Heartbeat du scan quotidien (alerte si pas de scores a J).
- Alerte sur RiskAction != NONE (mail/Telegram).
- Alerte sur rejet d'ordre, divergence positions broker vs base locale.
- Journal d'audit: chaque ordre trace avec le signal et le score qui l'ont
  genere (deja en base via signal_id).

## Securite

- Cles broker en lecture seule tant que possible; cles de trading uniquement
  sur la machine d'execution.
- `LIVE_TRADING_ACK` reste un secret d'environnement, jamais en YAML/repo.
- Principe des 4 yeux pour toute modification de config.yaml en production
  (revue de PR obligatoire).
