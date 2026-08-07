"""Draft — a grounded memo/brief from the document: cite-or-block, no fabrication, the model only sees safe text."""

from __future__ import annotations

from app.pipeline import draft_text

RICH = (
    "Project Atlas overview. Project Atlas is a company-wide migration to a new billing platform, intended to cut "
    "invoice errors and speed up collections. The rollout began in March and now covers all four regions. Invoice "
    "error rates fell by thirty percent in the first quarter after the cutover. Next steps: the finance team must "
    "complete the reconciliation by June 30, and regional managers should approve the updated workflow by May 15."
)


def test_grounded_memo_assembles_with_cited_sections():
    r = draft_text(RICH, "memo")
    assert not r.blocked
    assert r.sections, "a rich document should produce grounded sections"
    assert r.title and r.kind_slug == "memo"
    for s in r.sections:
        assert s.text
        assert s.citations and s.citations[0].span_id.startswith("S")
    assert r.markdown.startswith("#")  # the assembled memo


def test_every_section_is_document_supported():
    """No section text appears that isn't backed by a cited span (cite-or-block)."""
    r = draft_text(RICH, "explainer")
    for s in r.sections:
        assert s.citations, f"section {s.heading!r} was shown without a citation"


def test_unsupported_document_blocks_not_fabricates():
    # a doc with no information-dense passages → nothing salient → required sections can't ground → block.
    r = draft_text("x y z.", "memo")
    assert r.blocked and not r.sections
    assert "won't fabricate" in (r.block_message or "")


def test_model_only_sees_safe_text():
    """⭐ the invariant: what the section-drafter sees (the salient passages) carries no planted sensitive value."""
    doc = ("Michael Torres, SSN 123-45-6789, leads Project Atlas, a company-wide billing migration. "
           "The rollout began in March and covers all four regions, cutting invoice errors by thirty percent.")
    captured = {}
    import app.pipeline as pipeline

    real = pipeline.draft_section

    def spy(heading, focus, passages, provider):
        captured.setdefault("seen", []).append(" ".join(sp.text for sp in passages))
        return real(heading, focus, passages, provider)

    pipeline.draft_section = spy
    try:
        draft_text(doc, "memo")
    finally:
        pipeline.draft_section = real

    seen = " ".join(captured.get("seen", []))
    assert seen, "the drafter should have been asked to ground at least one section"
    assert "123-45-6789" not in seen


def test_unknown_kind_falls_back_to_default():
    r = draft_text(RICH, "not-a-real-kind")
    assert r.kind_slug == "memo"  # default_kind


def test_contract_review_memo_kind_drafts():
    """⭐ the legal Draft kind (adaptation ladder — a vertical is config across field-sets AND draft kinds)."""
    contract = ("This Master Services Agreement is between Acme Corp and Beta LLC, effective 2026-01-01. The term is "
                "24 months and renews automatically unless either party gives 90 days notice. Governed by Delaware "
                "law. Provider liability shall not exceed $500,000. Fees are due Net 30.")
    r = draft_text(contract, "contract-memo")
    assert not r.blocked and r.kind_slug == "contract-memo"
    headings = [s.heading for s in r.sections]
    assert "Overview" in headings and "Key Terms" in headings
    for s in r.sections:
        assert s.citations, f"section {s.heading!r} must be grounded (cite-or-block)"


def test_reproducible():
    a = draft_text(RICH, "memo")
    b = draft_text(RICH, "memo")
    assert a.title == b.title
    assert [s.heading for s in a.sections] == [s.heading for s in b.sections]
    assert [s.text for s in a.sections] == [s.text for s in b.sections]
