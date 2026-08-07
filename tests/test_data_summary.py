"""Summarize a spreadsheet (Data & Analysis tool #2): a computed profile + a grounded overview; the model narrates,
the code computes; the model sees only the sanitized profile + a sample, never the full dataset. Stub-backed."""

from __future__ import annotations

from app.pipeline import summarize_table
from app.table import parse_table

CSV = ("Region,Product,Units,Revenue\n"
       "West,Widget,120,4800\n"
       "East,Widget,90,3600\n"
       "West,Gadget,60,5400\n"
       "East,Gadget,45,4050\n"
       "West,Gizmo,200,9000\n")


def test_profile_is_computed_exactly():
    r = summarize_table(CSV)
    assert r.n_rows == 5 and r.n_cols == 4 and r.n_numeric == 2
    by = {p.name: p for p in r.profile}
    assert "total 26,850" in by["Revenue"].stats and "max 9,000" in by["Revenue"].stats   # computed sum/max
    assert "mean 103" in by["Units"].stats                                                # (120+90+60+45+200)/5
    assert "West (3)" in by["Region"].stats and "2 distinct" in by["Region"].stats        # top categories


def test_table_profile_counts_missing():
    t = parse_table("A,B\n1,x\n2,\n3,y\n")            # one missing in column B
    profs = {p.name: p for p in t.profile()}
    assert profs["B"].missing == 1 and profs["A"].kind == "number"


def test_overview_is_present():
    r = summarize_table(CSV)
    assert r.overview and "5" in r.overview            # the stub mentions the row count; anthropic narrates richly


def test_not_a_table_is_honest():
    r = summarize_table("just prose, not a table")
    assert r.empty and "doesn't look like a table" in (r.empty_note or "")


def test_model_sees_only_sanitized_profile_and_sample():
    csv = "Name,Email,Amount\nAlice,alice@example.com,100\nBob,bob@example.com,200\n"
    captured = {}
    import app.pipeline as pipeline

    real = pipeline.narrate_table

    def spy(safe_profile, safe_sample, n_rows, n_cols, provider):
        captured["seen"] = safe_profile + " " + safe_sample
        return real(safe_profile, safe_sample, n_rows, n_cols, provider)

    pipeline.narrate_table = spy
    try:
        summarize_table(csv)
    finally:
        pipeline.narrate_table = real

    seen = captured.get("seen", "")
    assert seen and "alice@example.com" not in seen and "bob@example.com" not in seen


def test_reproducible():
    a = summarize_table(CSV)
    b = summarize_table(CSV)
    assert a.overview == b.overview
    assert [(p.name, p.stats) for p in a.profile] == [(p.name, p.stats) for p in b.profile]
