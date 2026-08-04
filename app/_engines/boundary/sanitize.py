"""Sanitization + the boundary decision.

ORIGIN: c:/ai/phi-pii-data-boundary/app/sanitize.py  (verbatim except the detect/policy import paths).

Given text and a policy, `sanitize()` detects sensitive spans, applies each class's action, and returns a
`BoundaryResult` with one of four **decisions**:

  * `clear`       — nothing sensitive → send as-is.
  * `redacted`    — sensitive spans replaced (tokenized / masked) → the *sanitized* text may be sent.
  * `route_local` — a never-egress class is present → nothing may leave; keep it local.
  * `block`       — a block-class (or an unresolvable span) is present → block egress, queue a human.

The decision is the **most restrictive** action present (`block` > `route_local` > `redacted` > `clear`) — the
**fail-closed** rule: if anything can't safely leave, nothing raw does. **Reversible** classes become stable
tokens re-hydrated *only* locally (`rehydrate`); **irreversible** classes are masked with no map entry.
Pure, deterministic, no LLM.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app._engines.boundary.detect import Span, detect
from app._engines.boundary.policy import EGRESS_ACTIONS, SensitivityPolicy

# Most-restrictive-wins ordering for the overall decision.
_RESTRICTIVENESS = {"clear": 0, "redacted": 1, "route_local": 2, "block": 3}
_ACTION_TO_DECISION = {"tokenize": "redacted", "redact": "redacted", "route_local": "route_local", "block": "block"}


@dataclass(frozen=True)
class BoundaryResult:
    decision: str  # clear | redacted | route_local | block
    safe_text: str | None  # text safe to send outward — None when nothing may leave (route_local | block)
    spans: list[Span]
    classes: list[str]
    token_map: dict[str, str] = field(default_factory=dict)  # ⭐ LOCAL ONLY — never crosses the boundary
    policy_id: str = ""
    policy_version: str = ""

    @property
    def may_send(self) -> bool:
        return self.decision in ("clear", "redacted")

    @property
    def needs_review(self) -> bool:
        return self.decision == "block"

    @property
    def local_only(self) -> bool:
        return self.decision == "route_local"


def _apply(text: str, spans: list[Span], actions: dict[str, str]) -> tuple[str, dict[str, str]]:
    """Replace tokenize/redact spans; return (safe_text, local token_map). Tokens numbered per type by appearance."""
    counter: dict[str, int] = {}
    replacement: dict[tuple[int, int], str] = {}
    token_map: dict[str, str] = {}
    for s in sorted(spans, key=lambda s: s.start):  # ascending → stable token numbering
        act = actions[s.type]
        if act == "tokenize":
            counter[s.type] = counter.get(s.type, 0) + 1
            token = f"[{s.type.upper()}_{counter[s.type]}]"
            replacement[(s.start, s.end)] = token
            token_map[token] = text[s.start : s.end]
        elif act == "redact":
            replacement[(s.start, s.end)] = f"[{s.type.upper()}]"
        else:  # defensive — route_local/block are handled before we get here; fail closed to a mask
            replacement[(s.start, s.end)] = "[REDACTED]"
    out = text
    for s in sorted(spans, key=lambda s: s.start, reverse=True):  # descending → offsets stay valid
        out = out[: s.start] + replacement[(s.start, s.end)] + out[s.end :]
    return out, token_map


def sanitize(text: str, policy: SensitivityPolicy) -> BoundaryResult:
    """Detect → decide → sanitize. The heart of the boundary. Deterministic, fail-closed."""
    spans = detect(text, policy)
    classes = sorted({s.type for s in spans})
    if not spans:
        return BoundaryResult("clear", text, [], [], {}, policy.id, policy.version)

    # Resolve each span's action; an unknown class falls to the fail-closed default (block/route_local).
    actions: dict[str, str] = {}
    for s in spans:
        cls = policy.get(s.type)
        actions[s.type] = cls.resolved_action if cls else policy.default_action

    # Overall decision = the most restrictive action present.
    decision = "clear"
    for act in actions.values():
        d = _ACTION_TO_DECISION.get(act, policy.default_action)
        d = _ACTION_TO_DECISION.get(d, d)  # normalize a default_action into a decision label
        if _RESTRICTIVENESS[d] > _RESTRICTIVENESS[decision]:
            decision = d

    if decision in ("route_local", "block"):
        # Nothing may leave — do not emit sanitized text; the caller keeps it local / waits for a human.
        return BoundaryResult(decision, None, spans, classes, {}, policy.id, policy.version)

    # decision == "redacted": every span is an egress action (tokenize/redact) → build the safe text.
    assert all(actions[s.type] in EGRESS_ACTIONS for s in spans)
    safe_text, token_map = _apply(text, spans, actions)
    return BoundaryResult("redacted", safe_text, spans, classes, token_map, policy.id, policy.version)


def rehydrate(text: str, token_map: dict[str, str]) -> str:
    """⭐ LOCAL-ONLY: restore original values from tokens in a model's response. Never call this on the egress
    path — the token map lives only inside the local trust zone. Irreversibly-redacted classes never re-hydrate."""
    for token, original in token_map.items():
        text = text.replace(token, original)
    return text
