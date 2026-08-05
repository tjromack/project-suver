"""Typed values — the field types and their parsers.

ORIGIN: c:/ai/document-structured-extractor/app/schemas.py (the `FieldType` enum + `parse_money`/`parse_number`/
`parse_date`/`normalize_string`), verbatim. How a value canonicalizes is a property of its type; these are the
deterministic parsers the confidence gate uses to decide whether an extracted value is *valid* for its type.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import Enum

MONEY_TOLERANCE = Decimal("0.01")


class FieldType(str, Enum):
    STRING = "string"
    DATE = "date"
    MONEY = "money"
    NUMBER = "number"


_MONEY_STRIP = re.compile(r"[,$\s]")


def parse_money(raw: object) -> Decimal | None:
    """'$1,234.50' / '(45.00)' / 45 / '45.00' -> Decimal('1234.50') etc.; None if unparseable."""
    if raw is None:
        return None
    if isinstance(raw, Decimal):
        return raw.quantize(Decimal("0.01"))
    if isinstance(raw, (int, float)):
        return Decimal(str(raw)).quantize(Decimal("0.01"))
    s = str(raw).strip()
    if not s:
        return None
    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative, s = True, s[1:-1]
    s = _MONEY_STRIP.sub("", s)
    try:
        value = Decimal(s)
    except InvalidOperation:
        return None
    if negative:
        value = -value
    return value.quantize(Decimal("0.01"))


def parse_number(raw: object) -> Decimal | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float, Decimal)):
        return Decimal(str(raw))
    s = _MONEY_STRIP.sub("", str(raw).strip())
    if not s:
        return None
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def parse_date(raw: object) -> date | None:
    """Strict ISO `YYYY-MM-DD`. Returns None if absent or not a real calendar date."""
    if raw is None:
        return None
    if isinstance(raw, date):
        return raw
    s = str(raw).strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def normalize_string(raw: object) -> str | None:
    if raw is None:
        return None
    s = re.sub(r"\s+", " ", str(raw)).strip()
    return s or None


def valid_for_type(value: object, field_type: FieldType) -> bool:
    """Does `value` parse as its declared type? The deterministic half of the confidence gate."""
    if field_type == FieldType.MONEY:
        return parse_money(value) is not None
    if field_type == FieldType.NUMBER:
        return parse_number(value) is not None
    if field_type == FieldType.DATE:
        return parse_date(value) is not None
    return normalize_string(value) is not None
