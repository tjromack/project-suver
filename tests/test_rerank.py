"""LLM re-ranking (DEC 040) — after lexical retrieval pulls a WIDER candidate pool, the model re-orders those
(already-sanitized) passages so the ones that actually answer the question land in the top-K the answerer reads.
All deterministic/offline: the stub returns no order (behavior == today's lexical order); the reorder logic and the
pool-widening are tested with a fake ranker supplied directly. The grounding gate is never touched by re-ranking."""

from __future__ import annotations

import app.pipeline as pipeline
from app._engines.summarize import split_document
from app.config import Settings
from app.pipeline import _answer_over_spans, _rerank
from app.provider import rerank_passages


def test_stub_returns_no_order_behavior_unchanged():
    # the stub/no-key path is a no-op → retrieval keeps its deterministic lexical order (today's behavior)
    assert rerank_passages("what is the fee?", ["a passage", "another passage"], "stub") == []
    assert rerank_passages("q", ["only one"], "anthropic") == []   # <2 candidates → nothing to rank
    assert rerank_passages("", ["a", "b"], "anthropic") == []       # empty query → no-op


def test_rerank_off_by_default():
    # opt-in only (it adds a model call per question); default env leaves it off
    assert pipeline.settings.retrieval_rerank is False


def test_rerank_reorders_and_appends_missing(monkeypatch):
    spans = split_document("Alpha one. Bravo two. Charlie three.")
    scored = [(sp, 1.0) for sp in spans]                            # 3 candidates
    # model ranks #3 then #1 as relevant, omits #2 → we keep that order and APPEND the omitted one (never drop it)
    monkeypatch.setattr(pipeline, "rerank_passages", lambda q, passages, provider: [2, 0])
    out = _rerank("q", scored, "anthropic")
    assert [sp.text for sp, _ in out] == [spans[2].text, spans[0].text, spans[1].text]


def test_rerank_empty_order_is_a_noop(monkeypatch):
    spans = split_document("Alpha one. Bravo two.")
    scored = [(sp, 1.0) for sp in spans]
    monkeypatch.setattr(pipeline, "rerank_passages", lambda q, passages, provider: [])
    assert _rerank("q", scored, "anthropic") == scored             # order unchanged


def test_rerank_widens_the_candidate_pool_and_reorders(monkeypatch):
    """⭐ With re-ranking ON, retrieval hands the model a pool WIDER than top-K (so it has real choices to promote),
    then the code keeps the model's top-K. Here the model reverses the pool → the passage lexical order buried at the
    bottom becomes the answer. Only the safe query + passages are sent; grounding still verifies (fake draft echoes a
    retrieved passage, so it grounds)."""
    text = " ".join(f"Sentence number {i} about topic {i}." for i in range(1, 16))
    spans = split_document(text)
    seen: dict[str, int] = {}

    def fake_rerank(q, passages, provider):
        seen["count"] = len(passages)
        return list(reversed(range(len(passages))))                # reverse the pool

    def fake_draft(q, ranked, provider, context=None, across=False):
        return ranked[0].text                                      # answer = top passage → grounds trivially

    monkeypatch.setattr(pipeline, "rerank_passages", fake_rerank)
    monkeypatch.setattr(pipeline, "draft_answer", fake_draft)
    monkeypatch.setattr(pipeline, "settings", Settings(retrieval_rerank=True))

    ok, ans, cites = _answer_over_spans(spans, "topic number", {}, "anthropic")
    assert ok
    assert seen["count"] > pipeline.settings.copilot_top_k          # the pool was widened beyond the final K
    assert "number 12" in ans                                       # reversed pool (S1..S12) → S12 promoted to top


def test_rerank_stress_set_is_well_formed():
    """The retrieval-stress recall set (DEC 046) is structurally valid; the before/after runner imports cleanly.
    (The cases run on the REAL model via `python -m eval.rerank_delta` — not exercised here.)"""
    import eval.rerank_delta  # noqa: F401 — must import without error
    from eval.cases import RERANK_STRESS
    assert len(RERANK_STRESS) >= 3
    assert all(c.category == "answerable" and c.expect_answer for c in RERANK_STRESS)
    assert all(len(c.docs) == 1 for c in RERANK_STRESS)   # single-doc -> the Copilot retrieval path


def test_rerank_is_additive_never_drops_lexical_topk(monkeypatch):
    """DEC 047: additive re-ranking — the model may promote a buried passage, but a lexical top-K hit is never dropped
    (calibration found rerank could demote a correct passage out of the top-K and regress recall)."""
    text = " ".join(f"Sentence number {i} about topic {i}." for i in range(1, 16))
    spans = split_document(text)

    def fake_rerank(q, passages, provider):
        return list(range(len(passages) - 1, len(passages) - 5, -1))   # rank only the LAST pool passages; omit the lexical top ones

    def fake_draft(q, ranked, provider, context=None, across=False):
        return " ".join(sp.text for sp in ranked)                      # everything that survived into the answer set

    monkeypatch.setattr(pipeline, "rerank_passages", fake_rerank)
    monkeypatch.setattr(pipeline, "draft_answer", fake_draft)
    monkeypatch.setattr(pipeline, "settings", Settings(retrieval_rerank=True))
    ok, ans, cites = _answer_over_spans(spans, "topic number", {}, "anthropic")
    assert ok
    assert "number 1 about topic 1" in ans      # the lexical top-1 survived even though the reranker omitted it
