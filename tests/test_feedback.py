"""Feedback → review queue (DEC 042) — the online-eval signal. A 👍/👎/flag on a result + an optional note, feeding a
review queue that a human curates into the offline eval set. ⭐ Privacy by design: no document or answer content is
ever stored — only the tool, the verdict, and the typed note. All offline (the store never calls a model)."""

from __future__ import annotations

import pytest
from app import store
from app.main import app
from fastapi.testclient import TestClient

client = TestClient(app)


@pytest.fixture(autouse=True)
def _clear_feedback():
    with store._conn() as con:
        con.execute("DELETE FROM feedback")
    yield


def test_add_and_query_feedback():
    store.add_feedback("copilot", "up")
    store.add_feedback("summarize", "down", "missed the date")
    store.add_feedback("draft", "flag", "invented a clause")
    assert store.feedback_counts() == {"up": 1, "down": 1, "flag": 1}
    review = store.recent_feedback(only_review=True)                 # only 👎/flag → the review queue
    assert {f.tool_slug for f in review} == {"summarize", "draft"}
    assert all(f.verdict in ("down", "flag") for f in review)


def test_bad_verdict_rejected():
    with pytest.raises(ValueError):
        store.add_feedback("copilot", "meh")


def test_no_raw_content_column_exists():
    # the schema holds the signal + a SANITIZED question (context) — but NO document/answer body column (privacy by design)
    with store._conn() as con:
        cols = {r["name"] for r in con.execute("PRAGMA table_info(feedback)").fetchall()}
    assert cols == {"id", "tool_slug", "verdict", "note", "subject", "context", "created_at"}


def test_add_feedback_stores_context():
    store.add_feedback("copilot", "flag", "note", "ip:x", context="what is [PERSON_NAME_1]'s fee?")
    fb = store.recent_feedback(only_review=True)[0]
    assert "[PERSON_NAME_1]" in fb.context


def test_route_sanitizes_the_question_context():
    """⭐ DEC 043: the question is captured for review, but PII is tokenized BEFORE storage — never raw."""
    r = client.post("/feedback", data={"slug": "copilot", "verdict": "flag", "note": "weird",
                                        "context": "what is jane@example.com owed?"})
    assert r.status_code == 200
    fb = store.recent_feedback(only_review=True)[0]
    assert fb.context                                   # a (sanitized) question WAS captured...
    assert "jane@example.com" not in fb.context         # ...but the email was tokenized, not stored raw


def test_feedback_route_records():
    r = client.post("/feedback", data={"slug": "copilot", "verdict": "down", "note": "wrong date"})
    assert r.status_code == 200 and "logged" in r.text.lower()
    assert store.feedback_counts().get("down") == 1


def test_feedback_route_never_errors_on_bad_verdict():
    r = client.post("/feedback", data={"slug": "copilot", "verdict": "nonsense"})
    assert r.status_code == 200                                      # a feedback click never fails loudly
    assert store.feedback_counts() == {}                            # ...and nothing is stored for a bad verdict


def test_reviews_page_shows_the_queue():
    store.add_feedback("draft", "flag", "invented a clause")
    r = client.get("/reviews")
    assert r.status_code == 200
    assert "Review queue" in r.text
    assert "invented a clause" in r.text                             # the flagged note surfaces
    assert "sanitized" in r.text.lower()                             # the privacy-by-design note (DEC 043) is stated
    assert "never stored" in r.text.lower()


def test_tool_shell_shows_the_feedback_bar():
    r = client.get("/t/copilot")
    assert r.status_code == 200
    assert 'id="feedbackbar"' in r.text
    assert "Was this useful?" in r.text
