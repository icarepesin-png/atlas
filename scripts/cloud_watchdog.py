# -*- coding: utf-8 -*-
"""Gardien cloud ATLAS - tourne sur GitHub Actions, INDEPENDANT du PC.

Role: surveiller le systeme depuis l'exterieur, car les alertes locales
(healthcheck) meurent avec le PC. Chaque jour il verifie:

1. FRAICHEUR DES DONNEES: la table paper_equity de Neon doit avoir une entree
   recente. Si plus de 2 jours ouvres manquent (tolerance pour les jours
   feries), c'est que le PC n'a pas fait tourner le run -> alerte Telegram.
2. SANTE DU DASHBOARD CLOUD: la page Streamlit doit repondre sans "Oh no".
   Si elle est plantee -> alerte + demande de redeploiement (commit vide
   pousse par le workflow, ce qui force Streamlit a reconstruire l'app).

Zero dependance au code atlas (script autonome): requests + psycopg2 suffisent.
Variables d'environnement requises (GitHub Secrets):
  ATLAS_CLOUD_DB, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

REGLE D'OR: un gardien muet est pire que pas de gardien. Ce script SORT EN
ERREUR (exit 1) des qu'il ne peut pas faire son travail (secret manquant,
Telegram injoignable). Le job GitHub passe alors au rouge et GitHub envoie
un mail au proprietaire du depot: c'est le canal de secours si Telegram est
casse. Il ne doit JAMAIS finir vert en ayant avale une alerte.

Usage:
  python scripts/cloud_watchdog.py            # surveillance normale
  python scripts/cloud_watchdog.py --test     # envoie un message de controle
"""

from __future__ import annotations

import os
import sys
from datetime import date, timedelta

import requests

APP_URL = "https://bfuunx3imesbnlybietd72.streamlit.app"
RULE = "━━━━━━━━━━━━━━━"
STALE_BUSINESS_DAYS = 2  # tolerance: 1 jour ouvre manque = possible ferie


def require_secrets() -> None:
    """Sort en erreur si un secret manque: sinon le gardien serait aveugle."""
    manquants = [nom for nom in ("ATLAS_CLOUD_DB", "TELEGRAM_BOT_TOKEN",
                                 "TELEGRAM_CHAT_ID")
                 if not os.environ.get(nom, "").strip()]
    if manquants:
        print("SECRETS MANQUANTS: " + ", ".join(manquants))
        print("Le gardien ne peut ni surveiller ni alerter. A ajouter dans")
        print("Settings > Secrets and variables > Actions du depot GitHub.")
        sys.exit(1)


def send_telegram(text: str) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chats = [c.strip() for c in os.environ.get("TELEGRAM_CHAT_ID", "").split(",")
             if c.strip()]
    if not token or not chats:
        print("telegram non configure")
        return False
    ok_all = True
    for chat in chats:
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat, "text": text, "parse_mode": "HTML",
                      "disable_web_page_preview": True}, timeout=20)
            ok_all &= (r.status_code == 200 and r.json().get("ok", False))
        except Exception as exc:
            print("envoi telegram echoue:", exc)
            ok_all = False
    return ok_all


def business_days_between(start: date, end: date) -> int:
    """Jours ouvres STRICTEMENT entre start et end (hors bornes)."""
    n, d = 0, start + timedelta(days=1)
    while d < end:
        if d.weekday() < 5:
            n += 1
        d += timedelta(days=1)
    return n


def check_data_freshness() -> tuple[bool, str]:
    import psycopg2

    url = os.environ.get("ATLAS_CLOUD_DB", "")
    if not url:
        return False, "ATLAS_CLOUD_DB manquante"
    try:
        conn = psycopg2.connect(url, connect_timeout=20)
        with conn, conn.cursor() as cur:
            cur.execute("SELECT MAX(date) FROM paper_equity")
            row = cur.fetchone()
        conn.close()
    except Exception as exc:
        return False, f"base Neon injoignable: {type(exc).__name__}: {exc}"
    if not row or not row[0]:
        return False, "aucune donnee paper_equity dans Neon"
    last = date.fromisoformat(str(row[0])[:10])
    missed = business_days_between(last, date.today())
    if missed >= STALE_BUSINESS_DAYS:
        return False, (f"dernier run: {last} ({missed} jours ouvres manques). "
                       "Le PC n'a probablement pas fait tourner ATLAS.")
    return True, f"donnees fraiches (dernier run: {last})"


def check_app_alive() -> tuple[bool, str]:
    try:
        r = requests.get(APP_URL, timeout=45)
        body = r.text.lower()
        if r.status_code != 200:
            return False, f"HTTP {r.status_code}"
        if "oh no" in body or "error running app" in body:
            return False, "page en erreur ('Oh no')"
        return True, "dashboard en ligne"
    except Exception as exc:
        return False, f"injoignable: {type(exc).__name__}"


def run_test() -> None:
    """Preuve de bout en bout: secrets lus, Neon interroge, Telegram recu."""
    fresh_ok, fresh_msg = check_data_freshness()
    app_ok, app_msg = check_app_alive()
    texte = (f"🛰️ <b>ATLAS · Test du gardien cloud</b>\n{RULE}\n"
             "Ce message prouve que le gardien peut vous joindre même PC "
             "éteint.\n\n"
             f"{'🟢' if fresh_ok else '🔴'} Données : {fresh_msg}\n"
             f"{'🟢' if app_ok else '🔴'} Dashboard : {app_msg}")
    if not send_telegram(texte):
        print("ECHEC: le message de test n'est pas parti")
        sys.exit(1)
    print("message de test envoye")


def main() -> None:
    require_secrets()

    if "--test" in sys.argv:
        run_test()
        return

    fresh_ok, fresh_msg = check_data_freshness()
    app_ok, app_msg = check_app_alive()
    print(f"donnees : {'OK' if fresh_ok else 'PROBLEME'} - {fresh_msg}")
    print(f"dashboard: {'OK' if app_ok else 'PROBLEME'} - {app_msg}")

    # Signale au workflow s'il faut redeployer l'app (commit vide)
    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out:
        with open(gh_out, "a", encoding="utf-8") as f:
            f.write(f"app_down={'true' if not app_ok else 'false'}\n")

    if fresh_ok and app_ok:
        # Battement de coeur du lundi: sans lui, le silence est ambigu
        # (gardien sain ou gardien mort? impossible a distinguer).
        if date.today().weekday() == 0:
            send_telegram(f"🛰️ <b>ATLAS · Gardien cloud</b>\n{RULE}\n"
                          "🟢 Tout est sain cette semaine.\n"
                          f"{fresh_msg}")
        print("tout est sain, aucune alerte")
        return

    lines = [f"🛰️ <b>ATLAS · Gardien cloud</b>\n{RULE}"]
    if not fresh_ok:
        lines.append(f"🔴 <b>Données en retard</b>\n{fresh_msg}\n"
                     "➡️ Allumez le PC : le rattrapage se lancera tout seul.")
    if not app_ok:
        lines.append(f"🟠 <b>Dashboard cloud en panne</b> ({app_msg})\n"
                     "➡️ Redéploiement automatique demandé.")
    if not send_telegram("\n\n".join(lines)):
        # Alerte detectee mais non delivree = panne du filet de securite.
        # Job rouge -> mail GitHub, seul canal restant.
        print("ECHEC CRITIQUE: alerte detectee mais Telegram injoignable")
        sys.exit(1)
    print("alerte envoyee")
    # Code de sortie 0: l'alerte est partie, le job a fait son travail
    sys.exit(0)


if __name__ == "__main__":
    main()
