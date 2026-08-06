"""Phase 4 — cite-or-drop grounding in the pipeline: ⭐ no claim is shown without a source span.

The stub drafter is extractive, so its candidates ground trivially (kept, cited). A fabricated claim — one whose
content tokens the source never used — must be withheld. All deterministic; no network.
"""

from __future__ import annotations

from app._engines.summarize import Candidate, ground, split_document
from app.config import settings
from app.pipeline import summarize_text

DOC = (
    "The Q3 network migration completed on schedule. Latency dropped by 40 percent after the cutover. "
    "The team retired three legacy load balancers. A follow-up audit is planned for Q4. "
    "Customer-reported incidents fell to their lowest level in two years."
)


def test_stub_summary_is_all_cited():
    res = summarize_text(DOC)  # stub
    assert not res.blocked
    assert res.claims, "the stub should produce at least one cited key-point"
    # ⭐ every displayed claim carries a source-span citation
    for c in res.claims:
        assert c.span_id and c.span_id.startswith("S")
        assert c.span_text
        assert c.support >= settings.ground_threshold


def test_fabricated_claim_is_withheld():
    """A claim with tokens absent from the source is dropped by grounding, never shown as trusted."""
    spans = split_document(DOC)
    fabricated = Candidate(
        section_key="key_points",
        text="The company announced a merger with a Brazilian telecom for nine billion dollars.",
    )
    extractive = Candidate(section_key="key_points", text="Latency dropped by 40 percent after the cutover.")
    result = ground([fabricated, extractive], spans, settings.ground_threshold)
    kept_texts = [k.text for k in result.kept]
    dropped_texts = [d.text for d in result.dropped]
    assert "Latency dropped by 40 percent after the cutover." in kept_texts
    assert any("merger" in t for t in dropped_texts)


def test_multi_sentence_fact_grounds_via_the_span_window():
    """⭐ 08-06 Demo tuning: a true lead fact whose tokens split across two ADJACENT sentences must ground (over the
    contiguous window) — not be over-withheld by single-span support — while a fabrication still stays withheld."""
    doc = ("The Byzantine navy was a direct continuation of its Roman predecessor. "
           "It remained active from 330 to 1453 and was headquartered at Constantinople.")
    spans = split_document(doc)
    # this claim's tokens are split across the two sentences ("continuation" + "330…1453…Constantinople")
    split_fact = Candidate(section_key="key_points",
                           text="The navy was a continuation of Rome, active from 330 to 1453 at Constantinople.")
    fabricated = Candidate(section_key="key_points",
                           text="The navy operated forty aircraft carriers in the Pacific in 1990.")
    result = ground([split_fact, fabricated], spans, settings.ground_threshold)
    kept = [k.text for k in result.kept]
    dropped = [d.text for d in result.dropped]
    assert any("continuation of Rome" in t for t in kept), "a two-sentence lead fact should ground via the window"
    assert any("aircraft carriers" in t for t in dropped), "a fabrication must still be withheld"


def test_pipeline_is_reproducible():
    a = summarize_text(DOC)
    b = summarize_text(DOC)
    assert [c.text for c in a.claims] == [c.text for c in b.claims]
    assert [c.span_id for c in a.claims] == [c.span_id for c in b.claims]


def test_clean_document_has_no_handled_items():
    res = summarize_text(DOC)  # no PII planted
    assert res.handled_count == 0
    assert res.decision == "clear"
    assert res.handled_note == "No sensitive items detected"
