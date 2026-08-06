"""Converse — chat with a document: multi-turn, grounded; history resolves the query, retrieval answers it."""

from __future__ import annotations

from app.pipeline import converse_followup, converse_start

DOC = ("The onboarding deadline is May 10. New hires must complete a security training first. "
       "Payroll is handled by the finance team. The office reopens in September for all staff.")


def test_start_answers_and_returns_a_session():
    r = converse_start(DOC, "When is the onboarding deadline?")
    assert r.session_id and len(r.turns) == 1
    assert r.turns[0].answered and "May 10" in r.turns[0].answer
    assert r.turns[0].citations                       # grounded — cites a passage


def test_followup_continues_the_same_conversation():
    r1 = converse_start(DOC, "When is the onboarding deadline?")
    r2 = converse_followup(r1.session_id, "Who handles payroll?")
    assert r2.session_id == r1.session_id
    assert len(r2.turns) == 2                          # the conversation grew, over the SAME stored document
    assert "finance" in r2.turns[1].answer.lower()


NAVY = ("Greek fire saved Constantinople from several Arab sieges. "
        "The navy declined in the 11th century, forcing the empire to rely on the fleets of Venice and Genoa.")


def test_elliptical_followup_resolves_via_prior_question():
    """⭐ the Demo regression: a referential follow-up ('what did that force?') must resolve to the prior topic and
    answer from the document — not abstain. Retrieval falls back to the prior question so the right passage is
    found; the model is handed the prior questions so the pronoun resolves (checked live on `anthropic`)."""
    r1 = converse_start(NAVY, "When did the navy decline?")
    assert r1.turns[0].answered and "11th century" in r1.turns[0].answer
    r2 = converse_followup(r1.session_id, "What did that force?")
    assert r2.turns[1].answered, "an elliptical follow-up should resolve, not abstain"
    ans = r2.turns[1].answer.lower()
    assert "venice" in ans or "genoa" in ans


def test_abstains_out_of_document():
    r = converse_start(DOC, "What is the CEO's salary?")
    assert not r.turns[0].answered
    assert "couldn't find" in r.turns[0].answer.lower()
    assert not r.turns[0].citations


def test_expired_session_asks_to_re_add():
    r = converse_followup("no-such-session-id", "anything?")
    assert r.expired and "re-add the document" in (r.block_message or "")


def test_model_only_sees_safe_text():
    doc = "Contact Michael Torres at michael.torres@example.com. The renewal date is June 1 for all members."
    captured = {}
    import app.pipeline as pipeline

    real = pipeline.draft_answer

    def spy(safe_query, retrieved, provider, **kw):
        seen = safe_query + " " + " ".join(sp.text for sp in retrieved) + " " + " ".join(kw.get("context") or [])
        captured["seen"] = seen
        return real(safe_query, retrieved, provider, **kw)

    pipeline.draft_answer = spy
    try:
        converse_start(doc, "What is the renewal date?")
    finally:
        pipeline.draft_answer = real

    assert r"michael.torres@example.com" not in captured.get("seen", "")


def test_reproducible_first_turn():
    a = converse_start(DOC, "When does the office reopen?")
    b = converse_start(DOC, "When does the office reopen?")
    assert a.turns[0].answer == b.turns[0].answer
