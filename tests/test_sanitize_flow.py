"""Phase 3 — the boundary in the flow: ⭐ the model only ever sees Data-Boundary-safe text.

The headline trust invariant of the product. If any of these fail, sensitive data could reach the model — ship-block.
"""

from __future__ import annotations

from app._engines.boundary import default_policy, rehydrate, sanitize
from app.pipeline import summarize_text

# A synthetic record with several planted sensitive values.
PLANTED_SSN = "123-45-6789"
DOC = (
    "Quarterly member review. The account holder is Michael Torres and can be reached at "
    "michael.torres@example.com or (415) 555-0148. Member SSN 123-45-6789 was verified. "
    "The plan renews on schedule and the deductible was met in Q2."
)


def test_boundary_removes_planted_ssn_from_safe_text():
    r = sanitize(DOC, default_policy())
    assert r.decision == "redacted"
    assert r.safe_text is not None
    # ⭐ the planted SSN must NOT survive into the text that may leave the boundary
    assert PLANTED_SSN not in r.safe_text
    assert "michael.torres@example.com" not in r.safe_text
    assert "[SSN_1]" in r.safe_text


def test_pipeline_never_exposes_planted_value_to_the_model():
    """⭐ THE invariant: what the pipeline hands the drafter (safe_text) contains no planted sensitive value."""
    captured = {}

    import app.pipeline as pipeline

    real_draft = pipeline.draft_candidates

    def spy(safe_text, spans, provider):
        captured["seen_by_model"] = safe_text
        return real_draft(safe_text, spans, provider)

    pipeline.draft_candidates = spy
    try:
        summarize_text(DOC)  # stub provider
    finally:
        pipeline.draft_candidates = real_draft

    seen = captured["seen_by_model"]
    assert PLANTED_SSN not in seen
    assert "michael.torres@example.com" not in seen
    assert "(415) 555-0148" not in seen


def test_rehydrate_restores_locally_only():
    r = sanitize(DOC, default_policy())
    # a model reply that echoes tokens re-hydrates to the real values — LOCAL only
    model_reply = "Key point about [SSN_1] and [EMAIL_1]."
    restored = rehydrate(model_reply, r.token_map)
    assert PLANTED_SSN in restored
    assert "michael.torres@example.com" in restored
    # the token map is never part of the safe text
    assert PLANTED_SSN not in r.safe_text


def test_displayed_summary_rehydrates_but_model_did_not_see_it():
    res = summarize_text(DOC)
    assert not res.blocked
    assert res.handled_count >= 3  # ssn + email + phone + name at least
    # the user sees their real values back in the cited summary (re-hydrated locally)
    joined = " ".join(c.text + " " + c.span_text for c in res.claims)
    # at least one planted value shows in the local view (it was tokenized, not dropped)
    assert PLANTED_SSN in joined or "Michael Torres" in joined or "michael.torres@example.com" in joined


def test_never_egress_class_blocks_the_whole_summary():
    """A never_egress class → route_local → safe_text is None → we do NOT summarize (fail-closed)."""
    from app._engines.boundary.policy import parse_policy

    local_policy = parse_policy({
        "id": "test-local",
        "version": "1.0.0",
        "default_action": "route_local",
        "classes": [{"name": "ssn", "detector": "ssn", "never_egress": True}],
    })
    r = sanitize(DOC, local_policy)
    assert r.decision == "route_local"
    assert r.safe_text is None  # ⭐ nothing may leave
