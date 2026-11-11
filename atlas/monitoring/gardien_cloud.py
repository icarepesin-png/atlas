# -*- coding: utf-8 -*-
"""Le PC surveille le gardien cloud: qui garde le gardien ?

Le workflow GitHub "ATLAS Watchdog" alerte quand le PC cesse de faire tourner
ATLAS. Mais personne ne verifiait que le gardien lui-meme tournait: le
2026-11-08, GitHub l'a desactive (regle des 60 jours sans activite sur le
depot) et il est reste eteint en silence. Le message "tout est sain" du lundi
n'est plus arrive, et l'absence d'un message ne se remarque pas.

D'ou cette surveillance croisee: a chaque run, le PC interroge l'API publique
de GitHub (sans identifiant, le depot est public) et signale dans le rapport
du soir un gardien desactive, en echec, ou muet depuis trop longtemps.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import requests

log = logging.getLogger(__name__)

DEPOT = "icarepesin-png/atlas"
API = f"https://api.github.com/repos/{DEPOT}/actions"
PAGE = f"https://github.com/{DEPOT}/actions/workflows/watchdog.yml"
ENTETES = {"User-Agent": "atlas-gardien", "Accept": "application/vnd.github+json"}
SILENCE_MAX_JOURS = 3       # le cron est quotidien; GitHub le retarde parfois


def etat(maintenant: datetime | None = None) -> dict:
    """Etat du gardien cloud.

    ok = True (sain), False (a reparer) ou None (impossible de savoir: pas de
    reseau, API indisponible). On n'alerte jamais sur un None: une panne de
    connexion du PC n'est pas une panne du gardien.
    """
    maintenant = maintenant or datetime.now(timezone.utc)
    try:
        wf = requests.get(f"{API}/workflows", headers=ENTETES, timeout=20)
        wf.raise_for_status()
        gardien = next((w for w in wf.json().get("workflows", [])
                        if str(w.get("path", "")).endswith("watchdog.yml")), None)
        if gardien is None:
            return {"ok": False, "raison": "workflow introuvable sur GitHub",
                    "page": PAGE}
        runs = requests.get(f"{API}/runs", headers=ENTETES, timeout=20,
                            params={"per_page": 1})
        runs.raise_for_status()
        dernier = (runs.json().get("workflow_runs") or [None])[0]
    except Exception as exc:  # noqa: BLE001
        log.info("etat du gardien cloud inconnu: %s", exc)
        return {"ok": None, "raison": f"verification impossible ({type(exc).__name__})"}

    statut = str(gardien.get("state", "?"))
    if statut != "active":
        motif = ("desactive par GitHub apres 60 jours sans activite sur le depot"
                 if statut == "disabled_inactivity" else f"etat {statut}")
        return {"ok": False, "raison": motif, "state": statut, "page": PAGE}
    if dernier is None:
        return {"ok": False, "raison": "aucune execution connue",
                "state": statut, "page": PAGE}

    quand = datetime.fromisoformat(dernier["created_at"].replace("Z", "+00:00"))
    age = (maintenant - quand).total_seconds() / 86400
    base = {"state": statut, "dernier_run": dernier["created_at"][:16],
            "page": PAGE}
    if age > SILENCE_MAX_JOURS:
        return {"ok": False, **base,
                "raison": f"aucune execution depuis {age:.0f} jours"}
    if dernier.get("conclusion") not in ("success", None):
        return {"ok": False, **base,
                "raison": f"derniere execution en echec ({dernier.get('conclusion')})"}
    return {"ok": True, "raison": "actif", **base}


if __name__ == "__main__":
    print(etat())
