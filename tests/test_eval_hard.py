"""Offline guards for the HARD eval set (messy documents).

Like `test_eval_harness.py`, this asserts the set is well-formed and the runner executes — NOT real-model quality.
The actual hard-set trust numbers (and the failures we then fix) come from `python -m eval.run_hard` against
`anthropic`. This keeps the hard set from silently rotting between real runs."""

from __future__ import annotations

from eval.cases_hard import HARD_CASES
from eval.run import run


def test_hard_cases_are_well_formed():
    ids = [c.id for c in HARD_CASES]
    assert len(ids) == len(set(ids)), "hard case ids must be unique"
    for c in HARD_CASES:
        assert c.category in ("answerable", "unanswerable", "adversarial", "sensitive")
        assert c.docs and all(name and text for name, text in c.docs)
        assert c.question and c.note, f"{c.id}: every hard case needs a question and a note (why it's hard)"
        assert any([c.expect_answer, c.expect_abstain, c.forbid_anywhere, c.forbid_in_doc, c.expect_handled])


def test_hard_harness_runs_offline():
    results, summary = run(provider="stub", cases=HARD_CASES)
    assert len(results) == len(HARD_CASES)
    assert summary["total"] == len(HARD_CASES)
