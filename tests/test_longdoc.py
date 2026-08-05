"""Long-document handling — window a doc and map-reduce, so the WHOLE document is covered, not just its start."""

from __future__ import annotations

import pytest

import app.config as config
from app._engines.summarize import split_document
from app.pipeline import _span_windows, _text_windows, extract_fields, summarize_text


@pytest.fixture
def tiny_window():
    """Force a tiny per-call window so a small test doc still exercises multi-window map-reduce."""
    orig = config.settings.max_draft_chars
    object.__setattr__(config.settings, "max_draft_chars", 120)
    try:
        yield
    finally:
        object.__setattr__(config.settings, "max_draft_chars", orig)


def test_text_windows_split():
    assert _text_windows("short", 100) == ["short"]
    ws = _text_windows("x" * 350, 100)
    assert len(ws) >= 3 and "".join(ws) == "x" * 350   # complete coverage, no loss


def test_span_windows_split():
    spans = split_document("One sentence here now. Two sentences here now. Three sentences here now. Four now here.")
    assert len(_span_windows(spans, 30)) >= 2
    assert len(_span_windows(spans, 10_000)) == 1        # a short doc is a single window


def test_summarize_covers_the_last_window(tiny_window):
    doc = ("Alpha event: the northern fleet launched its campaign in 1501. "
           "Beta event: the southern fleet regrouped near the coast in 1502. "
           "Gamma event: the decisive siege finally concluded the war in 1503.")
    r = summarize_text(doc)
    assert r.note and "section" in r.note                # multi-window note, not "first N chars"
    joined = " ".join(c.text for c in r.claims)
    assert "1503" in joined                              # content from the LAST window is covered


def test_extractor_covers_the_last_window(tiny_window):
    doc = ("Kickoff is on 2026-01-05. Filler text about the project timeline and plan goes here to pad length. "
           "Midpoint review on 2026-02-10. More filler about scheduling and staffing to extend the document. "
           "The final hard deadline is 2026-09-30.")
    r = extract_fields(doc, "dates")
    vals = [it.value for it in r.items]
    assert "2026-09-30" in vals                          # a date from the last window is caught


def test_short_doc_is_single_window_unchanged(tiny_window):
    # a doc under the (tiny) budget still summarizes with no long-doc note
    r = summarize_text("A single short sentence about the fleet in 1500.")
    assert r.note is None
