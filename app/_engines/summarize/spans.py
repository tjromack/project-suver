"""Source spans — split a document into numbered, cited units with provenance.

ORIGIN: c:/ai/summarize-brief-generator/app/spans.py  (verbatim).

Every claim in a brief must trace to a specific piece of the source. That piece is a **span**: a sentence- or
line-granularity unit with a stable id (`S1..Sn`) and exact **char offsets** into the original text, so a
citation is verifiable (`text[span.start:span.end] == span.text`). Splitting is **deterministic** — no model —
so the same document always yields the same spans, which is what makes grounding and the eval reproducible.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# A newline whose next line begins a list item or an enumerated point starts a new span.
_NEXT_IS_ITEM = re.compile(r"[ \t]*(?:[-*•]|\d+[.)])\s")


@dataclass(frozen=True)
class Span:
    id: str          # "S1", "S2", ...  — the citation label
    index: int       # 1-based
    text: str        # the span's text, whitespace-trimmed
    start: int       # char offset of `text` in the source document
    end: int         # start + len(text)  (so source[start:end] == text)

    def to_dict(self) -> dict:
        return {"id": self.id, "index": self.index, "text": self.text, "start": self.start, "end": self.end}


def _is_sentence_end(text: str, i: int, n: int) -> int | None:
    """If a sentence terminator ends here, return the offset just past it (incl. trailing quotes); else None."""
    if text[i] not in ".!?":
        return None
    j = i + 1
    while j < n and text[j] in "\"')]":
        j += 1
    if j >= n or text[j].isspace():
        return j
    return None


def split_document(text: str) -> list[Span]:
    """Split `text` into ordered `Span`s with exact offsets. Deterministic; no model."""
    spans: list[Span] = []
    n = len(text)
    i = 0
    idx = 0
    while i < n:
        while i < n and text[i].isspace():      # skip leading whitespace
            i += 1
        if i >= n:
            break
        start = i
        while i < n:
            end_at = _is_sentence_end(text, i, n)
            if end_at is not None:
                i = end_at
                break
            if text[i] == "\n":
                # blank-line paragraph break, or the next line starts a list item / heading
                rest = text[i + 1:]
                if rest[:1] == "\n" or _NEXT_IS_ITEM.match(rest):
                    break
            i += 1
        stripped = text[start:i].rstrip()
        if stripped:
            idx += 1
            spans.append(Span(id=f"S{idx}", index=idx, text=stripped, start=start, end=start + len(stripped)))
    return spans


def by_id(spans: list[Span]) -> dict[str, Span]:
    return {s.id: s for s in spans}


def load_source(path) -> str:
    from pathlib import Path

    return Path(path).read_text(encoding="utf-8")
