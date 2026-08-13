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


def test_no_document_content_is_stored():
    # the schema has NO column for document/answer text — feedback is signal-only (privacy by design)
    with store._conn() as con:
        cols = {r["name"] for r in con.execute("PRAGMA table_info(feedback)").fetchall()}
    assert cols == {"id", "tool_slug", "verdict", "note", "subject", "created_at"}


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
    assert "no document" in r.text.lower()                           # the privacy-by-design note is stated


def test_tool_shell_shows_the_feedback_bar():
    r = client.get("/t/copilot")
    assert r.status_code == 200
    assert 'id="feedbackbar"' in r.text
    assert "Was this useful?" in r.text
