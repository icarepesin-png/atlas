# -*- coding: utf-8 -*-
"""Verrou d'execution: un seul run ATLAS a la fois sur la machine.

Pourquoi: le 2026-08-08, DEUX rattrapages ont demarre a la meme seconde a
l'ouverture de session (la tache "ATLAS Catchup" a un declencheur de session
ET scripts/startup.ps1 en lance un autre). Les deux processus ont lu les
memes signaux 'pending' avant que l'un ait pu les marquer executes, et ont
achete chacun de leur cote: GEN et FTNT se sont retrouves au DOUBLE de la
taille voulue (10% du portefeuille pour un plafond de 5%).

L'idempotence ("ne rien faire si le run du jour a deja reussi") ne protege
pas de ce cas: les deux processus constatent en meme temps qu'il n'y a rien
de fait. Seule l'exclusion mutuelle le fait.

Verrou par fichier cree en O_EXCL (atomique sous Windows comme sous Unix).
Un verrou dont le processus est mort ou qui depasse `perime_apres` est
considere abandonne et repris, pour qu'un plantage ne bloque pas le systeme.
"""

from __future__ import annotations

import logging
import os
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

from atlas.config import get_config

log = logging.getLogger(__name__)

PERIME_APRES = timedelta(hours=2)  # un run complet dure ~10 min


class DejaEnCours(RuntimeError):
    """Un autre run detient le verrou."""


def _chemin(nom: str) -> Path:
    dossier = Path(get_config().cache_dir).parent / "locks"
    dossier.mkdir(parents=True, exist_ok=True)
    return dossier / f"{nom}.lock"


def _processus_vivant(pid: int) -> bool:
    """Le PID tourne-t-il encore ? En cas de doute, on repond oui.

    Sous Windows, os.kill(pid, 0) NE distingue PAS un PID mort (il leve un
    OSError generique), ce qui ferait passer tout verrou orphelin pour vivant
    et bloquerait ATLAS jusqu'a expiration. On interroge donc directement
    l'API Win32.
    """
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        ERROR_INVALID_PARAMETER = 87      # PID inexistant
        k32 = ctypes.windll.kernel32
        handle = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            code = k32.GetLastError()
            if code == ERROR_INVALID_PARAMETER:
                return False
            # ERROR_ACCESS_DENIED ou autre: le processus existe probablement.
            # Dans le doute on garde le verrou (l'expiration le liberera).
            return True
        try:
            STILL_ACTIVE = 259
            sortie = ctypes.c_ulong()
            if k32.GetExitCodeProcess(handle, ctypes.byref(sortie)):
                return sortie.value == STILL_ACTIVE
            return True
        finally:
            k32.CloseHandle(handle)
    try:
        os.kill(pid, 0)          # signal 0: test d'existence, n'envoie rien
    except ProcessLookupError:
        return False
    except PermissionError:
        return True              # existe mais appartient a un autre compte
    except OSError:
        return True
    return True


def _abandonne(f: Path, perime_apres: timedelta) -> bool:
    """Verrou laisse par un processus mort ou trop ancien ?"""
    try:
        contenu = f.read_text(encoding="utf-8").split(maxsplit=1)
        pid = int(contenu[0])
        depuis = datetime.fromisoformat(contenu[1].strip())
    except Exception:
        return True              # illisible: on le considere abandonne
    if datetime.now() - depuis > perime_apres:
        log.warning("verrou %s perime (depuis %s), reprise", f.name, depuis)
        return True
    if not _processus_vivant(pid):
        log.warning("verrou %s laisse par le PID mort %d, reprise", f.name, pid)
        return True
    return False


@contextmanager
def run_lock(nom: str = "atlas-run", attente: float = 0.0,
             perime_apres: timedelta = PERIME_APRES):
    """Exclusion mutuelle entre runs ATLAS.

    attente: secondes d'attente avant d'abandonner (0 = echec immediat).
    Leve DejaEnCours si un autre run tient le verrou.
    """
    f = _chemin(nom)
    limite = time.monotonic() + attente
    while True:
        try:
            fd = os.open(f, os.O_CREAT | os.O_EXCL | os.O_RDWR)
            os.write(fd, f"{os.getpid()} {datetime.now().isoformat()}"
                     .encode("utf-8"))
            os.close(fd)
            break
        except FileExistsError:
            if _abandonne(f, perime_apres):
                f.unlink(missing_ok=True)
                continue
            if time.monotonic() >= limite:
                raise DejaEnCours(
                    f"un autre run ATLAS est deja en cours (verrou {f})")
            time.sleep(0.5)
    try:
        yield
    finally:
        f.unlink(missing_ok=True)
