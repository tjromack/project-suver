"""Draft a reply (Communications tool #3): grounded reply; unknowns → [placeholders], never invented; invented
specifics flagged; the model only ever sees safe text. Stub-backed (no network)."""

from __future__ import annotations

from app.pipeline import _invented_specifics, draft_reply_text, reply_intents

MSG = "From: Priya\nHi — can you send me the Q2 forecast? Thanks."


def test_drafts_a_reply_with_placeholders():
    r = draft_reply_text(MSG, "answer")
    assert r.reply and not r.blocked
    assert r.intent_slug == "answer"
    assert r.placeholders, "an ungrounded reply should leave [placeholders] to fill, not invent"


def test_intent_pick_changes_the_reply():
    a = draft_reply_text(MSG, "acknowledge")
    d = draft_reply_text(MSG, "decline")
    assert a.reply != d.reply
    assert a.intent_label == "Acknowledge & confirm" and d.intent_label == "Politely decline"


def test_unknown_intent_falls_back():
    r = draft_reply_text(MSG, "not-a-real-intent")
    assert r.intent_slug == "acknowledge"


def test_invented_specifics_are_flagged():
    # a money/time/date in the draft that isn't in the message → flagged for the user to verify
    assert _invented_specifics("Let's meet at 3:00pm for $500.", "Can we meet sometime?") == ["3:00pm", "$500"]
    assert _invented_specifics("Sounds good, see you then.", "Can we meet at 3:00pm?") == []


def test_reply_never_invents_a_specific_from_the_stub():
    r = draft_reply_text("Can you confirm the plan?", "acknowledge")
    assert r.unverified == []                 # the stub uses placeholders, never a concrete specific


def test_model_only_sees_safe_text():
    doc = "Please reply to me at priya@example.com about the Q2 forecast."
    captured = {}
    import app.pipeline as pipeline

    real = pipeline.draft_reply

    def spy(safe_message, intent_slug, intent_focus, provider):
        captured["seen"] = safe_message
        return real(safe_message, intent_slug, intent_focus, provider)

    pipeline.draft_reply = spy
    try:
        draft_reply_text(doc, "answer")
    finally:
        pipeline.draft_reply = real

    assert captured.get("seen") and "priya@example.com" not in captured["seen"]


def test_intents_are_available_for_the_select():
    slugs = [s for s, _ in reply_intents()]
    assert "acknowledge" in slugs and "decline" in slugs and len(slugs) >= 4


def test_reproducible():
    a = draft_reply_text(MSG, "follow_up")
    b = draft_reply_text(MSG, "follow_up")
    assert a.reply == b.reply and a.placeholders == b.placeholders
