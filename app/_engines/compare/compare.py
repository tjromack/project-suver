"""Deterministic, type-aware comparison — the core of Reconcile.

ORIGIN: c:/ai/two-source-comparator/app/compare.py (verbatim except the schema import path). Two field dicts on a
common schema go in; a list of **discrepancies** comes out. Detection is *rules*, never an LLM diff: each field is
compared by a rule chosen by its **type**, and every discrepancy records the rule that fired plus both values, so
it is auditable. Nothing here decides which source is right — that's the human's job. This only *detects*.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher

from app._engines.compare.schema import CompareField, CompareSchema, FieldType

# A money difference at or below this many cents is treated as agreement (rounding / representation).
MONEY_TOLERANCE_CENTS = 1
# Numbers within this absolute epsilon are equal.
NUMBER_EPSILON = 1e-9
# A normalized string difference with a fuzzy ratio at/above this is a *near* match (low severity).
STRING_NEAR_RATIO = 0.90


@dataclass(frozen=True)
class Discrepancy:
    field: str
    a: object          # value on source A (None = absent)
    b: object          # value on source B (None = absent)
    rule: str          # the rule that fired — auditable
    severity: str      # "high" | "medium" | "low"

    def to_dict(self) -> dict:
        return {"field": self.field, "a": self.a, "b": self.b, "rule": self.rule, "severity": self.severity}


# --- value normalizers (deterministic) ----------------------------------------------------

def parse_money_cents(value: object) -> int | None:
    """"$1,420.50" / "1420.5" / 1420.5 → 142050 cents. None if not parseable as money."""
    if value is None:
        return None
    s = re.sub(r"[^\d.\-]", "", str(value))          # drop $ , spaces and any currency symbol
    if s in ("", "-", ".", "-."):
        return None
    try:
        return int((Decimal(s) * 100).to_integral_value(rounding="ROUND_HALF_UP"))
    except (InvalidOperation, ValueError):
        return None


_DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d %b %Y", "%b %d, %Y", "%B %d, %Y")


def parse_date(value: object) -> date | None:
    from datetime import datetime
    if value is None:
        return None
    s = str(value).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def normalize_string(value: object) -> str:
    return re.sub(r"\s+", " ", str(value).strip()).casefold()


def parse_number(value: object) -> float | None:
    if value is None:
        return None
    s = re.sub(r"[^\d.\-]", "", str(value))
    try:
        return float(s) if s not in ("", "-", ".", "-.") else None
    except ValueError:
        return None


# --- per-field comparison -----------------------------------------------------------------

def _compare_field(f: CompareField, a: object, b: object) -> Discrepancy | None:
    a_present, b_present = a is not None, b is not None

    # Presence first — you can't compare a value against nothing.
    if a_present != b_present:
        return Discrepancy(f.name, a, b, rule="missing_on_one_side", severity="high")
    if not a_present and not b_present:
        return None                                   # both absent → the sources agree

    if f.type == FieldType.MONEY:
        ca, cb = parse_money_cents(a), parse_money_cents(b)
        if ca is None or cb is None:                  # unparseable → fall back to a literal string check
            return None if normalize_string(a) == normalize_string(b) else \
                Discrepancy(f.name, a, b, rule="money.unparseable_mismatch", severity="high")
        if abs(ca - cb) <= MONEY_TOLERANCE_CENTS:
            return None                               # within tolerance → agreement (no false positive)
        return Discrepancy(f.name, a, b, rule="money.value_mismatch", severity="high")

    if f.type == FieldType.DATE:
        da, db = parse_date(a), parse_date(b)
        if da is not None and db is not None:
            return None if da == db else Discrepancy(f.name, a, b, rule="date.mismatch", severity="medium")
        # one/both unparseable → literal compare so a real difference still surfaces
        return None if normalize_string(a) == normalize_string(b) else \
            Discrepancy(f.name, a, b, rule="date.mismatch", severity="medium")

    if f.type == FieldType.NUMBER:
        na, nb = parse_number(a), parse_number(b)
        if na is None or nb is None:
            return None if normalize_string(a) == normalize_string(b) else \
                Discrepancy(f.name, a, b, rule="number.mismatch", severity="medium")
        return None if abs(na - nb) <= NUMBER_EPSILON else \
            Discrepancy(f.name, a, b, rule="number.mismatch", severity="medium")

    # STRING (default): normalize, then a fuzzy ratio modulates severity.
    na, nb = normalize_string(a), normalize_string(b)
    if na == nb:
        return None
    ratio = SequenceMatcher(None, na, nb).ratio()
    severity = "low" if ratio >= STRING_NEAR_RATIO else "medium"
    rule = "string.near_match" if ratio >= STRING_NEAR_RATIO else "string.mismatch"
    return Discrepancy(f.name, a, b, rule=rule, severity=severity)


def compare(schema: CompareSchema, a: dict, b: dict) -> list[Discrepancy]:
    """Compare two field dicts on `schema` → the discrepancy list (empty = the sources agree)."""
    out: list[Discrepancy] = []
    for f in schema.fields:
        d = _compare_field(f, a.get(f.name), b.get(f.name))
        if d is not None:
            out.append(d)
    return out
