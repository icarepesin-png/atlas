"""Notifications Telegram via l'API Bot officielle.

Mise en place (une seule fois):
1. Recuperer le token du bot aupres de @BotFather dans Telegram
   (commande /mybots, choisir le bot, "API Token").
2. L'ecrire dans .env : TELEGRAM_BOT_TOKEN=123456:ABC-...
3. Dans Telegram, envoyer n'importe quel message au bot (ex: /start),
   sinon il n'a pas le droit de vous ecrire.
4. python -m atlas.monitoring.notify --setup   (decouvre le chat_id et
   l'enregistre dans .env)
5. python -m atlas.monitoring.notify --test    (message d'essai)

Tout envoi est best-effort: en cas d'echec (reseau, token invalide), un
warning est journalise et le programme appelant continue. Une notification
ne doit jamais faire echouer un run.
"""

from __future__ import annotations

import argparse
import logging
import sys

import requests

from atlas.config import PROJECT_ROOT, get_settings

log = logging.getLogger(__name__)

API = "https://api.telegram.org/bot{token}/{method}"
ENV_FILE = PROJECT_ROOT / ".env"


def is_configured() -> bool:
    s = get_settings()
    return bool(s.telegram_bot_token and s.telegram_chat_id)


def send(text: str) -> bool:
    """Envoie un message (HTML) a tous les destinataires configures
    (TELEGRAM_CHAT_ID accepte une liste separee par des virgules).
    Retourne False (sans lever) si non configure ou si un envoi echoue."""
    s = get_settings()
    chat_ids = [c.strip() for c in s.telegram_chat_id.split(",") if c.strip()]
    if not s.telegram_bot_token or not chat_ids:
        log.debug("telegram non configure, notification ignoree")
        return False
    all_ok = True
    for chat_id in chat_ids:
        try:
            resp = requests.post(
                API.format(token=s.telegram_bot_token, method="sendMessage"),
                json={"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                      "disable_web_page_preview": True},
                timeout=15,
            )
            ok = resp.status_code == 200 and resp.json().get("ok", False)
            if not ok:
                log.warning("envoi telegram refuse (%s): %s",
                            chat_id, resp.text[:200])
                all_ok = False
        except Exception as exc:
            log.warning("envoi telegram echoue (%s): %s", chat_id, exc)
            all_ok = False
    return all_ok


RULE = "━━━━━━━━━━━━━━━"


def fmt_money(v) -> str:
    """Montant lisible: 103389.46 -> '103 389'. Espaces insecables fines."""
    try:
        return f"{float(v):,.0f}".replace(",", " ")
    except (TypeError, ValueError):
        return str(v)


def format_run_summary(health: dict) -> str:
    """Message de synthese du run nocturne (HTML Telegram), a partir de
    health.json."""
    import html as _html

    if health.get("status") != "ok":
        err = _html.escape(str(health.get("error", "erreur inconnue")))
        return (
            "🔴 <b>ATLAS · ALERTE</b>\n"
            f"{RULE}\n"
            "Le run nocturne a <b>échoué</b>.\n\n"
            f"<code>{err}</code>\n\n"
            "<i>Détails : data/daily_run.log</i>"
        )
    scan = health.get("scan", {})
    paper = health.get("paper", {})
    risk = paper.get("risk_actions", [])
    real_risk = [r for r in risk if not str(r).startswith("none")]
    if real_risk:
        risk_line = "⚠️ " + " · ".join(_html.escape(r) for r in real_risk)
    else:
        risk_line = "✅ Tous les seuils respectés"

    eq = paper.get("equity")
    pnl = None
    try:
        pnl = float(eq) - 100_000
    except (TypeError, ValueError):
        pass
    pnl_line = ""
    if pnl is not None:
        arrow = "🟢" if pnl >= 0 else "🔴"
        pnl_line = f"   {arrow} {pnl:+,.0f}".replace(",", " ") + " depuis le départ\n"

    regime = str(scan.get("regime", "?"))
    regime_icon = {"expansion": "🌱", "recovery": "🌤️", "slowdown": "🌥️",
                   "recession": "🌧️", "neutral": "⚪"}.get(regime, "")

    return (
        f"🤖 <b>ATLAS · Rapport du {scan.get('as_of', '?')}</b>\n"
        f"{RULE}\n"
        f"{regime_icon} <b>Marché</b> · régime {regime}\n"
        f"   {scan.get('scored', '?')} titres analysés · "
        f"{scan.get('signals', '?')} signaux\n\n"
        f"💼 <b>Portefeuille</b>\n"
        f"   Equity : <b>{fmt_money(eq)} USD</b>\n"
        f"{pnl_line}"
        f"   Positions ouvertes : {paper.get('open_positions', '?')}\n\n"
        f"🔄 <b>Activité du jour</b>\n"
        f"   🟢 Achats : {paper.get('buys', 0)}   🔴 Ventes : {paper.get('sells', 0)}\n"
        f"   ⏳ En attente : {paper.get('pending', 0)}   ⌛ Expirés : {paper.get('expired', 0)}\n\n"
        f"🛡️ <b>Risque</b>\n"
        f"   {risk_line}"
    )


# -- mise en place ------------------------------------------------------------

def discover_chat_ids(token: str) -> list[str]:
    """Lit getUpdates et retourne les chat_id DISTINCTS de toutes les
    personnes ayant ecrit au bot. Chacune doit lui avoir envoye au moins
    un message (getUpdates ne retient que les messages recents)."""
    try:
        resp = requests.get(API.format(token=token, method="getUpdates"),
                            timeout=15)
        data = resp.json()
    except Exception as exc:
        print(f"echec getUpdates: {exc}")
        return []
    if not data.get("ok"):
        print(f"reponse API invalide: {data}")
        return []
    found: dict[str, str] = {}
    for update in data.get("result", []):
        chat = update.get("message", {}).get("chat")
        if chat:
            name = chat.get("first_name") or chat.get("title", "?")
            found[str(chat["id"])] = name
    if not found:
        print("Aucun message recu par le bot. Ouvrez Telegram, envoyez"
              " /start au bot, puis relancez --setup.")
        return []
    for cid, name in found.items():
        print(f"chat trouve: id={cid} ({name})")
    return list(found)


def _update_env(key: str, value: str) -> None:
    """Ajoute ou remplace une cle dans .env sans toucher au reste."""
    lines = []
    if ENV_FILE.exists():
        lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
    replaced = False
    for i, line in enumerate(lines):
        if line.split("=")[0].strip() == key:
            lines[i] = f"{key}={value}"
            replaced = True
            break
    if not replaced:
        lines.append(f"{key}={value}")
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{key} enregistre dans .env")


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--setup", action="store_true",
                        help="decouvre le chat_id et l'ecrit dans .env")
    parser.add_argument("--test", action="store_true",
                        help="envoie un message d'essai")
    args = parser.parse_args()

    if args.setup:
        settings = get_settings()
        token = settings.telegram_bot_token
        if not token:
            print("TELEGRAM_BOT_TOKEN absent de .env. L'ajouter d'abord.")
            sys.exit(1)
        discovered = discover_chat_ids(token)
        if not discovered:
            sys.exit(1)
        # Union avec les destinataires deja enregistres (getUpdates ne
        # retient que les messages recents, on ne perd personne).
        existing = [c.strip() for c in settings.telegram_chat_id.split(",")
                    if c.strip()]
        merged = existing + [c for c in discovered if c not in existing]
        _update_env("TELEGRAM_CHAT_ID", ",".join(merged))
        print(f"{len(merged)} destinataire(s) configure(s)")
        get_settings.cache_clear()

    if args.test:
        get_settings.cache_clear()
        ok = send("ATLAS: notifications Telegram operationnelles. "
                  "Vous recevrez la synthese de chaque run nocturne ici.")
        print("message envoye" if ok else "echec de l'envoi (voir logs)")
        sys.exit(0 if ok else 1)

    if not (args.setup or args.test):
        parser.print_help()


if __name__ == "__main__":
    main()
