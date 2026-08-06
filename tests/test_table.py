"""The table parser (Data & Analysis) — CSV/TSV/pasted table → typed TableData. Stub-backed, no network."""

from __future__ import annotations

from app.table import parse_table, to_number

CSV = "Region,Product,Units,Revenue\nWest,Widget,120,$4,800\nEast,Widget,90,$3,600\nWest,Gadget,60,$5,400\n"


def test_parses_headers_rows_and_numeric_columns():
    t = parse_table(CSV)
    assert t is not None
    assert t.headers == ["Region", "Product", "Units", "Revenue"]
    assert t.n_rows == 3
    assert 2 in t.numeric_cols and 3 in t.numeric_cols     # Units, Revenue are numeric ($4,800 parses)
    assert 0 not in t.numeric_cols                          # Region is text


def test_to_number_tolerates_money_and_parens():
    assert to_number("$4,800") == 4800.0
    assert to_number("1,234.5") == 1234.5
    assert to_number("(500)") == -500.0                    # parenthesised negative
    assert to_number("42%") == 42.0
    assert to_number("west") is None


def test_col_index_exact_then_fuzzy():
    t = parse_table(CSV)
    assert t.col_index("Revenue") == 3
    assert t.col_index("revenue") == 3                     # case-insensitive
    assert t.col_index("units sold") == 2                  # fuzzy contains ("units")
    assert t.col_index("nope") == -1


def test_tsv_is_parsed():
    t = parse_table("a\tb\n1\t2\n3\t4")
    assert t is not None and t.headers == ["a", "b"] and t.n_rows == 2


def test_non_table_is_none():
    assert parse_table("just a sentence, no rows here") is None
    assert parse_table("") is None
