"""Grounding — the core: every claim cites a source span, or it is dropped. Deterministic.

ORIGIN: c:/ai/summarize-brief-generator/app/ground.py  (grounding math verbatim; two pilot adaptations).

A brief claim is trustworthy only if the source *supports* it. This step **verifies** each drafted candidate
against the source spans — independently, so it checks the drafter's provenance claim rather than trusting it —
and computes a **support score**: the fraction of the claim's content tokens (stopwords dropped) that appear in
its best-matching span. Support ≥ the threshold → **keep** the claim with a citation to that span; below → the
claim is **dropped** onto a "couldn't ground" list, never shown as trusted.

There is **no model call** here. Support is a plain, inspectable property, which is exactly what makes a brief
auditable. An extractive claim (the stub's output) grounds trivially; a fabricated claim — one that introduces
tokens the source never used — has low support and is dropped.

Pilot adaptations: `Candidate` (the drafter's output type, originally `app.draft.Candidate`) is inlined as a
lean dataclass; `ground()` takes an explicit `threshold` instead of reading the engine's `settings`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app._engines.summarize.spans import Span

# A small, deterministic stopword set — grounding is about *content* tokens, not function words.
_STOP = frozenset("""
a an and are as at be by for from has have in into is it its of on or that the their this to was were will with
""".split())


@dataclass(frozen=True)
class Candidate:
    """A drafted candidate claim (the model's output), before grounding verifies it.

    ORIGIN: c:/ai/summarize-brief-generator/app/draft.py Candidate — inlined lean copy (the fields grounding uses).
    """

    section_key: str
    text: str
    kind: str = "point"
    salience: float = 0.0


def content_tokens(text: str) -> set[str]:
    """Lowercase alphanumeric tokens, stopwords removed. Numbers/dates are kept (they carry facts)."""
    toks = re.findall(r"[a-z0-9]+", text.lower())
    return {t for t in toks if t not in _STOP and (t.isdigit() or len(t) >= 2)}


def support(claim_text: str, span_text: str) -> float:
    """Fraction of the claim's content tokens present in the span (claim-token recall). 0 if no content."""
    claim = content_tokens(claim_text)
    if not claim:
        return 0.0
    return len(claim & content_tokens(span_text)) / len(claim)


def best_span(claim_text: str, spans: list[Span]) -> tuple[Span | None, float]:
    """The span that best supports the claim, and its support score. Ties → lowest span index."""
    best: Span | None = None
    best_score = -1.0
    for sp in spans:
        s = support(claim_text, sp.text)
        if s > best_score:
            best, best_score = sp, s
    return best, (best_score if best is not None else 0.0)


def best_window(claim_text: str, spans: list[Span], max_span: int = 2) -> tuple[Span | None, float]:
    """Best support over any **contiguous run of ≤ `max_span` spans**, with the anchor span (highest single-span
    support in that window) for the citation. A summary point legitimately compresses 1–2 adjacent sentences, so a
    true lead fact whose tokens split across two sentences ("active from 330 to 1453, headquartered at X") should
    ground — while a fabrication (tokens in no window) still won't. Verifying against an adjacent-sentence window is
    a faithful claim: every token appears in this short, contiguous stretch of the user's document."""
    if not spans:
        return None, 0.0
    best_anchor: Span | None = None
    best_score = -1.0
    n = len(spans)
    for i in range(n):
        combined = ""
        for j in range(i, min(i + max_span, n)):
            combined = (combined + " " + spans[j].text) if combined else spans[j].text
            s = support(claim_text, combined)
            if s > best_score:
                best_score = s
                best_anchor = max(spans[i : j + 1], key=lambda sp: support(claim_text, sp.text))
    return best_anchor, (best_score if best_anchor is not None else 0.0)


@dataclass(frozen=True)
class GroundedClaim:
    section_key: str
    text: str
    span_id: str        # the VERIFIED supporting span — the citation
    support: float
    kind: str
    salience: float = 0.0   # carried from the candidate so the assembler can trim lowest-salience to fit


@dataclass(frozen=True)
class Dropped:
    section_key: str
    text: str
    support: float      # best support found (below threshold)
    best_span_id: str | None
    reason: str


@dataclass
class GroundingResult:
    kept: list[GroundedClaim]
    dropped: list[Dropped]

    @property
    def n_kept(self) -> int:
        return len(self.kept)

    @property
    def n_dropped(self) -> int:
        return len(self.dropped)


def ground(candidates: list[Candidate], spans: list[Span], threshold: float) -> GroundingResult:
    """Verify each candidate against the spans; keep (cited) if support ≥ threshold, else drop and surface.
    Support is measured over the best contiguous ≤2-span window (a summary point may compress two adjacent
    sentences), cited to the anchor span — so a true multi-sentence lead fact grounds, a fabrication still doesn't."""
    kept: list[GroundedClaim] = []
    dropped: list[Dropped] = []
    for c in candidates:
        sp, score = best_window(c.text, spans)
        score = round(score, 4)
        if sp is not None and score >= threshold:
            kept.append(GroundedClaim(c.section_key, c.text, sp.id, score, c.kind, c.salience))
        else:
            reason = ("no content tokens to verify" if not content_tokens(c.text)
                      else f"best support {score:.2f} < threshold {threshold:.2f} — not supported by any span")
            dropped.append(Dropped(c.section_key, c.text, score, sp.id if sp else None, reason))
    return GroundingResult(kept=kept, dropped=dropped)
