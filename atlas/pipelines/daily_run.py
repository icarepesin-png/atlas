"""Orchestration quotidienne: scan complet puis execution paper.

Run:  python -m atlas.pipelines.daily_run
Prevu pour le Planificateur de taches Windows / cron (soir apres cloture US).

Filets de securite:
- logs dans data/daily_run.log,
- etat du dernier run ecrit dans data/health.json (lu par le healthcheck
  du matin et par le bandeau du dashboard),
- sauvegarde quotidienne de la base dans data/backups/ (30 jours conserves).
"""

from __future__ import annotations

import json
import logging
import shutil
import traceback
from datetime import datetime, timezone

from atlas.config import PROJECT_ROOT

HEALTH_FILE = PROJECT_ROOT / "data" / "health.json"
BACKUP_DIR = PROJECT_ROOT / "data" / "backups"
BACKUP_KEEP = 30

log = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_health(payload: dict) -> None:
    HEALTH_FILE.parent.mkdir(parents=True, exist_ok=True)
    HEALTH_FILE.write_text(json.dumps(payload, indent=2, default=str),
                           encoding="utf-8")


def backup_db() -> None:
    """Copie datee de la base (elle contient le track record paper)."""
    db = PROJECT_ROOT / "atlas.db"
    if not db.exists():
        return
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    target = BACKUP_DIR / f"atlas_{datetime.now():%Y-%m-%d}.db"
    shutil.copy2(db, target)
    backups = sorted(BACKUP_DIR.glob("atlas_*.db"))
    for old in backups[:-BACKUP_KEEP]:
        old.unlink()
    log.info("sauvegarde base: %s (%d conservees)", target.name,
             min(len(backups), BACKUP_KEEP))


def main() -> None:
    log_dir = PROJECT_ROOT / "data"
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_dir / "daily_run.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
    health: dict = {"started": _now(), "status": "error", "error": None}
    exit_code = 0
    try:
        from atlas.pipelines import daily_scan, paper_trade

        scan = daily_scan.run()
        trade = paper_trade.run()
        health.update(status="ok", scan=scan, paper=trade)
        # Sentiment fantome: poids nul, best-effort, jamais bloquant
        try:
            from atlas.pipelines import sentiment_ghost
            health["sentiment_ghost"] = sentiment_ghost.run()
        except Exception as exc:
            log.warning("sentiment fantome echoue (non bloquant): %s", exc)
            health["sentiment_ghost"] = {"status": "error", "error": str(exc)}
        # Pousse les donnees vers le cloud pour le dashboard heberge (si configure)
        try:
            from atlas.pipelines import sync_to_cloud
            health["cloud_sync"] = sync_to_cloud.run()
        except Exception as exc:
            log.warning("synchro cloud echouee (non bloquant): %s", exc)
            health["cloud_sync"] = {"status": "error", "error": str(exc)}
        log.info("daily_run termine: scan=%s paper=%s", scan, trade)
        print({"scan": scan, "paper": trade})
    except Exception as exc:
        health["error"] = f"{type(exc).__name__}: {exc}"
        log.error("daily_run EN ECHEC:\n%s", traceback.format_exc())
        exit_code = 1
    finally:
        health["finished"] = _now()
        write_health(health)
        try:
            backup_db()
        except Exception as exc:
            log.warning("sauvegarde base echouee: %s", exc)
        try:
            from atlas.monitoring.notify import format_run_summary, send
            send(format_run_summary(health))
        except Exception as exc:
            log.warning("notification telegram echouee: %s", exc)
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
