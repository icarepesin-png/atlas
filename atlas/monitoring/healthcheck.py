"""Healthcheck du run nocturne. A planifier les matins de semaine.

Run:  python -m atlas.monitoring.healthcheck [--silent]

Verifie data/health.json :
- present,
- statut 'ok',
- date posterieure au dernier run attendu (dernier soir de semaine 23h00).

En cas d'anomalie: message d'alerte en console, popup Windows (sauf --silent),
code de sortie 1. Un systeme autonome qui echoue en silence est un systeme
qu'on croit vivant alors qu'il est mort: ce script est son pouls.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone

from atlas.pipelines.daily_run import HEALTH_FILE

RUN_HOUR = 23


def last_expected_run(now: datetime) -> datetime:
    """Dernier creneau de run revolu: soir de semaine a 23h00 (heure locale)."""
    candidate = now.replace(hour=RUN_HOUR, minute=0, second=0, microsecond=0)
    if now < candidate + timedelta(minutes=15):
        candidate -= timedelta(days=1)
    while candidate.weekday() >= 5:  # 5=samedi, 6=dimanche
        candidate -= timedelta(days=1)
    return candidate


def check(now: datetime | None = None) -> tuple[bool, str]:
    now = now or datetime.now()
    if not HEALTH_FILE.exists():
        return False, ("Aucun fichier health.json: le run quotidien n'a "
                       "jamais ecrit son etat.")
    try:
        health = json.loads(HEALTH_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return False, f"health.json illisible: {exc}"
    if health.get("status") != "ok":
        return False, (f"Le dernier run a ECHOUE: {health.get('error')}. "
                       "Voir data/daily_run.log.")
    finished = health.get("finished")
    if not finished:
        return False, "health.json sans horodatage de fin."
    finished_dt = datetime.fromisoformat(finished)
    if finished_dt.tzinfo is not None:
        finished_dt = finished_dt.astimezone().replace(tzinfo=None)
    expected = last_expected_run(now)
    if finished_dt < expected:
        return False, (f"Run manquant: dernier run termine le "
                       f"{finished_dt:%d/%m %H:%M}, un run etait attendu le "
                       f"{expected:%d/%m} a 23h00. Verifier la tache "
                       "'ATLAS Daily Run' et data/daily_run.log.")
    scan = health.get("scan", {})
    return True, (f"OK: run du {finished_dt:%d/%m %H:%M}, "
                  f"{scan.get('scored', '?')} titres scores, "
                  f"{scan.get('signals', '?')} signaux, "
                  f"regime {scan.get('regime', '?')}.")


def _popup(message: str) -> None:
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            0, message, "ATLAS - ALERTE RUN QUOTIDIEN", 0x10 | 0x1000)
    except Exception:
        pass  # session non interactive: l'alerte console et le code 1 restent


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--silent", action="store_true",
                        help="pas de popup Windows en cas d'echec")
    args = parser.parse_args()
    ok, message = check()
    print(("SAIN | " if ok else "ALERTE | ") + message)
    if not ok:
        try:
            import html as _html

            from atlas.monitoring.notify import RULE, send
            send(f"🔴 <b>ATLAS · Contrôle du matin</b>\n{RULE}\n"
                 f"{_html.escape(message)}")
        except Exception:
            pass
        if not args.silent:
            _popup(message)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
