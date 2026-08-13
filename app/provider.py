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
    """Draft candidate key-points from the SANITIZED text. `stub` is extractive/offline; `anthropic` is a real draft.
    On any model error the call degrades to the offline stub (production posture — no crash)."""
    if provider == "anthropic":
        try:
            return _anthropic_candidates(safe_text)
        except Exception:
            return _stub_candidates(spans)
    return _stub_candidates(spans)


# --- Copilot ("Ask this document"): draft a grounded ANSWER from retrieved passages ------------------

# The model must answer only from the passages, or emit this exact sentinel so we can abstain (never guess).
NOT_IN_DOCUMENT = "NOT_IN_DOCUMENT"

_ANSWER_PROMPT = (
    "You are answering a question using ONLY the numbered passages from the user's own document below.\n"
    "Rules:\n"
    "- Answer in 1–4 sentences using ONLY facts stated in the passages. Do not use outside knowledge.\n"
    "- If the passages do not contain the answer, reply with EXACTLY this and nothing else: {sentinel}\n"
    "- Some names/identifiers may appear as bracketed tokens like [PERSON_NAME_1]; keep such tokens exactly.\n"
    "{history}\n"
    "QUESTION: {q}\n\nPASSAGES:\n{passages}"
)

# The cross-document variant (Ask across your documents): the same question is asked of EACH document separately,
# so the passages here are from ONE document that may NOT be the one the question names. Two extra rules prevent the
# two failure modes a corpus creates: (1) never attribute a fact to a company/product/agreement named in the
# question — the passages might be a different document, so state facts about *this* document only; (2) don't cite
# passage/section numbers or write "per the document" — just state the fact (this also removes the "[S#]" artifacts).
_ANSWER_PROMPT_ACROSS = (
    "You are answering a question using ONLY the numbered passages from ONE of the user's documents below. The SAME\n"
    "question is being asked of each document separately, so these passages may be from a DIFFERENT document than the\n"
    "one the question names.\n"
    "Rules:\n"
    "- Answer in 1–3 sentences using ONLY facts stated in the passages. Do not use outside knowledge.\n"
    "- State the facts about THIS document only. Do NOT attribute them to any company, product, or agreement named\n"
    "  in the question — the question may refer to a different document. If these passages don't answer the question,\n"
    "  reply with EXACTLY this and nothing else: {sentinel}\n"
    "- Do NOT mention passage or section numbers, and do NOT write phrases like \"per the document\" or \"according\n"
    "  to\" — just state the fact plainly.\n"
    "- Some names/identifiers may appear as bracketed tokens like [PERSON_NAME_1]; keep such tokens exactly.\n"
    "QUESTION: {q}\n\nPASSAGES:\n{passages}"
)


def _passages(spans: list[Span]) -> str:
    return "\n".join(f"[{sp.id}] {sp.text}" for sp in spans)


def _history_block(context: list[str] | None) -> str:
    """A short conversation-history preamble so a follow-up's references ('that', 'it', 'they') resolve to what
    the user meant. The prior questions are already sanitized (safe). Empty for one-shot Copilot."""
    if not context:
        return ""
    lines = "\n".join(f"- {c}" for c in context)
    return ("- This question continues a conversation. Use the earlier questions below ONLY to resolve what the\n"
            "  current question refers to (e.g. \"that\", \"it\", \"they\"), then answer it from the passages.\n"
            f"EARLIER QUESTIONS:\n{lines}\n")


def _stub_answer(safe_query: str, retrieved: list[Span]) -> str:
    """Extractive, offline: the single best-matching passage IS the answer (it grounds trivially). Deterministic."""
    if not retrieved:
        return NOT_IN_DOCUMENT
    # retrieved is already ranked by relevance; the top passage is the extractive answer.
    return retrieved[0].text


def _anthropic_answer(safe_query: str, retrieved: list[Span], context: list[str] | None = None,
                      across: bool = False) -> str:
    import truststore

    truststore.inject_into_ssl()
    from anthropic import Anthropic

    from app.config import settings

    if not retrieved:
        return NOT_IN_DOCUMENT
    client = Anthropic()
    if across:   # cross-document: neutral subject, no passage-number references (see _ANSWER_PROMPT_ACROSS)
        prompt = _ANSWER_PROMPT_ACROSS.format(sentinel=NOT_IN_DOCUMENT, q=safe_query, passages=_passages(retrieved))
    else:
        prompt = _ANSWER_PROMPT.format(sentinel=NOT_IN_DOCUMENT, q=safe_query, passages=_passages(retrieved),
                                       history=_history_block(context))
    msg = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = "".join(getattr(b, "text", "") for b in msg.content).strip()
    if raw == NOT_IN_DOCUMENT:
        return raw
    # Drop any inline [S#] citation markers the model echoes from the labeled passages (citations show separately);
    # boundary tokens like [PERSON_NAME_1] are left untouched.
    cleaned = _re.sub(r"\s*\[S\d+\]", "", raw)
    # Repair fragments a stripped marker can leave, e.g. "Per [S2], the…" → "Per, the…" → "the…":
    cleaned = _re.sub(r"\s+([,.;:])", r"\1", cleaned)          # orphaned space before punctuation
    cleaned = _re.sub(r"^(Per|Per section|According to|As stated in)[,;:]?\s+", "", cleaned, flags=_re.I)
    return cleaned.strip()


def draft_answer(safe_query: str, retrieved: list[Span], provider: str, *, context: list[str] | None = None,
                 across: bool = False) -> str:
    """Answer the question from the retrieved (sanitized) passages, or return NOT_IN_DOCUMENT. `context` is the
    recent prior questions of a conversation (Converse follow-ups) — already sanitized — so the model can resolve a
    referential follow-up ("what did that force?"); Copilot passes none. The model only ever sees safe passages +
    the safe question + the safe prior questions; grounding downstream still verifies before anything is shown. On
    any model error, degrade to the offline stub."""
    if provider == "anthropic":
        try:
            return _anthropic_answer(safe_query, retrieved, context, across=across)
        except Exception:
            return _stub_answer(safe_query, retrieved)
    return _stub_answer(safe_query, retrieved)


# --- Semantic-recall retrieval: expand the question into alternative phrasings (DEC 032) --------------
# Retrieval ranks passages by token overlap; a passage that states the answer in different words ("shall pay …
# per month" for "monthly fee") can be missed. Here the model expands the SANITIZED question into a few short
# alternative phrasings/terms a document might use; the pipeline then ranks each passage by its BEST match against
# any phrasing. The model only ever sees the safe query (same posture as `draft_answer`), returns generic search
# terms (no user data), and — crucially — the grounding gate is untouched: expansion widens what's RETRIEVED, the
# exact-token grounding still VERIFIES the answer before anything shows. "The model plans, the code computes."

_EXPAND_PROMPT = (
    "A user is searching their own documents for the answer to the QUESTION below. List a few short ALTERNATIVE\n"
    "PHRASINGS or key terms a document might use to STATE that answer — synonyms and paraphrases of what's being\n"
    "asked, NOT the answer itself and NOT the literal question again.\n"
    "Rules:\n"
    "- Output ONLY the phrasings, one per line, at most {n}. No numbering, no commentary, no blank lines.\n"
    "- Each is 1–4 words, concrete (e.g. for \"monthly fee\": \"per month\", \"monthly payment\", \"compensation\").\n"
    "- If the question is already unambiguous with no useful synonyms, output nothing.\n"
    "QUESTION: {q}"
)


def _anthropic_expand(safe_query: str, n: int) -> list[str]:
    import truststore

    truststore.inject_into_ssl()
    from anthropic import Anthropic

    from app.config import settings

    client = Anthropic()
    msg = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=120,
        messages=[{"role": "user", "content": _EXPAND_PROMPT.format(n=n, q=safe_query)}],
    )
    raw = "".join(getattr(b, "text", "") for b in msg.content)
    terms: list[str] = []
    ql = safe_query.strip().lower()
    for line in raw.splitlines():
        t = line.strip().lstrip("-•*0123456789. ").strip()
        if t and t.lower() != ql and t.lower() not in (x.lower() for x in terms):
            terms.append(t)
    return terms[:n]


def expand_query(safe_query: str, provider: str, *, n: int = 6) -> list[str]:
    """Alternative phrasings of the (already-sanitized) question for semantic-recall retrieval — or `[]`. The stub
    returns `[]` (retrieval falls back to the literal question → deterministic, offline, unchanged behavior); on any
    model error we also degrade to `[]`. Never sends anything but the safe query; never affects grounding."""
    q = (safe_query or "").strip()
    if provider != "anthropic" or not q:
        return []
    try:
        return _anthropic_expand(q, n)
    except Exception:
        return []


# --- Re-rank: order retrieved passages by how well each ANSWERS the question (DEC 040) --------------------------
# After lexical retrieval pulls a wide candidate pool, the model re-orders those passages so the ones that actually
# STATE the answer land in the top-K the answerer reads — lifting recall on synonym/compound questions. Only the safe
# query + already-sanitized passages are sent (same posture as draft_answer); the grounding gate is untouched. The
# model ranks, the code slices — "the model plans, the code computes." Stub/error → [] (no-op; today's lexical order).

_RERANK_PROMPT = (
    "You are ranking passages by how well each one helps ANSWER the question below.\n"
    "Reply with ONLY the passage numbers in order, MOST relevant first, comma-separated (e.g. 3,1,4).\n"
    "List every passage number exactly once. No words, no commentary.\n\n"
    "QUESTION: {q}\n\nPASSAGES:\n{passages}"
)


def rerank_passages(safe_query: str, passages: list[str], provider: str) -> list[int]:
    """Return the passage indices (0-based) ordered most→least relevant to `safe_query`, or `[]`. The stub returns
    `[]` (retrieval keeps its deterministic lexical order → offline/tests unchanged); on any model error we also
    degrade to `[]`. Never sends anything but the safe query + the already-sanitized passages; never touches grounding."""
    q = (safe_query or "").strip()
    if provider != "anthropic" or not q or len(passages) < 2:
        return []
    try:
        return _anthropic_rerank(q, passages)
    except Exception:
        return []


def _anthropic_rerank(safe_query: str, passages: list[str]) -> list[int]:
    import re

    import truststore

    truststore.inject_into_ssl()
    from anthropic import Anthropic

    from app.config import settings

    numbered = "\n".join(f"[{i + 1}] {p}" for i, p in enumerate(passages))
    client = Anthropic()
    msg = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=60,
        messages=[{"role": "user", "content": _RERANK_PROMPT.format(q=safe_query, passages=numbered)}],
    )
    raw = "".join(getattr(b, "text", "") for b in msg.content)
    order: list[int] = []
    for tok in re.split(r"[^0-9]+", raw):
        if tok.isdigit():
            idx = int(tok) - 1
            if 0 <= idx < len(passages) and idx not in order:
                order.append(idx)
    return order


# --- Read an image: faithfully transcribe the VISIBLE text of an image, honesty-first (DEC 041) ------------------
# The one modality where sanitize-before-egress can't hold: you can't tokenize PII *inside* pixels without first
# reading the image. So the image is sent to the model as-is (transparently — see the tool's trust note), and the
# honesty discipline moves into the PROMPT: transcribe only what's visible, mark unreadable parts, never guess (the
# vision analog of abstain / flag-the-uncertain). The data boundary is then applied to the OUTPUT transcription so we
# can detect + flag sensitive content and offer a sanitized version for anything shared downstream.

_READ_IMAGE_PROMPT = (
    "Transcribe the text visible in this image faithfully and completely, preserving structure "
    "(labels, line items, totals) as plain text.\n"
    "Rules:\n"
    "- Include ONLY what is actually visible. Do NOT infer, complete, or guess anything that is not shown.\n"
    "- If part is unreadable or cut off, write [unreadable] there rather than guessing.\n"
    "- If the image contains no readable text, reply with exactly: [no readable text]"
)


def read_image(data: bytes, media_type: str, provider: str) -> str:
    """Transcribe an image's visible text via the multimodal model, or `""`. The stub/no-key path returns `""` (it
    can't read pixels offline — the pipeline notes this honestly); on any model error we also degrade to `""`."""
    if provider != "anthropic" or not data:
        return ""
    try:
        return _anthropic_read_image(data, media_type)
    except Exception:
        return ""


def _anthropic_read_image(data: bytes, media_type: str) -> str:
    import base64

    import truststore

    truststore.inject_into_ssl()
    from anthropic import Anthropic

    from app.config import settings

    b64 = base64.standard_b64encode(data).decode("ascii")
    client = Anthropic()
    msg = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=2000,
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
            {"type": "text", "text": _READ_IMAGE_PROMPT},
        ]}],
    )
    return "".join(getattr(b, "text", "") for b in msg.content).strip()


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
    top passage). The model only ever sees the safe passages; grounding still verifies before the section shows.
    On any model error, degrade to the offline stub."""
    if provider == "anthropic":
        try:
            return _anthropic_section(heading, focus, passages)
        except Exception:
            return _stub_answer(focus, passages)
    return _stub_answer(focus, passages)  # extractive: the top (rotated) salient passage


# --- Extractor: pull a list of typed {label, value} items of a field-set kind from the (sanitized) document ------

_EXTRACT_PROMPT = (
    "Extract structured items from the user's document below.\n{instruction}\n"
    'Return ONLY a JSON array of objects, each: {{"label": "...", "value": "...", "uncertain": false}}.\n'
    "- Use ONLY information stated in the document; never invent a value.\n"
    "- Return the **most important ~25 items at most** (favor the clearest, most significant).\n"
    '- Set "uncertain": true ONLY when the value is genuinely ambiguous, estimated, or you had to interpret it —\n'
    "  NOT for a value that is clearly stated in the document (a clearly-stated figure is certain even if it is\n"
    "  large or approximate-sounding, e.g. \"over $29 trillion\").\n"
    "- If the document contains none of this, return [].\n"
    "- Keep bracketed tokens like [EMAIL_1] exactly as written.\n\n"
    "DOCUMENT:\n{doc}"
)

_ISO_DATE = _re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_MONEY_RX = _re.compile(r"(?<![\w.])(\(?\$?\s?\d[\d,]*\.\d{2}\)?)(?![\d])")
_TOKEN_RX = _re.compile(r"\[(EMAIL|PHONE|PERSON_NAME|ADDRESS)_\d+\]")
_KV_RX = _re.compile(r"^\s*([A-Za-z][\w /&.-]{1,40}?)\s*:\s*(\S.{0,118}?)\s*$")
_TOKEN_LABEL = {"EMAIL": "Email", "PHONE": "Phone", "PERSON_NAME": "Name", "ADDRESS": "Address"}


def _labeled(line: str, at: int) -> str:
    """A label from the text before the value's colon on this line, else a generic one."""
    if ":" in line and line.index(":") < at:
        lab = line.split(":", 1)[0].strip()
        if 1 < len(lab) <= 40:
            return lab
    return ""


def _stub_items(safe_text: str, stub_kind: str) -> list[dict]:
    """Deterministic offline extraction over the sanitized text — for tests/dev. Real output is the model path."""
    out: list[dict] = []
    seen: set = set()

    def add(label: str, value: str):
        key = (label.lower(), value)
        if value and key not in seen:
            seen.add(key)
            out.append({"label": label, "value": value, "uncertain": False})

    if stub_kind == "contact":
        for m in _TOKEN_RX.finditer(safe_text):
            add(_TOKEN_LABEL[m.group(1)], m.group(0))
        return out
    if stub_kind == "keyvalue":
        for line in safe_text.splitlines():
            m = _KV_RX.match(line)
            if m:
                add(m.group(1).strip(), m.group(2).strip())
        return out[:14]
    rx = _ISO_DATE if stub_kind == "date" else _MONEY_RX
    generic = "Date" if stub_kind == "date" else "Amount"
    for line in safe_text.splitlines():
        for m in rx.finditer(line):
            add(_labeled(line, m.start()) or generic, m.group(1).strip())
    return out[:20]


def _parse_items(raw: str) -> list[dict]:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = raw[raw.find("\n") + 1:] if "\n" in raw else raw
    data = None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        # Salvage a JSON array truncated by the model's output limit: close it after the last complete object.
        cut = raw.rfind("}")
        if cut != -1:
            try:
                data = json.loads(raw[: cut + 1] + "]")
            except (json.JSONDecodeError, ValueError):
                data = None
    items = []
    for d in data if isinstance(data, list) else []:
        if isinstance(d, dict) and str(d.get("value", "")).strip():
            items.append({"label": str(d.get("label") or "Item").strip(),
                          "value": str(d["value"]).strip(),
                          "uncertain": bool(d.get("uncertain", False))})
    return items


def _anthropic_items(safe_text: str, instruction: str) -> list[dict]:
    import truststore

    truststore.inject_into_ssl()
    from anthropic import Anthropic

    from app.config import settings

    client = Anthropic()
    prompt = _EXTRACT_PROMPT.format(instruction=instruction, doc=safe_text)
    msg = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=4096,   # a full field-set can be many rows; salvage handles any remaining truncation
        messages=[{"role": "user", "content": prompt}],
    )
    raw = "".join(getattr(b, "text", "") for b in msg.content).strip()
    return _parse_items(raw)


def extract_items(safe_text: str, fieldset, provider: str) -> list[dict]:
    """Pull `{label, value, uncertain}` items of the field-set's kind from the SANITIZED text. `stub` is
    deterministic/offline (type regexes + boundary tokens); `anthropic` is a real, schema-shaped extraction. The
    model only ever sees safe text; the confidence gate downstream validates every value before it's shown. On any
    model error, degrade to the offline stub."""
    if provider == "anthropic":
        try:
            return _anthropic_items(safe_text, fieldset.instruction)
        except Exception:
            return _stub_items(safe_text, fieldset.stub_kind)
    return _stub_items(safe_text, fieldset.stub_kind)


# --- Communications · Meeting notes → action items: pull {task, owner, due} the notes actually state -------------

_ACTIONS_PROMPT = (
    "Extract the ACTION ITEMS from the user's meeting notes or transcript below — the concrete tasks, to-dos, "
    "commitments, or follow-ups it states.\n"
    'Return ONLY a JSON array of objects, each: {{"task": "...", "owner": "...", "due": "...", "uncertain": false}}.\n'
    "- task: the action as a short imperative phrase (e.g. \"Send the revised budget\"). Use ONLY what the notes say.\n"
    "- owner: the person or team responsible IF the notes state one, else \"\". Names may appear as bracketed tokens\n"
    "  like [PERSON_NAME_1] — keep them EXACTLY; never guess an owner.\n"
    "- due: the deadline or date IF stated (e.g. \"Friday\", \"June 30\"), else \"\". Never invent a date.\n"
    "- Include ONLY actions explicitly stated; do not infer tasks nobody asked for. If there are none, return [].\n"
    "- Return the most important ~25 at most.\n\n"
    "NOTES:\n{doc}"
)

_ACTION_CUE_RX = _re.compile(r"\b(will|must|should|need(?:s)? to|to-?do|action item|follow[- ]?up|due|by \w)", _re.I)
_ACTION_OWNER_TOKEN_RX = _re.compile(r"\[PERSON_NAME_\d+\]")
_ACTION_SUBJECT_RX = _re.compile(r"^([A-Z][\w .&/]{1,30}?)\s+(?:will|must|should|needs? to|to)\b")
_ACTION_DUE_RX = _re.compile(r"\b(?:by|due|before)\s+(\d{4}-\d{2}-\d{2}|[A-Z][a-z]+(?:\s+\d{1,2})?|\w+day)", _re.I)
_ACTION_SPLIT_RX = _re.compile(r"(?<=[.!?])\s+|\n+|(?:^|\s)[-*•]\s+")


def _stub_action_items(safe_text: str) -> list[dict]:
    """Deterministic offline extraction — sentences that read like commitments become tasks (task = the sentence, so
    it grounds trivially downstream). Owner = a boundary name-token or the subject before 'will/must/should'; due =
    a 'by/due <date>' capture. Real output is the model path; this keeps tests/dev offline."""
    out: list[dict] = []
    seen: set[str] = set()
    for raw in _ACTION_SPLIT_RX.split(safe_text):
        s = (raw or "").strip(" -*•\t")
        if len(s) < 8 or not _ACTION_CUE_RX.search(s):
            continue
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        owner_m = _ACTION_OWNER_TOKEN_RX.search(s)
        if owner_m:
            owner = owner_m.group(0)
        else:
            subj = _ACTION_SUBJECT_RX.match(s)
            owner = subj.group(1).strip() if subj else ""
        due_m = _ACTION_DUE_RX.search(s)
        out.append({"task": s, "owner": owner, "due": due_m.group(1).strip() if due_m else "", "uncertain": False})
        if len(out) >= 25:
            break
    return out


def _parse_actions(raw: str) -> list[dict]:
    """Parse the model's reply into {task, owner, due, uncertain}. Tolerant + salvages a truncated JSON array."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = raw[raw.find("\n") + 1:] if "\n" in raw else raw
    data = None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        cut = raw.rfind("}")
        if cut != -1:
            try:
                data = json.loads(raw[: cut + 1] + "]")
            except (json.JSONDecodeError, ValueError):
                data = None
    items = []
    for d in data if isinstance(data, list) else []:
        if isinstance(d, dict) and str(d.get("task", "")).strip():
            items.append({"task": str(d["task"]).strip(),
                          "owner": str(d.get("owner") or "").strip(),
                          "due": str(d.get("due") or "").strip(),
                          "uncertain": bool(d.get("uncertain", False))})
    return items


def _anthropic_action_items(safe_text: str) -> list[dict]:
    import truststore

    truststore.inject_into_ssl()
    from anthropic import Anthropic

    from app.config import settings

    client = Anthropic()
    prompt = _ACTIONS_PROMPT.format(doc=safe_text)
    msg = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = "".join(getattr(b, "text", "") for b in msg.content).strip()
    return _parse_actions(raw)


def extract_action_items(safe_text: str, provider: str) -> list[dict]:
    """Pull `{task, owner, due, uncertain}` action items from the SANITIZED notes. `stub` is deterministic/offline;
    `anthropic` is a real extraction. The model only ever sees safe text (names arrive as boundary tokens); the
    cite-or-drop + owner/due-must-be-stated gates downstream verify before anything shows. Degrades to the stub on
    any model error."""
    if provider == "anthropic":
        try:
            return _anthropic_action_items(safe_text)
        except Exception:
            return _stub_action_items(safe_text)
    return _stub_action_items(safe_text)


# --- Communications · Triage messages: bucket each message by what it needs (needs_reply/action/fyi/ignore) --------

_TRIAGE_CATEGORIES = ("needs_reply", "action", "fyi", "ignore")

_TRIAGE_PROMPT = (
    "You are triaging the user's messages. For EACH numbered message below, decide what it needs:\n"
    "- needs_reply: the sender is waiting for a response from the user.\n"
    "- action: it asks the user to DO something (a task or deadline), no reply needed.\n"
    "- fyi: informational — worth reading, but no action or reply.\n"
    "- ignore: no value to the user (newsletter, promotion, automated no-reply, spam).\n"
    'Return ONLY a JSON array, one object per message: {{"index": <n>, "category": "...", "reason": "...", '
    '"confidence": 0.0}}.\n'
    "- reason: one short phrase drawn ONLY from the message (why it lands in that bucket). Never invent.\n"
    "- confidence: how sure you are (use below 0.6 when the message is genuinely ambiguous).\n"
    "- Keep bracketed tokens like [PERSON_NAME_1] exactly.\n\n"
    "MESSAGES:\n{numbered}"
)

_TRIAGE_CUES = {
    "ignore": ("unsubscribe", "newsletter", "no-reply", "noreply", "% off", "sale ends", "limited time",
               "promotion", "view in browser", "do not reply"),
    "needs_reply": ("?", "let me know", "can you", "could you", "please confirm", "get back to me", "thoughts",
                    "what do you think", "are you able", "would you", "please advise", "waiting to hear", "reply"),
    "action": ("please ", "action required", "need you to", "by friday", "by monday", "by tuesday", "by wednesday",
               "by thursday", "deadline", " due ", "submit", "complete the", "sign the", "approve"),
    "fyi": ("fyi", "for your information", "heads up", "just so you know", "no action needed", "reminder",
            "will be closed", "please note", "update:", "notice:"),
}


def _stub_triage(messages: list[str]) -> list[dict]:
    """Deterministic offline triage — keyword cues decide the bucket; a message with no clear cue gets low confidence
    (the pipeline then flags it 'review'). The reason is a short slice of the message, so it grounds trivially."""
    out: list[dict] = []
    for m in messages:
        low = m.lower()
        cat, conf = "fyi", 0.5
        if any(c in low for c in _TRIAGE_CUES["ignore"]):
            cat, conf = "ignore", 0.9
        elif any(c in low for c in _TRIAGE_CUES["needs_reply"]):
            cat, conf = "needs_reply", 0.9
        elif any(c in low for c in _TRIAGE_CUES["action"]):
            cat, conf = "action", 0.9
        elif any(c in low for c in _TRIAGE_CUES["fyi"]):
            cat, conf = "fyi", 0.85
        first = next((ln.strip() for ln in m.splitlines() if ln.strip()), m.strip())
        out.append({"category": cat, "reason": first[:120], "confidence": conf})
    return out


def _parse_triage(raw: str, n: int) -> list[dict]:
    """Parse the model's reply into `n` aligned {category, reason, confidence} dicts (by `index`; gaps → unsure)."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = raw[raw.find("\n") + 1:] if "\n" in raw else raw
    data = None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        cut = raw.rfind("}")
        if cut != -1:
            try:
                data = json.loads(raw[: cut + 1] + "]")
            except (json.JSONDecodeError, ValueError):
                data = None
    aligned: list[dict] = [{"category": "unsure", "reason": "", "confidence": 0.0} for _ in range(n)]
    for d in data if isinstance(data, list) else []:
        if not isinstance(d, dict):
            continue
        try:
            i = int(d.get("index"))
        except (TypeError, ValueError):
            continue
        if 0 <= i < n:
            cat = str(d.get("category") or "").strip().lower()
            try:
                conf = float(d.get("confidence", 0.0))
            except (TypeError, ValueError):
                conf = 0.0
            aligned[i] = {"category": cat if cat in _TRIAGE_CATEGORIES else "unsure",
                          "reason": str(d.get("reason") or "").strip(),
                          "confidence": max(0.0, min(1.0, conf))}
    return aligned


def _anthropic_triage(messages: list[str]) -> list[dict]:
    import truststore

    truststore.inject_into_ssl()
    from anthropic import Anthropic

    from app.config import settings

    client = Anthropic()
    numbered = "\n".join(f"[{i}] {m}" for i, m in enumerate(messages))
    prompt = _TRIAGE_PROMPT.format(numbered=numbered)
    msg = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = "".join(getattr(b, "text", "") for b in msg.content).strip()
    return _parse_triage(raw, len(messages))


def classify_messages(messages: list[str], provider: str) -> list[dict]:
    """Triage each (SANITIZED) message → {category, reason, confidence}, aligned to input order. `stub` is
    deterministic/offline; `anthropic` is a real one-call triage. The model only ever sees safe text; the pipeline
    flags a low-confidence classification as 'review' (never a confident wrong bucket). Degrades to the stub on error."""
    if not messages:
        return []
    if provider == "anthropic":
        try:
            return _anthropic_triage(messages)
        except Exception:
            return _stub_triage(messages)
    return _stub_triage(messages)


# --- Communications · Draft a reply: a grounded reply to a received message; unknowns become [placeholders] --------

_REPLY_PROMPT = (
    "Draft a short, professional reply to the message below. The user's intent for the reply: {intent}\n"
    "Rules:\n"
    "- Use ONLY facts stated in the message. Do NOT invent any specific — no date, time, number, price, name,\n"
    "  link, or commitment the message doesn't contain.\n"
    "- For anything you would need but the message doesn't give, insert a clearly-labeled placeholder in square\n"
    "  brackets, e.g. [confirm the meeting time] or [your answer here] — never guess it.\n"
    "- Keep it concise (2–6 sentences), plain text, no subject line.\n"
    "- Some names appear as bracketed tokens like [PERSON_NAME_1] — those are the REAL names; keep them exactly\n"
    "  (they are not placeholders).\n\n"
    "MESSAGE:\n{message}"
)

_REPLY_STUBS = {
    "acknowledge": "Thanks for your message — got it. [confirm the specific point]. I'll [next step] and follow up. Best,",
    "answer": "Thanks for reaching out. [your answer to their question]. Let me know if you need anything else. Best,",
    "decline": "Thanks for thinking of me. Unfortunately I won't be able to [what they asked] because [reason]. Best,",
    "request_info": "Thanks for the note. Could you share [the detail you need] so I can respond properly? Best,",
    "follow_up": "Thanks for this — I'll look into it and follow up on [what you'll get back on] by [date]. Best,",
}


def _stub_reply(intent_slug: str) -> str:
    """Deterministic offline reply — an intent-appropriate template with explicit [placeholders], no invented
    specifics. The shipped experience is the `anthropic` draft; this keeps tests/dev offline."""
    return _REPLY_STUBS.get(intent_slug, _REPLY_STUBS["acknowledge"])


def _anthropic_reply(safe_message: str, intent_focus: str) -> str:
    import truststore

    truststore.inject_into_ssl()
    from anthropic import Anthropic

    from app.config import settings

    client = Anthropic()
    prompt = _REPLY_PROMPT.format(intent=intent_focus, message=safe_message)
    msg = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(getattr(b, "text", "") for b in msg.content).strip()


def draft_reply(safe_message: str, intent_slug: str, intent_focus: str, provider: str) -> str:
    """Draft a reply to the SANITIZED message for the chosen intent. `stub` is a deterministic template; `anthropic`
    is a real draft that uses only the message's facts and inserts [placeholders] for anything it doesn't know. The
    model only ever sees safe text; the pipeline lists placeholders + flags any invented specific. Degrades to the
    stub on any model error."""
    if provider == "anthropic":
        try:
            return _anthropic_reply(safe_message, intent_focus)
        except Exception:
            return _stub_reply(intent_slug)
    return _stub_reply(intent_slug)


# --- Data & Analysis · Ask your spreadsheet: the model PLANS a query; the pipeline COMPUTES it deterministically ---

_PLAN_PROMPT = (
    "You turn a question about a table into a STRUCTURED PLAN that will be executed deterministically over the data. "
    "You do NOT compute or state the answer yourself — only the plan.\n"
    "The table's columns:\n{schema}\n\nA few sample rows (for context only):\n{sample}\n\n"
    'Return ONLY a JSON object: {{"op": "aggregate"|"count"|"filter"|"groupby", '
    '"column": "<number column, or null>", "group_column": "<text column for groupby, or null>", '
    '"agg": "sum"|"avg"|"min"|"max"|"count"|null, "top": <integer or null>, "order": "desc"|"asc"|null, '
    '"filter": {{"column": "<column>", "match": "eq"|"contains", "value": "<value from the question>"}} | null, '
    '"answerable": true}}\n'
    "Rules:\n"
    "- aggregate: a sum/average/min/max over a NUMBER column (set `agg` and `column`). count: how many rows match. "
    "filter: return the matching rows (optionally `column` = one column to show).\n"
    "- groupby: group rows by a TEXT column and aggregate a NUMBER column per group — use for \"which X has the "
    "most/least Y\" or \"Y by X\" (set `group_column` + `column` + `agg`; for the single winner set `top`=1 and "
    "`order`=desc for most / asc for least).\n"
    "- `filter.value` comes from the QUESTION (what the user filters by); `match` is eq for exact, contains for partial.\n"
    "- Use ONLY the exact column names listed above. If the question can't be answered from these columns, set "
    '`answerable` to false.\n'
    "- Never put the numeric answer in the plan.\n\n"
    "QUESTION: {question}"
)

_AGG_WORDS = {"sum": "sum", "total": "sum", "add": "sum", "average": "avg", "avg": "avg", "mean": "avg",
              "max": "max", "maximum": "max", "highest": "max", "largest": "max", "most": "max",
              "min": "min", "minimum": "min", "lowest": "min", "smallest": "min"}
_EXPLICIT_AGG = {"sum": "sum", "total": "sum", "average": "avg", "avg": "avg", "mean": "avg", "count": "count"}
_ARGMAX_WORDS = ("which", "most", "highest", "largest", "top", "biggest", "greatest", "best")
_ARGMIN_WORDS = ("lowest", "smallest", "least", "fewest", "worst")


def _plan(op, **kw):
    base = {"op": op, "column": None, "group_column": None, "agg": None, "top": None, "order": None,
            "filter": None, "answerable": True}
    base.update(kw)
    return base


def _stub_plan(schema_headers: list[str], numeric_headers: list[str], question: str) -> dict:
    """Deterministic offline planner — routes group-by / aggregate / count questions by keyword + a column mention;
    else abstains. Enough to run the flow offline for tests; the shipped planner is the `anthropic` path."""
    q = (question or "").lower()
    text_headers = [h for h in schema_headers if h not in numeric_headers]

    def find_col(cols):
        return next((h for h in cols if h and h.lower() in q), None)

    is_argmax = any(w in q for w in _ARGMAX_WORDS)
    is_argmin = any(w in q for w in _ARGMIN_WORDS)

    # groupby: a text column mentioned + an argmax/argmin word or "by"/"per"
    gcol = find_col(text_headers)
    if gcol and (is_argmax or is_argmin or " by " in q or "per " in q):
        ncol = find_col(numeric_headers) or (numeric_headers[0] if numeric_headers else None)
        if ncol:
            expl = next((v for k, v in _EXPLICIT_AGG.items() if _re.search(rf"\b{k}\b", q)), None)
            return _plan("groupby", group_column=gcol, column=ncol, agg=expl or "sum",
                         top=1 if (is_argmax or is_argmin) else None, order="asc" if is_argmin else "desc")

    if "how many" in q or "count" in q or "number of rows" in q:
        return _plan("count")

    agg = next((v for k, v in _AGG_WORDS.items() if _re.search(rf"\b{k}\b", q)), None)
    if agg:
        col = find_col(numeric_headers) or (numeric_headers[0] if numeric_headers else None)
        if col:
            return _plan("aggregate", column=col, agg=agg)

    col = find_col(schema_headers)
    if col:
        return _plan("filter", column=col)
    # Nothing in the question maps to this table → abstain (never guess an operation). The anthropic planner handles
    # value-filters ("the West rows") that this offline heuristic can't.
    return _plan("filter", answerable=False)


def _parse_plan(raw: str) -> dict | None:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = raw[raw.find("\n") + 1:] if "\n" in raw else raw
    try:
        d = json.loads(raw)
        return d if isinstance(d, dict) else None
    except (json.JSONDecodeError, ValueError):
        cut = raw.rfind("}")
        if cut != -1:
            try:
                d = json.loads(raw[: cut + 1])
                return d if isinstance(d, dict) else None
            except (json.JSONDecodeError, ValueError):
                return None
    return None


def _anthropic_plan(safe_schema: str, safe_sample: str, safe_question: str) -> dict | None:
    import truststore

    truststore.inject_into_ssl()
    from anthropic import Anthropic

    from app.config import settings

    client = Anthropic()
    prompt = _PLAN_PROMPT.format(schema=safe_schema, sample=safe_sample, question=safe_question)
    msg = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = "".join(getattr(b, "text", "") for b in msg.content).strip()
    return _parse_plan(raw)


def plan_query(safe_schema: str, safe_sample: str, safe_question: str, schema_headers: list[str],
               numeric_headers: list[str], provider: str) -> dict | None:
    """Ask the model for a STRUCTURED PLAN over the (sanitized) schema + sample + question — never the answer. The
    pipeline executes the plan deterministically over the full local data. `stub` is a heuristic planner. The model
    only ever sees the sanitized schema + a sanitized SAMPLE (never the full dataset). Degrades to the stub on error."""
    if provider == "anthropic":
        try:
            plan = _anthropic_plan(safe_schema, safe_sample, safe_question)
            if plan is not None:
                return plan
        except Exception:
            pass
        return _stub_plan(schema_headers, numeric_headers, safe_question)
    return _stub_plan(schema_headers, numeric_headers, safe_question)


# --- Data & Analysis · Summarize a spreadsheet: the model NARRATES a computed profile (never invents a number) ------

_NARRATE_PROMPT = (
    "Below is a COMPUTED profile of a data table — the numbers are already calculated for you. Write a 2–4 sentence "
    "plain-language overview of the dataset: what it appears to be about, its size, and 2–3 of the most notable facts.\n"
    "Rules:\n"
    "- Use ONLY the numbers in the profile — do NOT recompute anything or invent any figure.\n"
    "- No preamble (don't start with \"Based on…\"/\"This profile…\"); just the overview, plain and direct.\n"
    "- Keep bracketed tokens like [PERSON_NAME_1] exactly as written.\n\n"
    "PROFILE:\n{profile}\n\nSAMPLE ROWS:\n{sample}"
)


def _stub_narrate(n_rows: int, n_cols: int) -> str:
    return f"This table has {n_rows:,} rows and {n_cols} columns. See the computed column profile below."


def _anthropic_narrate(safe_profile: str, safe_sample: str) -> str:
    import truststore

    truststore.inject_into_ssl()
    from anthropic import Anthropic

    from app.config import settings

    client = Anthropic()
    prompt = _NARRATE_PROMPT.format(profile=safe_profile, sample=safe_sample)
    msg = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = "".join(getattr(b, "text", "") for b in msg.content).strip()
    return _PREAMBLE.sub("", raw).strip()


def narrate_table(safe_profile: str, safe_sample: str, n_rows: int, n_cols: int, provider: str) -> str:
    """Write a plain-language overview of a table from its already-COMPUTED profile. `stub` is a minimal deterministic
    line; `anthropic` narrates. The model only ever sees the sanitized profile + a sanitized sample (never the full
    data) and is told to use only the computed numbers — the profile table shown alongside is the ground truth.
    Degrades to the stub on any model error."""
    if provider == "anthropic":
        try:
            return _anthropic_narrate(safe_profile, safe_sample)
        except Exception:
            return _stub_narrate(n_rows, n_cols)
    return _stub_narrate(n_rows, n_cols)


# --- Learning platform (DEC 044): turn a document into study material (flashcards, quiz) ------------------------
# Same trust discipline as Summarize: the model DRAFTS study items from sanitized text; the deterministic grounding
# gate (cite-or-drop, in the pipeline) then verifies each item's ANSWER against a source span before it's shown — a
# card/question whose answer can't be grounded is dropped, never invented. The model only ever sees `safe_text`.

def _first_words(text: str, n: int = 6) -> str:
    ws = (text or "").split()
    return " ".join(ws[:n]) + ("…" if len(ws) > n else "")


def _parse_json_array(raw: str) -> list:
    """Parse the model's reply into a JSON array, tolerant of a ```json fence. Malformed → [] (grounding is the gate)."""
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = raw[raw.find("\n") + 1:] if "\n" in raw else raw
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, ValueError):
        return []


_FLASHCARDS_PROMPT = (
    "From the document below, write up to {k} study flashcards. Each flashcard is a question and a short answer.\n"
    "Rules:\n"
    "- Base every card ONLY on facts stated in the document. Do not add anything not stated.\n"
    "- The ANSWER must be a fact from the document (prefer its own wording); keep it to one short sentence.\n"
    "- Some names/identifiers may appear as bracketed tokens like [PERSON_NAME_1]; keep such tokens exactly.\n"
    'Return ONLY a JSON array of objects: [{{"q":"...","a":"..."}}]. No prose, no markdown.\n\n'
    "DOCUMENT:\n{doc}"
)


def _stub_flashcards(spans: list[Span], k: int) -> list[dict]:
    """Extractive/offline: a card per information-dense span (answer IS the span, so it grounds trivially)."""
    picked = [sp for sp in spans if len(content_tokens(sp.text)) >= _MIN_TOKENS][:k]
    return [{"q": f'What does the document state about "{_first_words(sp.text)}"?', "a": sp.text} for sp in picked]


def _anthropic_flashcards(safe_text: str, k: int) -> list[dict]:
    import truststore

    truststore.inject_into_ssl()
    from anthropic import Anthropic

    from app.config import settings

    client = Anthropic()
    msg = client.messages.create(
        model=settings.anthropic_model, max_tokens=1200,
        messages=[{"role": "user", "content": _FLASHCARDS_PROMPT.format(k=k, doc=safe_text)}],
    )
    raw = "".join(getattr(b, "text", "") for b in msg.content)
    out: list[dict] = []
    for it in _parse_json_array(raw):
        if isinstance(it, dict):
            q, a = str(it.get("q", "")).strip(), str(it.get("a", "")).strip()
            if q and a:
                out.append({"q": q, "a": a})
    return out[:k]


def make_flashcards(safe_text: str, spans: list[Span], provider: str, *, k: int) -> list[dict]:
    """Draft candidate flashcards (q/a) from the SANITIZED text. `stub` is extractive/offline; `anthropic` is a real
    draft. On any model error → the offline stub (production posture). Grounding downstream is the gate, either way."""
    if provider == "anthropic":
        try:
            return _anthropic_flashcards(safe_text, k)
        except Exception:
            return _stub_flashcards(spans, k)
    return _stub_flashcards(spans, k)


_QUIZ_PROMPT = (
    "From the document below, write up to {k} multiple-choice quiz questions.\n"
    "Rules:\n"
    "- Each question has ONE correct answer that is a fact stated in the document, and three plausible but WRONG\n"
    "  options that are NOT stated as true in the document.\n"
    "- Base the correct answer ONLY on the document; keep every option short.\n"
    "- Some names/identifiers may appear as bracketed tokens like [PERSON_NAME_1]; keep such tokens exactly.\n"
    'Return ONLY a JSON array: [{{"q":"...","correct":"...","distractors":["...","...","..."]}}]. No prose, no markdown.\n\n'
    "DOCUMENT:\n{doc}"
)


def _stub_quiz(spans: list[Span], k: int) -> list[dict]:
    picked = [sp for sp in spans if len(content_tokens(sp.text)) >= _MIN_TOKENS][:k]
    return [{"q": f'According to the document, which is correct about "{_first_words(sp.text)}"?',
             "correct": sp.text,
             "distractors": ["This is not stated in the document.", "A different detail entirely.", "None of the above."]}
            for sp in picked]


def _anthropic_quiz(safe_text: str, k: int) -> list[dict]:
    import truststore

    truststore.inject_into_ssl()
    from anthropic import Anthropic

    from app.config import settings

    client = Anthropic()
    msg = client.messages.create(
        model=settings.anthropic_model, max_tokens=1400,
        messages=[{"role": "user", "content": _QUIZ_PROMPT.format(k=k, doc=safe_text)}],
    )
    raw = "".join(getattr(b, "text", "") for b in msg.content)
    out: list[dict] = []
    for it in _parse_json_array(raw):
        if isinstance(it, dict):
            q, correct = str(it.get("q", "")).strip(), str(it.get("correct", "")).strip()
            dz = [str(x).strip() for x in (it.get("distractors") or []) if str(x).strip()]
            if q and correct:
                out.append({"q": q, "correct": correct, "distractors": dz[:3]})
    return out[:k]


def make_quiz(safe_text: str, spans: list[Span], provider: str, *, k: int) -> list[dict]:
    """Draft candidate quiz questions (q/correct/distractors) from the SANITIZED text. `stub` offline; `anthropic`
    real; error → stub. The pipeline grounds the CORRECT answer (cite-or-drop) before showing a question."""
    if provider == "anthropic":
        try:
            return _anthropic_quiz(safe_text, k)
        except Exception:
            return _stub_quiz(spans, k)
    return _stub_quiz(spans, k)
