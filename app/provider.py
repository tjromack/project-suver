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


def _anthropic_answer(safe_query: str, retrieved: list[Span], context: list[str] | None = None) -> str:
    import truststore

    truststore.inject_into_ssl()
    from anthropic import Anthropic

    from app.config import settings

    if not retrieved:
        return NOT_IN_DOCUMENT
    client = Anthropic()
    prompt = _ANSWER_PROMPT.format(sentinel=NOT_IN_DOCUMENT, q=safe_query, passages=_passages(retrieved),
                                   history=_history_block(context))
    msg = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = "".join(getattr(b, "text", "") for b in msg.content).strip()
    # Drop any inline [S#] citation markers the model echoes from the labeled passages (citations show separately);
    # boundary tokens like [PERSON_NAME_1] are left untouched.
    return raw if raw == NOT_IN_DOCUMENT else _re.sub(r"\s*\[S\d+\]", "", raw).strip()


def draft_answer(safe_query: str, retrieved: list[Span], provider: str, *, context: list[str] | None = None) -> str:
    """Answer the question from the retrieved (sanitized) passages, or return NOT_IN_DOCUMENT. `context` is the
    recent prior questions of a conversation (Converse follow-ups) — already sanitized — so the model can resolve a
    referential follow-up ("what did that force?"); Copilot passes none. The model only ever sees safe passages +
    the safe question + the safe prior questions; grounding downstream still verifies before anything is shown. On
    any model error, degrade to the offline stub."""
    if provider == "anthropic":
        try:
            return _anthropic_answer(safe_query, retrieved, context)
        except Exception:
            return _stub_answer(safe_query, retrieved)
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
    'Return ONLY a JSON object: {{"op": "aggregate"|"count"|"filter", "column": "<column name or null>", '
    '"agg": "sum"|"avg"|"min"|"max"|null, "filter": {{"column": "<column>", "match": "eq"|"contains", '
    '"value": "<value from the question>"}} | null, "answerable": true}}\n'
    "Rules:\n"
    "- aggregate: a sum/average/min/max over a NUMBER column (set `agg` and `column`). count: how many rows match. "
    "filter: return the matching rows (optionally `column` = one column to show).\n"
    "- `filter.value` comes from the QUESTION (what the user filters by); `match` is eq for exact, contains for partial.\n"
    "- Use ONLY the exact column names listed above. If the question can't be answered from these columns, set "
    '`answerable` to false.\n'
    "- Never put the numeric answer in the plan.\n\n"
    "QUESTION: {question}"
)

_AGG_WORDS = {"sum": "sum", "total": "sum", "add": "sum", "average": "avg", "avg": "avg", "mean": "avg",
              "max": "max", "maximum": "max", "highest": "max", "largest": "max", "most": "max",
              "min": "min", "minimum": "min", "lowest": "min", "smallest": "min"}


def _stub_plan(schema_headers: list[str], numeric_headers: list[str], question: str) -> dict:
    """Deterministic offline planner — match an aggregate word + a column name from the question; else count. Enough
    to run the flow offline for tests; the shipped planner is the `anthropic` path."""
    q = (question or "").lower()
    agg = next((v for k, v in _AGG_WORDS.items() if _re.search(rf"\b{k}\b", q)), None)
    # a column mentioned in the question (prefer a numeric one for aggregates)
    def find_col(cols):
        return next((h for h in cols if h and h.lower() in q), None)
    if "how many" in q or "count" in q or "number of rows" in q:
        return {"op": "count", "column": None, "agg": None, "filter": None, "answerable": True}
    if agg:
        col = find_col(numeric_headers) or (numeric_headers[0] if numeric_headers else None)
        if col:
            return {"op": "aggregate", "column": col, "agg": agg, "filter": None, "answerable": True}
    col = find_col(schema_headers)
    if col:
        return {"op": "filter", "column": col, "agg": None, "filter": None, "answerable": True}
    # Nothing in the question maps to this table → abstain (never guess an operation). The anthropic planner handles
    # value-filters ("the West rows") that this offline heuristic can't.
    return {"op": "filter", "column": None, "agg": None, "filter": None, "answerable": False}


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
