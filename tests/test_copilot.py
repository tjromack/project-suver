"""Copilot — "Ask this document": grounded answer or honest abstention; the model only sees safe text."""

from __future__ import annotations

from app.pipeline import answer_question

DOC = (
    "The project deadline is March 15. The budget is set at fifty thousand dollars. "
    "Alice leads the design team and reports to the steering committee. "
    "All deliverables must pass a security review before release."
)


def test_answers_from_the_document_with_citations():
    r = answer_question(DOC, "What is the project deadline?")
    assert r.answered and not r.abstained
    assert "March 15" in r.answer
    assert r.citations and r.citations[0].span_id.startswith("S")


def test_abstains_when_not_in_the_document():
    r = answer_question(DOC, "What is the capital of France?")
    assert not r.answered and r.abstained
    assert "couldn't find" in r.answer.lower()
    assert not r.citations  # nothing shown as trusted


def test_model_only_sees_safe_text_on_the_qa_path():
    """⭐ the invariant holds for Copilot too: the drafter's passages carry no planted sensitive value."""
    doc = "Contact Michael Torres at 415-555-0148. His member SSN 123-45-6789 is on file. The renewal date is June 1."
    captured = {}
    import app.pipeline as pipeline

    real = pipeline.draft_answer

    def spy(safe_query, retrieved, provider):
        captured["passages"] = " ".join(sp.text for sp in retrieved)
        captured["query"] = safe_query
        return real(safe_query, retrieved, provider)

    pipeline.draft_answer = spy
    try:
        answer_question(doc, "What is the SSN on file?")
    finally:
        pipeline.draft_answer = real

    seen = captured.get("passages", "") + " " + captured.get("query", "")
    assert "123-45-6789" not in seen
    assert "415-555-0148" not in seen


def test_query_is_also_sanitized_and_counted():
    r = answer_question("The renewal date is June 1.", "Does 123-45-6789 appear anywhere?")
    # the planted SSN in the QUESTION is handled by the boundary before the model sees it
    assert r.handled_count >= 1


def test_reproducible():
    a = answer_question(DOC, "Who leads the design team?")
    b = answer_question(DOC, "Who leads the design team?")
    assert a.answer == b.answer and [c.span_id for c in a.citations] == [c.span_id for c in b.citations]
