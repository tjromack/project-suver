"""Typed values — the field types and their parsers.

ORIGIN: c:/ai/document-structured-extractor/app/schemas.py (the `FieldType` enum + `parse_money`/`parse_number`/
`parse_date`/`normalize_string`). How a value canonicalizes is a property of its type; these are the deterministic
parsers the confidence gate uses to decide whether an extracted value is *valid* for its type.

Suver adaptation (Trevor's 2026-08-05 Demo): consumer/report documents state money in **magnitude words**
("$29 trillion", "$1.5M"), which the engine's strict decimal parser rejected — flagging legitimate amounts.
`parse_money` here also accepts a trailing magnitude word/abbrev, so narrative amounts validate.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import Enum

MONEY_TOLERANCE = Decimal("0.01")

# Magnitude words/abbreviations for narrative money ("$29 trillion", "$1.5M", "€3 bn").
_MAGNITUDE = {
    "thousand": Decimal("1e3"), "k": Decimal("1e3"),
    "million": Decimal("1e6"), "mn": Decimal("1e6"), "m": Decimal("1e6"),
    "billion": Decimal("1e9"), "bn": Decimal("1e9"), "b": Decimal("1e9"),
    "trillion": Decimal("1e12"), "tn": Decimal("1e12"), "t": Decimal("1e12"),
}
# Searched (not anchored) so a qualifier survives — "over $29 trillion", "nearly $1 trillion" still validate.
_MONEY_MAG = re.compile(
    r"[\$€£]?\s*([\d,]+(?:\.\d+)?)\s*(thousand|million|billion|trillion|mn|bn|tn|[kmbt])\b", re.IGNORECASE
)
_MONEY_PLAIN = re.compile(r"[\$€£]?\s*\d[\d,]*(?:\.\d+)?")


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
    mag = _MONEY_MAG.search(s)                  # "over $29 trillion" / "$1.5M" — narrative amounts (Suver adaptation)
    if mag:
        value = Decimal(mag.group(1).replace(",", "")) * _MAGNITUDE[mag.group(2).lower()]
        return (-value if negative else value).quantize(Decimal("0.01"))
    stripped = _MONEY_STRIP.sub("", s)
    try:
        return (-Decimal(stripped) if negative else Decimal(stripped)).quantize(Decimal("0.01"))
    except InvalidOperation:
        pass
    plain = _MONEY_PLAIN.search(s)              # a money amount embedded in text ("about $1,296.00 total")
    if plain:
        try:
            value = Decimal(_MONEY_STRIP.sub("", plain.group(0)))
            return (-value if negative else value).quantize(Decimal("0.01"))
        except InvalidOperation:
            return None
    return None


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
