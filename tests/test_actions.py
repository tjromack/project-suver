"""Meeting notes → actions (Communications platform, tool #1): cite-or-drop the action; owner/due only if stated;
the model only ever sees safe text. Stub-backed (no network)."""

from __future__ import annotations

from app.pipeline import _stated, extract_actions

NOTES = (
    "Team sync notes — May 3.\n"
    "Finance will send the revised budget by Friday.\n"
    "Marketing should review the campaign draft before June 10.\n"
    "We discussed the new office layout and everyone liked it.\n"
    "Action item: schedule the vendor call.\n"
    "Contact Michael Torres at michael.torres@example.com for the contract.\n"
    "Michael Torres will finalize the contract by June 30.\n"
)


def test_extracts_grounded_action_items():
    r = extract_actions(NOTES)
    assert not r.empty and r.items
    assert any("budget" in a.task.lower() for a in r.items)
    for a in r.items:                                     # cite-or-drop: every action grounds to a source span
        assert a.span_id.startswith("S") and a.support >= 0.6


def test_a_non_action_line_is_not_listed():
    r = extract_actions(NOTES)
    # "everyone liked it" is discussion, not a commitment — it must not become an action
    assert not any("liked it" in a.task.lower() for a in r.items)


def test_owner_and_due_shown_only_when_stated():
    r = extract_actions(NOTES)
    fin = next(a for a in r.items if a.task.lower().startswith("finance"))
    assert fin.owner == "Finance" and fin.due == "Friday"
    sched = next(a for a in r.items if "schedule the vendor call" in a.task.lower())
    assert sched.owner == "" and sched.due == ""         # no owner/due stated → shown blank, never guessed


def test_owner_from_a_boundary_token_rehydrates_locally():
    """⭐ the neat compose: a name is PII → the boundary tokenizes it → the owner comes back as the real name in
    the local view, though the model only ever saw the token."""
    r = extract_actions(NOTES)
    mt = next((a for a in r.items if "finalize the contract" in a.task.lower()), None)
    assert mt is not None and mt.owner == "Michael Torres" and mt.due == "June 30"


def test_stated_guards_against_a_guessed_value():
    notes = "finance will send the revised budget by friday."
    assert _stated("Finance", notes) == "Finance"        # present in the notes → kept
    assert _stated("Acme Corp", notes) == ""             # absent → dropped (never guess an owner)
    assert _stated("[PERSON_NAME_9]", notes) == ""       # a token that isn't in the notes → dropped


def test_honest_empty_when_no_actions():
    r = extract_actions("We had a pleasant chat about the weather and the garden. It was a nice afternoon.")
    assert r.empty and "No action items" in (r.empty_note or "")


def test_model_only_sees_safe_text():
    doc = "Michael Torres will email michael.torres@example.com the report by June 1."
    captured = {}
    import app.pipeline as pipeline

    real = pipeline.extract_action_items

    def spy(safe_text, provider):
        captured.setdefault("seen", []).append(safe_text)
        return real(safe_text, provider)

    pipeline.extract_action_items = spy
    try:
        extract_actions(doc)
    finally:
        pipeline.extract_action_items = real

    seen = " ".join(captured.get("seen", []))
    assert seen and "michael.torres@example.com" not in seen


def test_reproducible():
    a = extract_actions(NOTES)
    b = extract_actions(NOTES)
    assert [x.task for x in a.items] == [x.task for x in b.items]
    assert [x.owner for x in a.items] == [x.owner for x in b.items]
