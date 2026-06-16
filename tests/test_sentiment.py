"""LLM sentiment output validation tests (no network, no model)."""

from atlas.features.sentiment import (NeutralSentiment, parse_llm_sentiment,
                                      get_sentiment_provider)


def test_parse_valid_output():
    raw = {"score": 78, "confidence": "high",
           "risks": ["concurrence accrue"], "opportunities": ["nouveau produit"]}
    r = parse_llm_sentiment(raw, n_headlines=8)
    assert r.score == 78.0
    assert r.confidence == "high"
    assert r.risks == ["concurrence accrue"]
    assert r.n_headlines == 8


def test_parse_clamps_score():
    assert parse_llm_sentiment({"score": 150}).score == 100.0
    assert parse_llm_sentiment({"score": -20}).score == 0.0
    assert parse_llm_sentiment({"score": "n/a"}).score == 50.0


def test_parse_rejects_unknown_confidence():
    assert parse_llm_sentiment({"score": 60, "confidence": "tres sur"}).confidence == "low"


def test_parse_truncates_lists():
    raw = {"score": 50, "risks": [f"r{i}" for i in range(10)],
           "opportunities": "pas une liste"}
    r = parse_llm_sentiment(raw)
    assert len(r.risks) == 3
    assert r.opportunities == []


def test_composite_provider_stays_neutral():
    """Le pilier composite DOIT rester neutre tant que le fantome n'a pas
    prouve son IC: garde-fou contre une activation accidentelle."""
    provider = get_sentiment_provider()
    assert isinstance(provider, NeutralSentiment)
    assert provider.score_ticker("MSFT").score == 50.0
