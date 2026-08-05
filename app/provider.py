"""The drafting step — the ONLY model call in the pipeline (`anthropic` | `stub`).

`draft_candidates(safe_text, spans, provider)` returns a list of candidate key-points. Everything else —
sanitize, split, ground — is deterministic and never calls a model (see CLAUDE.md principle 6). Whatever the
drafter returns still passes the deterministic grounding gate downstream, so an unsupported claim is withheld
regardless of provider. The model only ever sees **`safe_text`** (already Data-Boundary-sanitized).

- `stub`   — extractive, offline, deterministic: pick the most information-dense spans as candidates. They ground
             trivially (a candidate IS a span's text), so the whole flow runs with no key/network for tests/dev.
- `anthropic` — a real key-points draft over `safe_text`. `truststore.inject_into_ssl()` for the TLS proxy.
"""

from __future__ import annotations

import json

from app._engines.summarize import Candidate, Span, content_tokens

# How many key-points to aim for.
_TARGET_POINTS = 7
# A span needs at least this many content tokens to be a candidate (skip fragments / headings).
_MIN_TOKENS = 4
# Prefer sentence-length spans so the extractive output reads as points, not whole paragraphs. Messy PDF text
# often lacks clean sentence breaks (giant spans); fall back to those only if too few short ones exist.
_READABLE_MAX_CHARS = 320


def _stub_candidates(spans: list[Span]) -> list[Candidate]:
    """Extractive, deterministic: the most information-dense sentence-length spans, in document order.

    Grounds trivially (each candidate IS a span's text). Offline/dev/test path — the shipped experience is the
    `anthropic` draft; here we still prefer short, readable spans so a stub demo looks like key-points.
    """
    scored = [(len(content_tokens(sp.text)), sp) for sp in spans if len(content_tokens(sp.text)) >= _MIN_TOKENS]
    readable = [(n, sp) for n, sp in scored if len(sp.text) <= _READABLE_MAX_CHARS]
    pool = readable if len(readable) >= _TARGET_POINTS else scored  # fall back only if too few short spans
    pool.sort(key=lambda t: (-t[0], t[1].index))                    # densest first, ties by document order
    picked = pool[:_TARGET_POINTS]
    picked.sort(key=lambda t: t[1].index)                           # emit in document order
    return [
        Candidate(section_key="key_points", text=sp.text, kind="point", salience=float(n))
        for n, sp in picked
    ]


_PROMPT = (
    "You are a careful summarizer. From the document below, extract up to {k} of the most important key points.\n"
    "Rules:\n"
    "- Each point must be a single factual sentence drawn ONLY from the document — do not add anything not stated.\n"
    "- Prefer the document's own wording; be concise.\n"
    "- Some names/identifiers may appear as bracketed tokens like [PERSON_NAME_1] or [SSN_1]; keep such tokens\n"
    "  exactly as written — do not guess what they stand for.\n"
    'Return ONLY a JSON array of strings, e.g. ["point one", "point two"]. No prose, no markdown.\n\n'
    "DOCUMENT:\n{doc}"
)


def _anthropic_candidates(safe_text: str) -> list[Candidate]:
    """A real key-points draft. The model sees only `safe_text`. Malformed output → empty (grounding is the gate)."""
    import truststore

    truststore.inject_into_ssl()
    from anthropic import Anthropic

    from app.config import settings

    client = Anthropic()  # reads ANTHROPIC_API_KEY from the environment
    prompt = _PROMPT.format(k=_TARGET_POINTS, doc=safe_text)
    msg = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = "".join(getattr(b, "text", "") for b in msg.content).strip()
    points = _parse_points(raw)
    return [
        Candidate(section_key="key_points", text=p, kind="point", salience=float(len(points) - i))
        for i, p in enumerate(points)
    ]


def _parse_points(raw: str) -> list[str]:
    """Parse the model's reply into a list of point strings. Tolerant: JSON array first, else non-empty lines."""
    raw = raw.strip()
    if raw.startswith("```"):  # strip a ```json fence if present
        raw = raw.strip("`")
        raw = raw[raw.find("\n") + 1:] if "\n" in raw else raw
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [str(x).strip() for x in data if str(x).strip()]
    except (json.JSONDecodeError, ValueError):
        pass
    # Fallback: bullet/numbered lines.
    out = []
    for line in raw.splitlines():
        s = line.strip().lstrip("-*•").strip()
        s = s[s.find(".") + 1:].strip() if s[:2].strip().isdigit() else s
        if s:
            out.append(s)
    return out


def draft_candidates(safe_text: str, spans: list[Span], provider: str) -> list[Candidate]:
    """Draft candidate key-points from the SANITIZED text. `stub` is extractive/offline; `anthropic` is a real draft."""
    if provider == "anthropic":
        return _anthropic_candidates(safe_text)
    return _stub_candidates(spans)


# --- Copilot ("Ask this document"): draft a grounded ANSWER from retrieved passages ------------------

# The model must answer only from the passages, or emit this exact sentinel so we can abstain (never guess).
NOT_IN_DOCUMENT = "NOT_IN_DOCUMENT"

_ANSWER_PROMPT = (
    "You are answering a question using ONLY the numbered passages from the user's own document below.\n"
    "Rules:\n"
    "- Answer in 1–4 sentences using ONLY facts stated in the passages. Do not use outside knowledge.\n"
    "- If the passages do not contain the answer, reply with EXACTLY this and nothing else: {sentinel}\n"
    "- Some names/identifiers may appear as bracketed tokens like [PERSON_NAME_1]; keep such tokens exactly.\n\n"
    "QUESTION: {q}\n\nPASSAGES:\n{passages}"
)


def _passages(spans: list[Span]) -> str:
    return "\n".join(f"[{sp.id}] {sp.text}" for sp in spans)


def _stub_answer(safe_query: str, retrieved: list[Span]) -> str:
    """Extractive, offline: the single best-matching passage IS the answer (it grounds trivially). Deterministic."""
    if not retrieved:
        return NOT_IN_DOCUMENT
    # retrieved is already ranked by relevance; the top passage is the extractive answer.
    return retrieved[0].text


def _anthropic_answer(safe_query: str, retrieved: list[Span]) -> str:
    import truststore

    truststore.inject_into_ssl()
    from anthropic import Anthropic

    from app.config import settings

    if not retrieved:
        return NOT_IN_DOCUMENT
    client = Anthropic()
    prompt = _ANSWER_PROMPT.format(sentinel=NOT_IN_DOCUMENT, q=safe_query, passages=_passages(retrieved))
    msg = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(getattr(b, "text", "") for b in msg.content).strip()


def draft_answer(safe_query: str, retrieved: list[Span], provider: str) -> str:
    """Answer the question from the retrieved (sanitized) passages, or return NOT_IN_DOCUMENT. The model only ever
    sees safe passages + the safe question; grounding downstream still verifies before anything is shown."""
    if provider == "anthropic":
        return _anthropic_answer(safe_query, retrieved)
    return _stub_answer(safe_query, retrieved)


# --- Draft: write one memo SECTION from the salient passages (clean prose, no preamble, no inline markers) -------

import re as _re

_SECTION_PROMPT = (
    'Write the "{heading}" section of a short brief about the user\'s document, using ONLY the numbered passages.\n'
    "Rules:\n"
    "- 1–3 sentences of clean, direct prose. NO preamble (never begin with \"Based on…\"/\"According to…\"), and\n"
    "  NO inline citation markers like [S1].\n"
    "- Use ONLY facts stated in the passages; add nothing from outside them.\n"
    "- Focus this section on: {focus}\n"
    "- If the passages do not support this section, reply with EXACTLY this and nothing else: {sentinel}\n"
    "- Keep bracketed tokens like [PERSON_NAME_1] exactly as written.\n\n"
    "PASSAGES:\n{passages}"
)

_PREAMBLE = _re.compile(r"^\s*(based on|according to)\b[^:.\n]*[:.]\s*", _re.IGNORECASE)


def _clean_section(text: str) -> str:
    """Strip inline [S#] markers and a leading 'Based on…/According to…' preamble the model may still emit."""
    text = _re.sub(r"\s*\[S\d+\]", "", text)   # drop inline citation markers (citations show separately)
    text = _PREAMBLE.sub("", text)
    return text.strip()


def _anthropic_section(heading: str, focus: str, passages: list[Span]) -> str:
    import truststore

    truststore.inject_into_ssl()
    from anthropic import Anthropic

    from app.config import settings

    if not passages:
        return NOT_IN_DOCUMENT
    client = Anthropic()
    prompt = _SECTION_PROMPT.format(heading=heading, focus=focus, sentinel=NOT_IN_DOCUMENT, passages=_passages(passages))
    msg = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = "".join(getattr(b, "text", "") for b in msg.content).strip()
    return raw if raw == NOT_IN_DOCUMENT else _clean_section(raw)


def draft_section(heading: str, focus: str, passages: list[Span], provider: str) -> str:
    """Write one memo section from the sanitized salient passages, or NOT_IN_DOCUMENT. `stub` is extractive (the
    top passage). The model only ever sees the safe passages; grounding still verifies before the section shows."""
    if provider == "anthropic":
        return _anthropic_section(heading, focus, passages)
    return _stub_answer(focus, passages)  # extractive: the top (rotated) salient passage
