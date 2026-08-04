"""Vendored Summarize · Grounded-Brief core — deterministic split + cite-or-drop grounding.

ORIGIN: c:/ai/summarize-brief-generator/app/{spans,ground}.py  (re-syncable — keep changes minimal).
Pilot adaptations (documented in ../../DECISIONS.md DEC 005):
  * spans.py — verbatim.
  * ground.py — the drafter's `Candidate` (from the engine's `app.draft`) is inlined here as a lean local
    dataclass, and `ground()` takes an explicit `threshold` (the engine read it from its own `settings`).
    The grounding math — content-token support, best-span, keep-with-citation vs drop — is unchanged.

No model call lives here: the model drafts candidates (app/provider.py), grounding VERIFIES them deterministically.
"""

from app._engines.summarize.ground import (  # noqa: F401
    Candidate,
    Dropped,
    GroundedClaim,
    GroundingResult,
    best_span,
    content_tokens,
    ground,
    support,
)
from app._engines.summarize.spans import Span, by_id, split_document  # noqa: F401
