"""Learning platform (platform #4, DEC 044) — Flashcards + Quiz. A document → study material, with the SAME
cite-or-drop discipline as Summarize: the model drafts items, the deterministic grounding gate verifies each item's
answer against a source span, and an ungroundable item is dropped (never invented). Stub-backed / offline."""

from __future__ import annotations

import app.pipeline as pipeline
from app.config import settings
from app.main import app
from app.pipeline import flashcards_text, quiz_text
from app.tools import by_platform, get
from fastapi.testclient import TestClient

client = TestClient(app)

WC = ("The water cycle describes how water moves through Earth's environment. Evaporation turns liquid water into "
      "vapor using heat from the sun. Condensation forms clouds as water vapor cools and turns back into tiny "
      "droplets. Precipitation is water that falls to the ground as rain, snow, or hail when the droplets grow heavy. "
      "Collection returns the water to oceans, lakes, and rivers, where the cycle begins again.")


def test_flashcards_are_grounded():
    r = flashcards_text(WC)                                   # stub: each answer IS a span → grounds
    assert r.cards, "expected some flashcards from a factual paragraph"
    assert all(c.support >= settings.ground_threshold for c in r.cards)   # every kept card cites a span
    assert all(c.span_id and c.span_text for c in r.cards)
    assert not r.blocked


def test_flashcards_drop_ungroundable_answers(monkeypatch):
    """⭐ cite-or-drop: a card whose answer isn't supported by the document is dropped, never shown."""
    monkeypatch.setattr(pipeline, "make_flashcards", lambda safe, spans, provider, *, k: [
        {"q": "Q1", "a": "Evaporation turns liquid water into vapor using heat from the sun."},  # grounds
        {"q": "Q2", "a": "zzz nonsense unrelated words xyz"},                                    # cannot ground
    ])
    r = flashcards_text(WC)
    assert len(r.cards) == 1 and r.withheld_count == 1
    assert "Evaporation" in r.cards[0].answer


def test_flashcards_model_sees_only_sanitized_text(monkeypatch):
    seen = {}

    def spy(safe, spans, provider, *, k):
        seen["text"] = safe
        return []

    monkeypatch.setattr(pipeline, "make_flashcards", spy)
    flashcards_text("Contact jane@example.com about evaporation and the water cycle.")
    assert "jane@example.com" not in seen["text"]             # the email was tokenized before the model step


def test_quiz_correct_answer_is_grounded_and_placed():
    r = quiz_text(WC)                                         # stub: correct IS a span; 3 fixed distractors
    assert r.questions
    for q in r.questions:
        assert len(q.options) == 4                            # correct + 3 distractors
        assert 0 <= q.correct_index < len(q.options)
        assert q.options[q.correct_index] == q.span_text      # the correct option is the cited span
        assert q.support >= settings.ground_threshold


def test_quiz_drops_ungroundable_correct(monkeypatch):
    monkeypatch.setattr(pipeline, "make_quiz", lambda safe, spans, provider, *, k: [
        {"q": "Q1", "correct": "Evaporation turns liquid water into vapor using heat from the sun.",
         "distractors": ["a", "b", "c"]},                     # grounds
        {"q": "Q2", "correct": "zzz nonsense xyz", "distractors": ["a", "b", "c"]},   # cannot ground
    ])
    r = quiz_text(WC)
    assert len(r.questions) == 1 and r.withheld_count == 1


def test_learning_platform_registered():
    for slug, name in (("flashcards", "Flashcards"), ("quiz", "Quiz me")):
        t = get(slug)
        assert t is not None and t.is_live and t.platform == "Learning"
    platforms = dict(by_platform())
    assert "Learning" in platforms
    assert {t.slug for t in platforms["Learning"]} == {"flashcards", "quiz"}


def test_hub_shows_the_learning_platform():
    r = client.get("/")
    assert r.status_code == 200
    assert "Learning platform" in r.text
    assert "Flashcards" in r.text and "Quiz me" in r.text
    # a fourth platform renders after the first three (stable order; "&" is HTML-escaped in the heading)
    assert r.text.index("Analysis platform") < r.text.index("Learning platform")


def test_routes_render():
    a = client.post("/t/flashcards/run", data={"paste": WC})
    assert a.status_code == 200 and "boundary:" in a.text
    b = client.post("/t/quiz/run", data={"paste": WC})
    assert b.status_code == 200 and "Show answer" in b.text


def test_learning_outputs_are_downloadable(monkeypatch):
    """DEC 045: a usable deck, not just readable — a CSV download (data + button) for flashcards and quiz."""
    a = client.post("/t/flashcards/run", data={"paste": WC})
    assert "Download deck (.csv)" in a.text and 'id="fcdata"' in a.text
    b = client.post("/t/quiz/run", data={"paste": WC})
    assert "Download (.csv)" in b.text and 'id="qzdata"' in b.text
