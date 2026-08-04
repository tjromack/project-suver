"""The detector engine — deterministic, typed, recall-first.

ORIGIN: c:/ai/phi-pii-data-boundary/app/detect.py  (verbatim except the policy import path).

Each detector finds spans of one sensitive class using regex / checksum / gazetteer — **no model is ever
involved**. Detection favors **recall over precision**: a safe over-detection (redacting a non-secret) beats a
miss (a leak). `detect(text, policy)` runs the detectors named by the active policy's classes, tags each span
with its class, and resolves overlaps (higher-risk class wins, then the wider span).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app._engines.boundary.policy import SensitivityPolicy


class DetectError(ValueError):
    """A policy names a class whose detector isn't registered."""


@dataclass(frozen=True)
class Span:
    """A detected sensitive span: the class name + the [start, end) offsets in the text."""

    type: str
    start: int
    end: int

    @property
    def length(self) -> int:
        return self.end - self.start


# --- individual detectors: text -> list[(start, end)] ------------------------------------------------

_SSN = re.compile(r"\b\d{3}[- ]\d{2}[- ]\d{4}\b")
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
_PHONE = re.compile(r"(?<!\d)(?:\+?1[-. ]?)?\(?\d{3}\)?[-. ]\d{3}[-. ]\d{4}(?!\d)")
_DATE = re.compile(
    r"\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4}"
    r"|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4})\b"
)
_MRN = re.compile(r"\bMRN[:#]?\s*([A-Za-z0-9\-]{4,})\b", re.IGNORECASE)
_CC_CANDIDATE = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?<=\d)")
_ADDRESS = re.compile(
    r"\b\d{1,6}\s+(?:[A-Z][a-zA-Z]+\.?\s+){1,3}"
    r"(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Dr|Court|Ct|Way|Place|Pl)\b\.?",
)

# A modest first-name gazetteer — deterministic; extend per policy/domain. Recall-limited by design.
_FIRST_NAMES = {
    "james", "john", "robert", "michael", "william", "david", "richard", "joseph", "thomas", "daniel",
    "mary", "patricia", "jennifer", "linda", "elizabeth", "barbara", "susan", "jessica", "sarah", "karen",
    "jane", "emily", "laura", "anna", "grace", "peter", "paul", "mark", "steven", "andrew", "kevin", "brian",
}
_WORD = re.compile(r"\b[A-Z][a-z]+\b")


def _spans(pattern: re.Pattern, text: str, group: int = 0) -> list[tuple[int, int]]:
    return [(m.start(group), m.end(group)) for m in pattern.finditer(text)]


def _detect_ssn(text: str) -> list[tuple[int, int]]:
    return _spans(_SSN, text)


def _detect_email(text: str) -> list[tuple[int, int]]:
    return _spans(_EMAIL, text)


def _detect_phone(text: str) -> list[tuple[int, int]]:
    return _spans(_PHONE, text)


def _detect_dob(text: str) -> list[tuple[int, int]]:
    return _spans(_DATE, text)


def _detect_mrn(text: str) -> list[tuple[int, int]]:
    # Flag the id following the MRN marker (group 1), not the marker word itself.
    return _spans(_MRN, text, group=1)


def _luhn_ok(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = ord(ch) - 48
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


def _detect_credit_card(text: str) -> list[tuple[int, int]]:
    # Recall-first: flag any 13-19 digit candidate. (Luhn is available to callers/eval as a precision signal,
    # but a candidate that FAILS Luhn is still flagged — a typo'd card number is still sensitive.)
    out = []
    for m in _CC_CANDIDATE.finditer(text):
        digits = re.sub(r"\D", "", m.group())
        if 13 <= len(digits) <= 19:
            out.append((m.start(), m.end()))
    return out


def _detect_address(text: str) -> list[tuple[int, int]]:
    return _spans(_ADDRESS, text)


def _detect_person_name(text: str) -> list[tuple[int, int]]:
    # Anchor on a gazetteer first name, then extend over an immediately-following capitalized surname token.
    # Scanning tokens (not a greedy bigram regex) avoids a preceding capitalized word — "Patient Jane Roe" —
    # swallowing the first name and dropping the surname. Recall-limited by the gazetteer, but no adjacency miss.
    words = [(m.group(), m.start(), m.end()) for m in _WORD.finditer(text)]
    out = []
    for i, (w, s, e) in enumerate(words):
        if w.lower() not in _FIRST_NAMES:
            continue
        end = e
        if i + 1 < len(words):
            _nw, ns, ne = words[i + 1]
            between = text[e:ns]
            if between and between.strip() == "":  # only whitespace between first name and next Cap word
                end = ne
        out.append((s, end))
    return out


DETECTORS = {
    "ssn": _detect_ssn,
    "credit_card": _detect_credit_card,
    "mrn": _detect_mrn,
    "email": _detect_email,
    "phone": _detect_phone,
    "dob": _detect_dob,
    "person_name": _detect_person_name,
    "address": _detect_address,
}


def _resolve_overlaps(spans: list[Span], priority: dict[str, int]) -> list[Span]:
    """Keep non-overlapping spans; on overlap prefer the higher-risk class (lower priority index), then the wider
    span, then the earlier start — all deterministic."""
    ordered = sorted(spans, key=lambda s: (priority.get(s.type, 999), -s.length, s.start))
    kept: list[Span] = []
    for sp in ordered:
        if any(not (sp.end <= k.start or sp.start >= k.end) for k in kept):
            continue  # overlaps something already kept (which is higher/equal priority) → drop
        kept.append(sp)
    return sorted(kept, key=lambda s: s.start)


def detect(text: str, policy: SensitivityPolicy) -> list[Span]:
    """Run every detector named by the policy's classes; return resolved, position-ordered spans."""
    priority = {c.name: i for i, c in enumerate(policy.classes)}
    found: list[Span] = []
    for cls in policy.classes:
        fn = DETECTORS.get(cls.detector)
        if fn is None:
            raise DetectError(f"policy class '{cls.name}' names unknown detector '{cls.detector}'")
        for start, end in fn(text):
            if end > start:
                found.append(Span(type=cls.name, start=start, end=end))
    return _resolve_overlaps(found, priority)
