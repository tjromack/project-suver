"""Compare — two documents side by side: rules detect the differences, the tool never picks a winner."""

from __future__ import annotations

from app.pipeline import compare_two


def _rows_by_field(outcome):
    return {r.field: r for r in outcome.rows}


def test_finds_differences_and_matches():
    a = "Vendor: Acme Corp\nAmount: $1,200.00\nStatus: Approved"
    b = "Vendor: Acme Corp\nAmount: $1,500.00\nStatus: Approved"
    r = compare_two(a, b, "facts")
    assert not r.empty and not r.blocked
    rows = _rows_by_field(r)
    assert rows["Vendor"].status == "match"
    assert rows["Amount"].status == "differ"          # $1,200 vs $1,500 (string field-set)
    assert r.n_differ >= 1 and r.n_match >= 1


def test_only_in_one_side():
    a = "Vendor: Acme Corp\nStatus: Approved"
    b = "Vendor: Acme Corp\nApprover: Jordan"
    r = compare_two(a, b, "facts")
    rows = _rows_by_field(r)
    assert rows["Status"].status == "only_a"
    assert rows["Approver"].status == "only_b"


def test_type_aware_money():
    a = "Subtotal: $1,200.00\nTotal: $1,296.00"
    b = "Subtotal: $1,200.00\nTotal: $1,300.00"
    r = compare_two(a, b, "amounts")                  # MONEY field-set → cent-tolerant comparison
    rows = _rows_by_field(r)
    assert rows["Subtotal"].status == "match"         # identical amount
    assert rows["Total"].status == "differ"
    assert rows["Total"].rule.startswith("money")


def test_the_tool_never_decides():
    """Every difference's explanation is coherence-checked and decision-free (no 'should be' / 'is correct')."""
    a = "Amount: $1,200.00"
    b = "Amount: $1,500.00"
    r = compare_two(a, b, "amounts")
    diff = next(row for row in r.rows if row.status != "match")
    low = diff.note.lower()
    for banned in ("should be", "is correct", "the right value", "accept a", "accept b"):
        assert banned not in low
    assert "reviewer" in low                          # it defers to a human


def test_no_fields_in_either_is_empty():
    r = compare_two("just some prose with no dates", "other prose also without dates", "dates")
    assert r.empty and not r.rows


def test_model_only_sees_safe_text_both_docs():
    a = "Member SSN: 123-45-6789\nAmount: $500.00"
    b = "Member SSN: 987-65-4321\nAmount: $600.00"
    r = compare_two(a, b, "amounts")
    assert r.handled_count >= 2                        # each doc's SSN handled by the boundary before the model


def test_reproducible():
    a = "Vendor: Acme\nAmount: $10.00"
    b = "Vendor: Acme\nAmount: $12.00"
    x, y = compare_two(a, b, "facts"), compare_two(a, b, "facts")
    assert [(r.field, r.status) for r in x.rows] == [(r.field, r.status) for r in y.rows]
