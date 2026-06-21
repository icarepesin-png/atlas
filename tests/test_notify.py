"""Telegram notifier tests: formatting and safe no-op when unconfigured."""

from types import SimpleNamespace

import atlas.monitoring.notify as notify


def test_send_noop_when_unconfigured(monkeypatch):
    """Sans token/chat_id: pas d'appel reseau, retour False, pas d'exception."""
    monkeypatch.setattr(
        notify, "get_settings",
        lambda: SimpleNamespace(telegram_bot_token="", telegram_chat_id=""))

    def boom(*a, **k):
        raise AssertionError("aucun appel reseau ne doit avoir lieu")

    monkeypatch.setattr(notify.requests, "post", boom)
    assert notify.send("test") is False


def test_format_run_summary_ok():
    health = {
        "status": "ok",
        "scan": {"as_of": "2026-06-11", "regime": "expansion",
                 "scored": 554, "signals": 7},
        "paper": {"buys": 1, "sells": 0, "pending": 6, "expired": 0,
                  "equity": 99984.12, "open_positions": 8,
                  "risk_actions": ["none: tous les seuils respectes"]},
    }
    msg = notify.format_run_summary(health)
    assert "2026-06-11" in msg
    assert "expansion" in msg
    assert "554 titres" in msg
    assert "7 signaux" in msg
    assert "Achats : 1" in msg
    # equity formatee: les chiffres '99984' apparaissent dans le message
    digits = "".join(c for c in msg if c.isdigit())
    assert "99984" in digits
    assert "ALERTE" not in msg


def test_format_run_summary_failure():
    health = {"status": "error", "error": "ValueError: boom"}
    msg = notify.format_run_summary(health)
    assert "ALERTE" in msg
    assert "ValueError: boom" in msg
    assert "daily_run.log" in msg


def test_fmt_money():
    # 103389 avec un separateur de milliers (espace, quel qu'en soit le type)
    r = notify.fmt_money(103389.46)
    assert "".join(c for c in r if c.isdigit()) == "103389"
    assert not r.isdigit()  # il y a bien un separateur
    assert notify.fmt_money("n/a") == "n/a"
