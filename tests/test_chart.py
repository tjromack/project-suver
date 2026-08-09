"""Chart your spreadsheet (Data & Analysis tool #3): bar charts computed from the rows — accurate by construction,
fully local (no model). Stub-backed (no network)."""

from __future__ import annotations

from app.pipeline import chart_table

CSV = ("Region,Product,Units,Revenue\n"
       "West,Widget,120,4800\n"
       "East,Widget,90,3600\n"
       "West,Gadget,60,5400\n"
       "East,Gadget,45,4050\n"
       "West,Gizmo,200,9000\n")


def test_charts_are_computed_by_category():
    r = chart_table(CSV)
    # picks the RICHER breakdown (Product, 3 distinct) over Region (2) — a 2-bar chart isn't informative
    assert not r.empty and r.category == "Product"
    assert len(r.charts) == 2                             # one per numeric column (Units, Revenue)
    rev = next(c for c in r.charts if c.measure == "Revenue")
    got = {b.label: b.value for b in rev.bars}
    assert got["Gadget"] == "9,450" and got["Widget"] == "8,400" and got["Gizmo"] == "9,000"  # computed per product


def test_bars_are_sorted_and_scaled():
    r = chart_table(CSV)
    rev = next(c for c in r.charts if c.measure == "Revenue")
    assert rev.bars[0].label == "Gadget" and rev.bars[0].pct == 100   # largest first (9,450), scaled to 100
    assert rev.bars[-1].pct < 100                                     # the smallest is proportionally shorter


def test_no_categorical_column_is_honest():
    r = chart_table("A,B\n1,2\n3,4\n5,6\n")               # all numeric — nothing to group by
    assert r.empty and "obvious category" in (r.empty_note or "")


def test_an_id_like_column_is_not_a_category():
    r = chart_table("id,val\nx1,10\nx2,20\nx3,30\n")      # id is all-unique (distinct == rows) → not a category
    assert r.empty


def test_not_a_table_is_honest():
    r = chart_table("just prose, not a table")
    assert r.empty and "doesn't look like a table" in (r.empty_note or "")


def test_reproducible():
    a = chart_table(CSV)
    b = chart_table(CSV)
    assert [(c.measure, [(x.label, x.value) for x in c.bars]) for c in a.charts] == \
           [(c.measure, [(x.label, x.value) for x in c.bars]) for c in b.charts]
