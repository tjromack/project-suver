"""Cite-or-block assembly — ground each section from the document, or drop it; block if a required one fails.

ORIGIN: c:/ai/draft-template-responder/app/fill.py (the `build_draft` fill/enforce/assemble + block-don't-flag
discipline), slimmed: grounding is supplied by a callback (Suver grounds against the dropped document), each
section is a grounded unit rather than a `{slot}` in fixed prose, and the constraint that matters here is
**cite-or-block** — a section with no grounding is omitted (optional) or blocks the draft (required); nothing is
ever written that the document doesn't support. Deterministic; the only model call lives inside the callback.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from app._engines.draft.template import DraftKind, Section


@dataclass(frozen=True)
class GroundedSection:
    """What the grounding callback returns for a section: grounded text + its source citations. `None` = ungrounded."""

    text: str
    citations: list = field(default_factory=list)


@dataclass(frozen=True)
class DraftSection:
    key: str
    heading: str
    text: str
    citations: list = field(default_factory=list)


@dataclass(frozen=True)
class DraftResult:
    kind_slug: str
    title: str
    sections: list[DraftSection] = field(default_factory=list)   # included (grounded) sections, in order
    omitted: list[str] = field(default_factory=list)             # headings dropped (optional + couldn't ground)
    text: str = ""                                               # the assembled memo (markdown-ish)
    blocked: bool = False
    block_reason: str | None = None


def _assemble_text(title: str, sections: list[DraftSection]) -> str:
    """Byte-stable assembly: the title + each grounded section under its heading. Fixed structure, never regenerated."""
    out = [f"# {title}", ""]
    for s in sections:
        out.append(f"## {s.heading}")
        out.append(s.text.strip())
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def assemble(kind: DraftKind, doc_title: str,
             ground: Callable[[Section, int], GroundedSection | None]) -> DraftResult:
    """Ground each section via `ground(section, index)`; keep the grounded ones (cited), omit optional misses,
    block on a required miss or if nothing grounds at all. No fabrication — every included section is
    document-supported. The grounder decides HOW to ground (Suver grounds against the dropped document)."""
    title = f"{kind.title_hint} — {doc_title}" if doc_title else kind.title_hint
    sections: list[DraftSection] = []
    omitted: list[str] = []

    for i, sec in enumerate(kind.sections):
        g = ground(sec, i)
        text = (g.text or "").strip() if g else ""
        if g is not None and sec.max_len:
            text = text[: sec.max_len].rstrip()
        forbidden_hit = g is not None and any(f.lower() in text.lower() for f in kind.forbidden)

        if g is None or not text or forbidden_hit:
            if sec.required:
                reason = (f"the document doesn't support the required “{sec.heading}” section"
                          if not forbidden_hit else f"the “{sec.heading}” section hit a forbidden phrase")
                return DraftResult(kind.slug, title, [], omitted, "", True, reason)
            omitted.append(sec.heading)
            continue

        sections.append(DraftSection(sec.key, sec.heading, text, list(g.citations)))

    if not sections:
        return DraftResult(kind.slug, title, [], omitted, "", True,
                           "nothing in the document could be grounded into this draft")

    return DraftResult(kind.slug, title, sections, omitted, _assemble_text(title, sections), False, None)
