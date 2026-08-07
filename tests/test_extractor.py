"""Extractor — typed-list extraction into a table; confidence = min(validation, model); flag the uncertain."""

from __future__ import annotations

from app._engines.extract import FieldType, all_fieldsets, get_fieldset, parse_money, score_item
from app.pipeline import extract_fields, extract_paste


def test_narrative_money_validates_not_flagged():
    """Report/consumer docs state money as magnitude words ('$29 trillion') — they must validate, not flag."""
    assert parse_money("$29 trillion") is not None
    assert parse_money("$1.5M") is not None
    assert parse_money("1,200 billion") is not None
    assert parse_money("not money") is None
    it = score_item("Market size", "$29 trillion", FieldType.MONEY, False)
    assert it.valid and it.status == "ok"


def test_vertical_fieldsets_are_available():
    """⭐ the adaptation ladder — a new vertical is config (a field-set), not a new engine. Legal-led."""
    slugs = [fs.slug for fs in all_fieldsets()]
    for slug in ("contract", "invoice", "resume"):
        assert slug in slugs and get_fieldset(slug) is not None
    assert "legal" in get_fieldset("contract").label.lower()


def test_contract_terms_extracts_into_a_table():
    doc = ("Master Services Agreement\nParties: Acme Corp and Beta LLC\nEffective date: 2026-01-01\n"
           "Term: 24 months\nGoverning law: Delaware\nTermination notice: 60 days\nLiability cap: $500,000\n")
    r = extract_paste(doc, "contract")               # stub reads the label:value lines
    labels = [it.label.lower() for it in r.items]
    assert any("part" in l for l in labels) and any("govern" in l for l in labels)
    assert any("$500,000" == it.value for it in r.items)


def test_confidence_gate_flags_invalid_and_uncertain():
    """⭐ the trust mechanism: a value that fails type-validation, or one the model flags, is flagged (not trusted)."""
    ok = score_item("Deadline", "2026-05-10", FieldType.DATE, False)
    assert ok.valid and ok.status == "ok" and ok.confidence >= 0.75

    invalid = score_item("Deadline", "next Friday", FieldType.DATE, False)   # not ISO → validation fails
    assert not invalid.valid and invalid.status == "flagged"

    unsure = score_item("Total", "1200.00", FieldType.MONEY, True)            # model-flagged → min(1.0,0.5)=0.5
    assert unsure.valid and unsure.status == "flagged"  # valid type, but low model confidence → review


def test_key_facts_extracts_labeled_values():
    doc = "Project: Atlas\nStatus: On schedule\nOwner: Finance team\nRegion: All four"
    r = extract_fields(doc, "facts")
    assert not r.empty and not r.blocked
    labels = [it.label for it in r.items]
    assert "Project" in labels and "Status" in labels
    for it in r.items:
        assert it.status == "ok"


def test_dates_extracts_iso_dates():
    doc = "Kickoff: 2026-03-01\nLaunch deadline: 2026-05-10"
    r = extract_fields(doc, "dates")
    assert not r.empty
    assert any(it.value == "2026-05-10" for it in r.items)
    for it in r.items:
        assert it.field_type == "date" and it.status == "ok"


def test_amounts_extracts_money():
    doc = "Subtotal: $1,200.00\nTax: $96.00\nTotal: $1,296.00"
    r = extract_fields(doc, "amounts")
    assert not r.empty
    for it in r.items:
        assert it.field_type == "money" and it.status == "ok"


def test_people_extracts_contacts_rehydrated_from_tokens():
    doc = "Contact Michael Torres at michael.torres@example.com or (415) 555-0148."
    r = extract_fields(doc, "people")
    assert not r.empty
    joined = " ".join(it.value for it in r.items)
    # the email/phone/name were sanitized to tokens, extracted, and re-hydrated locally in the table
    assert "michael.torres@example.com" in joined or "Michael Torres" in joined


def test_no_matches_is_empty_not_fabricated():
    r = extract_fields("The sky is blue and the grass is green.", "dates")
    assert r.empty and not r.items
    assert "No dates" in (r.empty_note or "")


def test_model_only_sees_safe_text():
    doc = "Member SSN 123-45-6789. Total due: $500.00 on 2026-06-01."
    captured = {}
    import app.pipeline as pipeline

    real = pipeline.extract_items

    def spy(safe_text, fs, provider):
        captured["seen"] = safe_text
        return real(safe_text, fs, provider)

    pipeline.extract_items = spy
    try:
        extract_fields(doc, "amounts")
    finally:
        pipeline.extract_items = real

    assert "123-45-6789" not in captured["seen"]


def test_parse_items_salvages_truncated_json():
    """A model that overflows its output limit returns a truncated array — salvage the complete objects."""
    from app.provider import _parse_items
    assert len(_parse_items('[{"label":"A","value":"1"},{"label":"B","value":"2"}]')) == 2
    truncated = '[\n {"label":"A","value":"1"},\n {"label":"B","value":"2"},\n {"label":"C","valu'
    assert len(_parse_items(truncated)) == 2   # A and B recovered; the half-written C dropped


def test_unknown_fieldset_falls_back_to_default():
    r = extract_fields("Project: Atlas", "not-a-real-fieldset")
    assert r.fieldset_slug == "facts"  # default_fieldset


def test_reproducible():
    doc = "Subtotal: $1,200.00\nTotal: $1,296.00"
    a = extract_fields(doc, "amounts")
    b = extract_fields(doc, "amounts")
    assert [(it.label, it.value) for it in a.items] == [(it.label, it.value) for it in b.items]
