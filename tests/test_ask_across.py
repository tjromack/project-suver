"""Ask across your documents — grounded Q&A over a SET of documents: the answer cites the document each fact
came from, or abstains; the model only ever sees sanitized passages (per document)."""

from __future__ import annotations

from app.pipeline import ask_across, ask_across_inputs
from app.tools import ToolInput, get, load_builtin

load_builtin()   # register the built-in tools so get("ask-across") resolves (mirrors app startup)

DOC_A = (
    "renewal-terms.txt",
    "The subscription auto-renews for a further year unless either party gives ninety days written notice. "
    "Fees are payable net thirty days from the invoice date.",
)
DOC_B = (
    "termination.txt",
    "This agreement terminates on December 31, 2026. The governing law is the State of Delaware. "
    "Neither party may assign its rights without consent.",
)
DOC_C = (
    "liability.txt",
    "Total liability under this agreement is capped at the fees paid in the preceding twelve months. "
    "Nothing limits liability for gross negligence.",
)


def _answer_for(r, doc):
    return next(d for d in r.per_doc if d.doc == doc)


def test_answers_per_document_and_attributes_to_the_right_document():
    r = ask_across([DOC_A, DOC_B, DOC_C], "What notice is needed to stop the auto-renewal?")
    assert r.answered
    a = _answer_for(r, "renewal-terms.txt")
    assert a.answered and ("ninety" in a.answer.lower())
    assert a.citations, "a grounded answer must cite at least one passage in its own document"
    # attribution is by construction: the auto-renewal answer belongs to the renewal doc, not the others
    assert "renewal-terms.txt" in r.source_docs


def test_no_cross_document_contamination():
    """⭐ the reason this tool answers per-document: a fact from one doc must never leak into another's answer.
    Only the renewal doc states a fee; the NDA says 'no fees'. Asking the fee question must not let the NDA's
    'no fees' contaminate the renewal doc's answer."""
    fee_docs = [
        ("services.txt", "The monthly fee is $12,000, payable net thirty days from the invoice date."),
        ("nda.txt", "There are no fees under this Agreement. It expires after three years."),
    ]
    r = ask_across(fee_docs, "What is the monthly fee?")
    services = _answer_for(r, "services.txt")
    assert services.answered and "12,000" in services.answer
    # the services answer is grounded ONLY in the services doc — the NDA's "no fees" can't reach it
    assert all("no fees" not in c.span_text.lower() for c in services.citations)


def test_morphological_recall_surfaces_the_obvious_answer():
    """Retrieval is stemmed (plural/-ly), so a question phrased as a morphological variant still finds the passage:
    'monthly fee' finds a '$12,000 per month … fees' clause. The fix that made Acme answer in the live demo."""
    from app._engines.summarize import retrieval_support, support

    span = "Fees are $12,000 per month, due net thirty days from the invoice date."
    # plain (grounding) support misses it — "monthly"≠"month", "fee"≠"fees"; stemmed retrieval finds it
    assert support("What is the monthly fee?", span) == 0.0
    assert retrieval_support("What is the monthly fee?", span) > 0.0

    docs = [
        ("acme.txt", "The fee is $12,000 per month, due net thirty days from the invoice date."),
        ("nda.txt", "There are no fees under this Agreement. It expires after three years."),
    ]
    r = ask_across(docs, "What is the monthly fee?")
    acme = _answer_for(r, "acme.txt")
    assert acme.answered and "12,000" in acme.answer
    # the NDA's "no fees" must stay in the NDA's row — never contaminate the Acme answer
    assert "no fees" not in (acme.answer or "").lower()


def test_searches_every_document_supplied():
    r = ask_across([DOC_A, DOC_B, DOC_C], "What is the governing law?")
    assert r.n_docs == 3
    assert set(r.doc_names) == {"renewal-terms.txt", "termination.txt", "liability.txt"}
    assert len(r.per_doc) == 3
    assert r.answered and "termination.txt" in r.source_docs


def test_abstains_when_no_document_addresses_the_question():
    r = ask_across([DOC_A, DOC_B, DOC_C], "What is the capital of France?")
    assert not r.answered
    assert r.n_answered == 0
    assert all(not d.answered for d in r.per_doc)   # nothing shown as trusted
    assert "none of your" in r.summary_line.lower()


def test_model_only_sees_safe_text_across_the_corpus():
    """⭐ the invariant holds across a set too: no document's planted sensitive value reaches the drafter."""
    docs = [
        ("client-a.txt", "Contact Michael Torres at 415-555-0148. The renewal date is June 1."),
        ("client-b.txt", "Member SSN 123-45-6789 is on file. The plan covers dental and vision."),
    ]
    captured = {}
    import app.pipeline as pipeline

    real = pipeline.draft_answer

    def spy(safe_query, retrieved, provider, **kw):
        captured["passages"] = " ".join(sp.text for sp in retrieved)
        captured["query"] = safe_query
        return real(safe_query, retrieved, provider, **kw)

    pipeline.draft_answer = spy
    try:
        ask_across(docs, "What does the plan cover?")
    finally:
        pipeline.draft_answer = real

    seen = captured.get("passages", "") + " " + captured.get("query", "")
    assert "123-45-6789" not in seen
    assert "415-555-0148" not in seen


def test_counts_sensitive_items_handled_across_documents():
    docs = [
        ("a.txt", "Email alice@example.com about the deadline."),
        ("b.txt", "Call 415-555-0148 for the renewal."),
    ]
    r = ask_across(docs, "What is the deadline?")
    assert r.handled_count >= 2   # one per document, handled before the model


def test_reproducible():
    a = ask_across([DOC_A, DOC_B], "What notice is needed to stop the auto-renewal?")
    b = ask_across([DOC_A, DOC_B], "What notice is needed to stop the auto-renewal?")
    assert [d.answer for d in a.per_doc] == [d.answer for d in b.per_doc]
    assert a.source_docs == b.source_docs


def test_paste_counts_as_one_more_document():
    r = ask_across_inputs([], DOC_A[1], "What notice is needed to stop the auto-renewal?")
    assert r.n_docs == 1
    assert r.doc_names == ["Pasted text"]
    assert r.answered and "Pasted text" in r.source_docs


# --- the tool contract ------------------------------------------------------------------------------


def test_tool_is_registered_and_multi_document():
    t = get("ask-across")
    assert t is not None and t.is_live
    assert t.needs_many and t.needs_query
    assert t.platform == "Documents"


def test_tool_requires_documents_and_a_question():
    import pytest

    from app.tools import ToolError

    t = get("ask-across")
    with pytest.raises(ToolError):
        t.run(ToolInput(many=[], query="anything"))     # no documents
    with pytest.raises(ToolError):
        t.run(ToolInput(many=[("a.txt", b"hello world")], query=""))   # no question


def test_tool_run_returns_the_ask_across_partial():
    t = get("ask-across")
    out = t.run(ToolInput(
        many=[("renewal-terms.txt", DOC_A[1].encode()), ("termination.txt", DOC_B[1].encode())],
        query="What notice is needed to stop the auto-renewal?",
    ))
    assert out.template == "_ask_across_result.html"
    assert out.result.answered
