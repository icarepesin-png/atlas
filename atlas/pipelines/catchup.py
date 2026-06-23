"""Rattrapage du run quotidien au demarrage de session.

Probleme couvert: le PC etait eteint ou en veille (reveil auto defaillant) a
23h, le run de la veille a ete manque, et donc aucune notification. Cette tache
s'execute a l'ouverture de session: si le dernier run reussi est anterieur a la
derniere echeance attendue (soir de semaine 23h), elle relance le run complet.

Idempotent: si le run du jour a deja reussi, elle ne fait rien (pas de double
notification).

Run:  python -m atlas.pipelines.catchup
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

from atlas.monitoring.healthcheck import HEALTH_FILE, last_expected_run

log = logging.getLogger(__name__)


def is_overdue(now: datetime | None = None) -> bool:
    now = now or datetime.now()
    if not HEALTH_FILE.exists():
        return True
    try:
        health = json.loads(HEALTH_FILE.read_text(encoding="utf-8"))
    except Exception:
        return True
    if health.get("status") != "ok":
        return True
    finished = health.get("finished")
    if not finished:
        return True
    dt = datetime.fromisoformat(finished)
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt < last_expected_run(now)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if is_overdue():
        log.info("run quotidien en retard: rattrapage en cours...")
        from atlas.pipelines import daily_run
        try:
            daily_run.main()
        except SystemExit:
            pass
    else:
        log.info("run quotidien a jour, aucun rattrapage necessaire.")


if __name__ == "__main__":
    main()
