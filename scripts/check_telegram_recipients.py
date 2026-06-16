"""Verifie que le bot Telegram peut ecrire a chaque destinataire configure."""

import requests

from atlas.config import get_settings


def main() -> None:
    s = get_settings()
    ids = [c.strip() for c in s.telegram_chat_id.split(",") if c.strip()]
    for cid in ids:
        r = requests.get(
            f"https://api.telegram.org/bot{s.telegram_bot_token}/getChat",
            params={"chat_id": cid}, timeout=15,
        ).json()
        if r.get("ok"):
            c = r["result"]
            nom = c.get("first_name") or c.get("title") or "?"
            print(f"OK  id={cid}  ->  {nom}  (le bot peut lui ecrire)")
        else:
            desc = r.get("description")
            print(f"PROBLEME id={cid}: {desc}")


if __name__ == "__main__":
    main()
