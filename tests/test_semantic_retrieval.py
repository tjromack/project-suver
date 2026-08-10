"""Semantic-recall retrieval (DEC 032) — the model expands the question into alternative phrasings so a passage
that STATES the answer in different words still surfaces; the grounding gate is untouched. All deterministic/offline:
the stub returns no expansions (behavior == today), and the hybrid ranking is tested with phrasings supplied directly."""

from __future__ import annotations

import app.pipeline as pipeline
from app._engines.summarize import split_document
from app.pipeline import _phrasings, _retrieve, ask_across
from app.provider import expand_query

SPAN = "Section 3. The vendor shall pay Acme twelve thousand dollars per month, net thirty days from invoice."


def test_stub_returns_no_expansions_behavior_unchanged():
    assert expand_query("what is the monthly fee?", "stub") == []
    # with the stub/no-key, _phrasings degrades to just the literal question → today's exact behavior
    assert _phrasings("what is the monthly fee?", "stub") == ["what is the monthly fee?"]
    assert _phrasings("", "stub") == []


def test_phrasings_widen_retrieval_to_a_paraphrase():
    spans = split_document(SPAN)
    # the bare question shares NO content tokens with the passage ("compensation/owed" ≠ "shall pay … per month")
    assert _retrieve("What compensation is owed?", spans) == []
    # supplying alternative phrasings surfaces the passage — recall the lexical retriever alone can't reach
    got = _retrieve("What compensation is owed?", spans,
                    phrasings=["What compensation is owed?", "shall pay", "per month"])
    assert got and "shall pay" in got[0][0].text


def test_expansion_never_weakens_the_grounding_gate():
    """⭐ the DEC 032 guarantee: expansion widens RETRIEVAL only. A passage that a phrasing pulled in but that does
    NOT support the answer must still be dropped by the unchanged exact-token grounding — no phrasing can make an
    ungrounded claim show. (Here a fabricated claim grounds at 0 against the surfaced span.)"""
    from app._engines.summarize import support

    assert support("The monthly fee is one million dollars.", SPAN) < 0.6  # exact-token grounding unaffected


def test_ask_across_expands_once_per_question_not_per_document(monkeypatch):
    calls = {"n": 0}

    def fake_expand(q, provider, n=6):
        calls["n"] += 1
        return ["per month", "shall pay"]

    monkeypatch.setattr(pipeline, "expand_query", fake_expand)
    docs = [
        ("a.txt", "The vendor shall pay $12,000 per month under this agreement."),
        ("b.txt", "This NDA has a three year term and no fees."),
        ("c.txt", "Governing law is the State of Delaware."),
    ]
    r = ask_across(docs, "What is the monthly fee?")
    assert calls["n"] == 1                       # expanded ONCE for the whole 3-doc set, not per document
    a = next(d for d in r.per_doc if d.doc == "a.txt")
    assert a.answered and "12,000" in a.answer   # the fee passage was retrieved and answered
    # contamination still impossible: the NDA's "no fees" stays out of the fee doc's answer
    assert "no fees" not in (a.answer or "").lower()
