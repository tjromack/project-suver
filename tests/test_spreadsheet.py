"""Ask your spreadsheet (Data & Analysis tool #1): the model PLANS, the code COMPUTES — exact numbers, cited rows,
honest abstention, and the model sees only a sanitized SAMPLE (never the full dataset). Stub-backed, no network."""

from __future__ import annotations

from app.pipeline import _execute_plan, ask_table
from app.table import parse_table

CSV = ("Region,Product,Units,Revenue\n"
       "West,Widget,120,4800\n"
       "East,Widget,90,3600\n"
       "West,Gadget,60,5400\n"
       "East,Gadget,45,4050\n")


def test_sum_is_computed_exactly():
    r = ask_table(CSV, "What is the total Revenue?")
    assert r.answered and "17,850" in r.answer          # 4800+3600+5400+4050, computed in code
    assert "Total" in r.operation and r.n_matched == 4
    assert r.columns and r.rows                          # shows the rows it used


def test_average_and_count_are_computed():
    assert "78.75" in ask_table(CSV, "average Units?").answer      # (120+90+60+45)/4
    assert ask_table(CSV, "how many rows are there?").answer == "4"


def test_filter_aggregate_is_exact():
    """A value-filter aggregate (the anthropic planner's job) computes over exactly the matching rows."""
    t = parse_table(CSV)
    plan = {"op": "aggregate", "column": "Revenue", "agg": "sum",
            "filter": {"column": "Region", "match": "eq", "value": "West"}, "answerable": True}
    answer, operation, idx, grouped = _execute_plan(t, plan)
    assert "10,200" in answer                            # West only: 4800 + 5400
    assert len(idx) == 2 and grouped is None


def test_groupby_argmax_returns_the_winning_group():
    """⭐ 'which X has the most Y' — group by a text column, aggregate a number, return the top group (exact)."""
    r = ask_table(CSV, "Which product had the highest total revenue?")
    assert r.answered and r.grouped
    # Widget: 4800+3600 = 8400 ; Gadget: 5400+4050 = 9450 → Gadget wins
    assert r.answer.startswith("Gadget") and "9,450" in r.answer


def test_groupby_all_groups_sum_correctly():
    t = parse_table(CSV)
    plan = {"op": "groupby", "group_column": "Region", "column": "Revenue", "agg": "sum",
            "top": None, "order": "desc", "filter": None, "answerable": True}
    answer, operation, idx, grouped = _execute_plan(t, plan)
    cols, rows = grouped
    got = {row[0]: row[1] for row in rows}
    assert got["West"] == "10,200" and got["East"] == "7,650"   # 4800+5400 ; 3600+4050


def test_abstains_when_unanswerable():
    r = ask_table(CSV, "What is the CEO's salary?")
    assert r.abstained and not r.answered
    assert "couldn't answer" in (r.answer or "").lower()


def test_aggregate_on_a_text_column_abstains():
    t = parse_table(CSV)
    plan = {"op": "aggregate", "column": "Region", "agg": "sum", "filter": None, "answerable": True}
    assert _execute_plan(t, plan) is None                # can't sum a text column → abstain (never fabricate)


def test_not_a_table_is_honest():
    r = ask_table("just some prose, not a table at all", "total?")
    assert r.empty and "doesn't look like a table" in (r.empty_note or "")


def test_model_sees_only_a_sanitized_sample_never_the_full_dataset():
    # a planted email in an EARLY row (in the sample) must be sanitized; a unique value in a LATE row (beyond the
    # sample) must never reach the model at all.
    big = "Name,Email,Amount\n"
    big += "Alice,alice@example.com,100\n"               # row 1 — in the sample
    big += "".join(f"User{i},user{i}@x.com,{i}\n" for i in range(2, 9))
    big += "Zoe,zoe@example.com,99999\n"                 # last row — beyond the 6-row sample
    captured = {}
    import app.pipeline as pipeline

    real = pipeline.plan_query

    def spy(safe_schema, safe_sample, safe_question, headers, numeric_headers, provider):
        captured["seen"] = " ".join([safe_schema, safe_sample, safe_question])
        return real(safe_schema, safe_sample, safe_question, headers, numeric_headers, provider)

    pipeline.plan_query = spy
    try:
        ask_table(big, "total Amount?")
    finally:
        pipeline.plan_query = real

    seen = captured.get("seen", "")
    assert "alice@example.com" not in seen               # PII in the sample was sanitized
    assert "99999" not in seen and "zoe@example.com" not in seen   # a late row never reached the model


def test_full_dataset_is_still_computed_over():
    # even though the model only saw a sample, the SUM covers every row (incl. the late 99999)
    big = "Name,Amount\n" + "".join(f"U{i},{i}\n" for i in range(1, 9)) + "Zoe,100000\n"
    r = ask_table(big, "total Amount?")
    assert r.answered and r.n_matched == 9               # 8 small rows + the late big one
    total = sum(range(1, 9)) + 100000
    assert f"{total:,}" in r.answer


def test_reproducible():
    a = ask_table(CSV, "total Revenue?")
    b = ask_table(CSV, "total Revenue?")
    assert a.answer == b.answer and a.operation == b.operation
