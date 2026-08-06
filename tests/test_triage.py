"""Triage messages (Communications tool #2): bucket each message by what it needs; ambiguous → 'review' (never a
confident wrong bucket); the reason grounds to the message; the model only ever sees safe text. Stub-backed."""

from __future__ import annotations

from app.pipeline import triage_messages

INBOX = (
    "Hi, can you send me the Q2 numbers by end of day? Thanks, Priya\n\n"
    "FLASH SALE — 40% off ends tonight! Unsubscribe here.\n\n"
    "Please review and approve the vendor contract before Friday.\n\n"
    "FYI — the office will be closed next Monday for the holiday.\n\n"
    "hmmmm\n"
)


def test_buckets_messages_by_what_they_need():
    r = triage_messages(INBOX)
    assert not r.empty and r.items
    cats = {it.category for it in r.items}
    assert "needs_reply" in cats            # "can you send… ?"
    assert "action" in cats                 # "please review and approve… before Friday"
    assert "ignore" in cats                 # the flash-sale / unsubscribe
    assert r.counts                          # the summary line has per-bucket counts


def test_important_buckets_come_first():
    r = triage_messages(INBOX)
    order = [it.category for it in r.items]
    # needs_reply / action must appear before ignore in the sorted view
    assert order.index("needs_reply") < order.index("ignore")
    assert order.index("action") < order.index("ignore")


def test_ambiguous_message_is_flagged_review_not_guessed():
    """A message with no clear cue (low confidence) is shown as Review, not forced into a confident bucket."""
    r = triage_messages("hmmmm, not sure what to do here really")
    assert r.items and r.items[0].category == "unsure"
    assert r.items[0].category_label == "Review"


def test_reason_is_grounded_in_the_message():
    r = triage_messages(INBOX)
    for it in r.items:
        if it.reason:                        # a shown reason must be drawn from the message, not invented
            words = [w for w in it.reason.lower().split() if len(w) > 3]
            hit = sum(1 for w in words if w in it.snippet.lower())
            assert not words or hit >= 1


def test_empty_input_is_honest():
    r = triage_messages("   \n  \n ")
    assert r.empty and "No messages" in (r.empty_note or "")


def test_model_only_sees_safe_text():
    doc = "Can you email me back at jane.doe@example.com about the renewal? — Jane"
    captured = {}
    import app.pipeline as pipeline

    real = pipeline.classify_messages

    def spy(messages, provider):
        captured["seen"] = " ".join(messages)
        return real(messages, provider)

    pipeline.classify_messages = spy
    try:
        triage_messages(doc)
    finally:
        pipeline.classify_messages = real

    assert captured.get("seen") and "jane.doe@example.com" not in captured["seen"]


def test_reproducible():
    a = triage_messages(INBOX)
    b = triage_messages(INBOX)
    assert [it.category for it in a.items] == [it.category for it in b.items]
    assert [it.snippet for it in a.items] == [it.snippet for it in b.items]
