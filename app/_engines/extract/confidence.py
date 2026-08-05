"""The confidence gate — `confidence = min(validation, model)`; route/flag the uncertain, never guess.

ORIGIN: c:/ai/document-structured-extractor/app/confidence.py (the trust mechanism), slimmed to a **per-item**
score for typed-list extraction: validation is the deterministic *type-validity* of the extracted value (does it
parse as the field's type?), the model signal is the model's own uncertainty flag, and the confidence is the
**min** of the two — either can pull an item down. An item below the threshold, or one that fails type-validation,
is **flagged for review**, never silently kept as trusted (CLAUDE.md guardrail: confidence is anchored in
validation, not the model's self-report).
"""

from __future__ import annotations

from dataclasses import dataclass

from app._engines.extract.types import FieldType, valid_for_type

# Score anchors (mirroring the engine's per-field confidence anchors).
_VALID = 1.0            # value parses as its type
_INVALID = 0.3          # value does NOT parse as its type (a rule-implicated field, in engine terms)
_MODEL_OK = 0.95        # the model did not flag this item
_MODEL_FLAGGED = 0.5    # the model flagged this item uncertain
DEFAULT_THRESHOLD = 0.75


@dataclass(frozen=True)
class ExtractedItem:
    label: str
    value: str          # re-hydrated for display
    field_type: str     # the FieldType value
    confidence: float
    valid: bool
    status: str         # "ok" | "flagged"


def score_item(label: str, value: str, field_type: FieldType, model_uncertain: bool,
               *, threshold: float = DEFAULT_THRESHOLD) -> ExtractedItem:
    """Confidence = min(validation, model). Below threshold OR type-invalid → flagged (kept, but for review)."""
    valid = valid_for_type(value, field_type)
    validation_score = _VALID if valid else _INVALID
    model_score = _MODEL_FLAGGED if model_uncertain else _MODEL_OK
    confidence = round(min(validation_score, model_score), 2)
    status = "ok" if (valid and confidence >= threshold) else "flagged"
    return ExtractedItem(label=label, value=value, field_type=field_type.value,
                         confidence=confidence, valid=valid, status=status)
