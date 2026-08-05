"""Constrained explanation — the model EXPLAINS a discrepancy; it never DECIDES.

ORIGIN: c:/ai/two-source-comparator/app/explain.py (the deterministic `_stub_text` + `check_coherence` guard +
`Explanation`; the live anthropic path is dropped). Suver's Compare uses the **deterministic stub** rationale —
guaranteed grounded (cites both values) and decision-free by construction, so it passes the coherence guard and
needs no per-difference model call (the model is used only for the extraction step). The guard is kept as the
enforcement of "explain, never decide": an explanation that asserts agreement or picks a winner is flagged.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app._engines.compare.compare import Discrepancy

PROMPT_VERSION = "reconcile-explain-v1"

# Phrases that would mean the model DECIDED (picked a correct source/value) — never allowed in an explanation.
_DECISION_PHRASES = (
    "should be", "is correct", "is the correct", "correct value is", "use source", "use the",
    "accept source", "accept a", "accept b", "the right value", "is right", "is wrong", "must be",
    "reconcile to", "the true value", "authoritative value is", "resolve to", "should use",
)
# Phrases that would CONTRADICT a fired rule by asserting agreement.
_AGREEMENT_PHRASES = ("no discrepancy", "the values match", "values are identical", "they agree",
                      "are the same", "no difference", "match exactly")


@dataclass(frozen=True)
class Explanation:
    field: str
    rule: str
    text: str
    model: str = "stub"
    prompt_version: str = PROMPT_VERSION
    coherent: bool = True
    issues: tuple[str, ...] = ()


def _stub_text(d: Discrepancy) -> str:
    """A grounded, decision-free rationale per rule. References the field, the rule, and both values."""
    if d.rule == "missing_on_one_side":
        present_side, present_val, absent_side = ("A", d.a, "B") if d.a is not None else ("B", d.b, "A")
        return (f"Present on document {present_side} ({present_val!r}) but absent on document {absent_side}, "
                f"so the two can't be compared on this. A reviewer decides how to reconcile it.")
    if d.rule.startswith("money"):
        return (f"The amounts differ: document A shows {d.a!r} and document B shows {d.b!r}, beyond the one-cent "
                f"tolerance. Which is authoritative is for a reviewer to decide.")
    if d.rule.startswith("date"):
        return (f"The dates differ: document A shows {d.a!r} and document B shows {d.b!r}; normalized as dates "
                f"they are not equal. A reviewer decides which holds.")
    if d.rule.startswith("number"):
        return (f"The values differ: document A shows {d.a!r} and document B shows {d.b!r}. A reviewer decides "
                f"which document is authoritative.")
    near = d.rule.endswith("near_match")
    qualifier = " The two are textually similar, which may indicate a formatting difference." if near else ""
    return (f"The text differs: document A shows {d.a!r} and document B shows {d.b!r}.{qualifier} A reviewer "
            f"decides which document is authoritative.")


def _values_referenced(text: str, d: Discrepancy) -> bool:
    low = text.lower()
    present = [v for v in (d.a, d.b) if v is not None]
    return all(str(v).lower() in low for v in present)


def check_coherence(text: str, d: Discrepancy) -> list[str]:
    """Coherence issues (empty = coherent): asserts agreement, oversteps into a decision, or isn't grounded."""
    issues: list[str] = []
    low = text.lower()
    if not text.strip():
        return ["empty explanation"]
    if not _values_referenced(text, d):
        issues.append("does not cite the concrete value(s)")
    hit = next((p for p in _AGREEMENT_PHRASES if p in low), None)
    if hit:
        issues.append(f"asserts agreement ({hit!r}) though rule {d.rule} fired")
    hit = next((p for p in _DECISION_PHRASES if re.search(rf"\b{re.escape(p)}\b", low)), None)
    if hit:
        issues.append(f"oversteps into a decision ({hit!r})")
    return issues


def explain_stub(d: Discrepancy) -> Explanation:
    """A coherence-checked, decision-free rationale for one discrepancy (deterministic — no model call)."""
    text = _stub_text(d)
    issues = check_coherence(text, d)
    return Explanation(field=d.field, rule=d.rule, text=text, coherent=not issues, issues=tuple(issues))
