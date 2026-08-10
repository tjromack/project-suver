"""Smoke test for the Trust & Quality eval harness — plumbing only, offline (stub).

This verifies the harness RUNS end to end and scores every case; it does NOT assert real-model quality (the stub's
behavior differs from the product's real model — the actual trust numbers come from `python -m eval.run` against
`anthropic`, recorded in `eval/SCORECARD.md`)."""

from __future__ import annotations

from eval.cases import CASES, EvalCase
from eval.run import run, scorecard_md


def test_every_case_is_well_formed():
    ids = [c.id for c in CASES]
    assert len(ids) == len(set(ids)), "case ids must be unique"
    for c in CASES:
        assert c.category in ("answerable", "unanswerable", "adversarial", "sensitive")
        assert c.docs and all(name and text for name, text in c.docs)
        assert c.question
        # every case asserts SOMETHING (a recall, an abstention, a lure ban, or PII handling)
        assert any([c.expect_answer, c.expect_abstain, c.forbid_anywhere, c.forbid_in_doc, c.expect_handled])


def test_harness_runs_and_scores_every_case_offline():
    results, summary = run(provider="stub")
    assert len(results) == len(CASES)
    assert summary["total"] == len(CASES)
    assert set(summary["by_category"]) == {"answerable", "unanswerable", "adversarial", "sensitive"}
    # each category bucket is (passed, total) with passed ≤ total
    for passed, total in summary["by_category"].values():
        assert 0 <= passed <= total
    # the scorecard renders without error
    md = scorecard_md(results, summary)
    assert "Trust & Quality Scorecard" in md and "PII handled" in md


def test_sensitive_cases_tokenize_pii_before_the_model_even_on_the_stub():
    """The boundary runs before any provider, so PII is handled regardless of provider — assert it on the stub."""
    results, _ = run(provider="stub")
    for r in results:
        if r.case.category == "sensitive":
            assert r.handled >= 1, f"{r.case.id}: planted PII was not handled before the model"
