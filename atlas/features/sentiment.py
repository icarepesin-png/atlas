"""Sentiment / NLP scoring.

Deux fournisseurs:
- NeutralSentiment (defaut): score 50, le pilier est inactif et son poids est
  redistribue dans le composite.
- OllamaNewsSentiment (mode fantome): un LLM local (Ollama) lit les titres de
  presse recents d'une valeur et rend un score 0-100 + confiance + risques.
  Utilise par pipelines/sentiment_ghost.py qui JOURNALISE les scores a poids
  nul. Le pilier ne recevra son poids reel qu'apres validation de son pouvoir
  predictif (IC mesure sur plusieurs mois), conformement a docs/ROADMAP.md.

L'API Ollama est locale (http://localhost:11434), aucun document ne quitte
la machine.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Protocol

log = logging.getLogger(__name__)

OLLAMA_URL = "http://localhost:11434"


@dataclass
class SentimentResult:
    score: float = 50.0          # 0-100
    confidence: str = "none"     # none | low | medium | high
    risks: list[str] = field(default_factory=list)
    opportunities: list[str] = field(default_factory=list)
    n_headlines: int = 0


class SentimentProvider(Protocol):
    name: str

    def score_ticker(self, ticker: str) -> SentimentResult: ...


class NeutralSentiment:
    """Default no-op provider: contributes nothing for or against any stock."""

    name = "neutral"

    def score_ticker(self, ticker: str) -> SentimentResult:
        return SentimentResult()


# -- Ollama news sentiment (mode fantome) --------------------------------------

_PROMPT = """Tu es un analyste financier buy-side rigoureux. Voici des titres
de presse recents concernant l'action {ticker} :

{headlines}

Evalue la tonalite globale de ces nouvelles POUR UN ACTIONNAIRE de {ticker}.
Reponds UNIQUEMENT avec un objet JSON, sans aucun autre texte :
{{"score": <entier 0-100, 50 = neutre, 100 = tres positif>,
 "confidence": <"low" si les titres sont vagues ou peu nombreux, "medium",
 "high" si les nouvelles sont claires et concordantes>,
 "risks": [<0 a 3 risques concrets evoques, en francais, courts>],
 "opportunities": [<0 a 3 opportunites concretes, en francais, courtes>]}}"""


def fetch_headlines(ticker: str, max_items: int = 10) -> list[str]:
    """Recent news titles via yfinance. Defensive: structure has changed
    across yfinance versions."""
    try:
        import yfinance as yf
        items = yf.Ticker(ticker).news or []
    except Exception as exc:
        log.debug("news indisponibles pour %s: %s", ticker, exc)
        return []
    titles = []
    for item in items[:max_items]:
        title = item.get("title")
        if not title and isinstance(item.get("content"), dict):
            title = item["content"].get("title")
        if title:
            titles.append(str(title).strip())
    return titles


class OllamaNewsSentiment:
    """Score 0-100 a partir des titres de presse, via un LLM local Ollama."""

    name = "ollama_news"

    def __init__(self, model: str = "llama3.1:8b", url: str = OLLAMA_URL,
                 timeout_s: int = 120) -> None:
        self.model = model
        self.url = url
        self.timeout_s = timeout_s

    def is_available(self) -> bool:
        import requests
        try:
            resp = requests.get(f"{self.url}/api/tags", timeout=5)
            if resp.status_code != 200:
                return False
            models = [m.get("name", "") for m in resp.json().get("models", [])]
            return any(m.startswith(self.model.split(":")[0]) for m in models)
        except Exception:
            return False

    def _ask(self, prompt: str) -> dict:
        import requests
        resp = requests.post(
            f"{self.url}/api/chat",
            json={
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "format": "json",
                "stream": False,
                "options": {"temperature": 0},
            },
            timeout=self.timeout_s,
        )
        resp.raise_for_status()
        return json.loads(resp.json()["message"]["content"])

    def score_ticker(self, ticker: str) -> SentimentResult:
        headlines = fetch_headlines(ticker)
        if not headlines:
            return SentimentResult(confidence="none")
        prompt = _PROMPT.format(ticker=ticker,
                                headlines="\n".join(f"- {h}" for h in headlines))
        try:
            raw = self._ask(prompt)
        except Exception as exc:
            log.warning("ollama scoring echoue pour %s: %s", ticker, exc)
            return SentimentResult(confidence="none",
                                   n_headlines=len(headlines))
        return parse_llm_sentiment(raw, n_headlines=len(headlines))


def parse_llm_sentiment(raw: dict, n_headlines: int = 0) -> SentimentResult:
    """Validation stricte de la sortie LLM: score borne, confiance connue."""
    try:
        score = float(raw.get("score", 50))
    except (TypeError, ValueError):
        score = 50.0
    score = min(max(score, 0.0), 100.0)
    confidence = str(raw.get("confidence", "low")).lower()
    if confidence not in ("low", "medium", "high"):
        confidence = "low"
    def _strlist(key):
        v = raw.get(key, [])
        return [str(x)[:200] for x in v][:3] if isinstance(v, list) else []
    return SentimentResult(score=score, confidence=confidence,
                           risks=_strlist("risks"),
                           opportunities=_strlist("opportunities"),
                           n_headlines=n_headlines)


def get_sentiment_provider() -> SentimentProvider:
    """Provider du PILIER composite. Reste neutre tant que le mode fantome
    n'a pas prouve son pouvoir predictif (ne pas brancher Ollama ici sans
    passer par la validation decrite dans docs/ROADMAP.md)."""
    return NeutralSentiment()
