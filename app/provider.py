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
