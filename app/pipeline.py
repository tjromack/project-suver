"""The tool pipeline: ingest → **sanitize** → split → **draft(LLM)** → **ground** → re-hydrate → result.

This is where the composition lives. The invariant that makes Suver safe on real data: **the model only ever
sees `BoundaryResult.safe_text`** — sanitize runs before the drafter, the token map stays local, and re-hydration
happens only when building the view. The invariant has a test (`tests/test_sanitize_flow.py`). Every displayed
claim cites a source span or it is withheld (cite-or-drop; `tests/test_pipeline.py`).

Fail-closed: if the boundary decides `route_local`/`block`, `safe_text` is `None` — nothing may leave, so we do
**not** summarize; we tell the user their document stays on-device instead.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from difflib import SequenceMatcher

from app._engines.boundary import BoundaryResult, default_policy, rehydrate, sanitize
from app._engines.compare import CompareField, CompareSchema
from app._engines.compare import FieldType as CompareFieldType
from app._engines.compare import compare, explain_stub
from app._engines.draft import GroundedSection, assemble, default_kind, get_kind
from app._engines.extract import default_fieldset, get_fieldset, score_item
from app._engines.summarize import Span, content_tokens, ground, split_document, support
from app.config import settings
from app.ingest import IngestResult, extract_text, from_paste
from app.provider import NOT_IN_DOCUMENT, draft_answer, draft_candidates, draft_section, extract_items


@dataclass(frozen=True)
class Claim:
    text: str            # the key-point, re-hydrated for local display
    span_id: str         # the cited source span
    span_text: str       # the cited span's text, re-hydrated for local display
    support: float       # grounding support score (0–1)


@dataclass(frozen=True)
class Withheld:
    text: str
    reason: str


@dataclass(frozen=True)
class SummaryResult:
    claims: list[Claim] = field(default_factory=list)
    withheld: list[Withheld] = field(default_factory=list)
    handled_count: int = 0                 # sensitive items the boundary handled before the model saw the text
    handled_classes: list[str] = field(default_factory=list)
    decision: str = "clear"                # boundary decision: clear | redacted | route_local | block
    provider: str = "stub"
    kind: str = "text"                     # ingest kind (txt/md/pdf/docx/paste)
    source_chars: int = 0
    note: str | None = None                # e.g. "summarized the first N of M characters"
    blocked: bool = False                  # True when the document may not leave the device (route_local/block)
    block_message: str | None = None

    @property
    def handled_note(self) -> str:
        """The '🛡 N sensitive items handled' trust-chip text."""
        n = self.handled_count
        if n == 0:
            return "No sensitive items detected"
        item = "item" if n == 1 else "items"
        return f"{n} sensitive {item} handled before the model"


_BLOCK_MSG = (
    "This document contains data that isn't allowed to leave your device under the active policy "
    "({classes}), so it was kept local and not summarized. Nothing was sent to the model."
)


# --- Long-document handling: window a doc into ≤ budget-char passes; map-reduce over the windows -------


def _span_windows(spans: list[Span], budget: int) -> list[list[Span]]:
    """Group consecutive spans into windows each spanning ≤ `budget` chars (never splitting a span). One window
    for a short doc; several for a long one. Used to keep each model call within a comfortable context size."""
    windows: list[list[Span]] = []
    cur: list[Span] = []
    for sp in spans:
        if cur and (sp.end - cur[0].start) > budget:
            windows.append(cur)
            cur = []
        cur.append(sp)
    if cur:
        windows.append(cur)
    return windows or [[]]


def _text_windows(text: str, size: int) -> list[str]:
    """Split raw text into ≤ `size`-char windows, breaking at a newline near the boundary where possible."""
    if len(text) <= size:
        return [text]
    windows: list[str] = []
    i, n = 0, len(text)
    while i < n:
        end = min(i + size, n)
        if end < n:
            nl = text.rfind("\n", i + size // 2, end)  # prefer a line break in the back half of the window
            if nl > i:
                end = nl
        windows.append(text[i:end])
        i = end
    return windows


def _long_doc_note(verb: str, covered: int, total: int, n_windows: int, truncated: bool) -> str | None:
    if n_windows <= 1:
        return None
    if truncated:
        return (f"Long document — {verb} the first {covered:,} of {total:,} characters "
                f"({n_windows} sections; capped at {settings.max_chunks}).")
    return f"{verb.capitalize()} across the full document — {total:,} characters in {n_windows} sections."


def summarize_text(text: str, *, kind: str = "text", provider: str | None = None) -> SummaryResult:
    """Run the full pipeline on already-extracted text. Deterministic except the drafting step."""
    provider = provider or settings.provider

    # 1) SANITIZE — before anything else can see the text. The model only ever gets `safe_text`.
    boundary: BoundaryResult = sanitize(text, default_policy())
    handled = len(boundary.spans)
    classes = boundary.classes

    # Fail-closed: nothing may leave → do not summarize.
    if boundary.safe_text is None:
        return SummaryResult(
            handled_count=handled,
            handled_classes=classes,
            decision=boundary.decision,
            provider=provider,
            kind=kind,
            source_chars=len(text),
            blocked=True,
            block_message=_BLOCK_MSG.format(classes=", ".join(classes) or "restricted content"),
        )

    safe_text = boundary.safe_text

    # 2) SPLIT the sanitized text into cited spans (over safe text, so citations are consistent with what
    #    the model saw and grounded against).
    spans: list[Span] = split_document(safe_text)

    # 3) DRAFT — the only model call. One pass for a short doc; MAP-REDUCE for a long one (a pass per window,
    #    then merge), so the whole document is covered — not just its start. Grounding runs against every span.
    windows = _span_windows(spans, settings.max_draft_chars)
    truncated = len(windows) > settings.max_chunks
    windows = windows[: settings.max_chunks]
    candidates = []
    for win in windows:
        wtext = safe_text[win[0].start : win[-1].end] if win else ""
        candidates += draft_candidates(wtext, win, provider)
    covered = windows[-1][-1].end if windows and windows[-1] else len(safe_text)
    note = _long_doc_note("summarized", covered, len(safe_text), len(windows), truncated)

    # 4) GROUND — cite-or-drop. Deterministic; the model never self-certifies.
    grounding = ground(candidates, spans, settings.ground_threshold)
    by_id = {s.id: s for s in spans}

    # 4b) REDUCE — dedupe repeated points (by text), keep the top-N by support, present in document order.
    seen: set[str] = set()
    uniq = []
    for gc in sorted(grounding.kept, key=lambda g: -g.support):
        key = gc.text.strip().lower()
        if key and key not in seen:
            seen.add(key)
            uniq.append(gc)
    top = uniq[: settings.summary_max_points]
    top.sort(key=lambda g: by_id[g.span_id].index if g.span_id in by_id else 0)

    # 5) RE-HYDRATE — LOCAL ONLY, for display. Restore the user's real values in both the claim and its citation.
    tmap = boundary.token_map
    claims = [
        Claim(
            text=rehydrate(gc.text, tmap),
            span_id=gc.span_id,
            span_text=rehydrate(by_id[gc.span_id].text, tmap) if gc.span_id in by_id else "",
            support=gc.support,
        )
        for gc in top
    ]
    # Surface a few withheld points for transparency (not the full — possibly long — dropped set).
    withheld = [Withheld(text=rehydrate(d.text, tmap), reason=d.reason) for d in grounding.dropped[:8]]

    return SummaryResult(
        claims=claims,
        withheld=withheld,
        handled_count=handled,
        handled_classes=classes,
        decision=boundary.decision,
        provider=provider,
        kind=kind,
        source_chars=len(text),
        note=note,
    )


def summarize_document(filename: str, data: bytes | str, *, provider: str | None = None) -> SummaryResult:
    """Ingest a real file (or paste) → run the pipeline. Ingest errors propagate as `IngestError` (friendly)."""
    r: IngestResult = extract_text(filename, data)
    return summarize_text(r.text, kind=r.kind, provider=provider)


def summarize_paste(text: str, *, provider: str | None = None) -> SummaryResult:
    r = from_paste(text)
    return summarize_text(r.text, kind=r.kind, provider=provider)


# --- Copilot: "Ask this document" — a grounded answer or an honest abstention -------------------------


@dataclass(frozen=True)
class AnswerResult:
    query: str = ""
    answer: str | None = None                # the grounded answer, re-hydrated for local display
    citations: list[Claim] = field(default_factory=list)   # the passages that support it (re-hydrated)
    handled_count: int = 0
    handled_classes: list[str] = field(default_factory=list)
    decision: str = "clear"
    provider: str = "stub"
    kind: str = "text"
    source_chars: int = 0
    answered: bool = False                   # True → a grounded answer; False → abstained/blocked
    abstained: bool = False                  # the document doesn't contain the answer
    abstain_reason: str | None = None
    blocked: bool = False                    # the boundary kept the content local (never-egress)
    block_message: str | None = None

    @property
    def handled_note(self) -> str:
        n = self.handled_count
        if n == 0:
            return "No sensitive items detected"
        return f"{n} sensitive {'item' if n == 1 else 'items'} handled before the model"


_ABSTAIN = "I couldn't find an answer to that in your document. Try rephrasing, or ask about something the document covers."


def _retrieve(safe_query: str, spans: list[Span]) -> list[tuple[Span, float]]:
    """Rank passages by question↔passage content-token overlap (the same deterministic support used for grounding).
    Returns the top-K above the relevance floor, most-relevant first. No model, no embeddings."""
    scored = [(sp, support(safe_query, sp.text)) for sp in spans]
    scored = [(sp, s) for sp, s in scored if s >= settings.copilot_min_relevance]
    scored.sort(key=lambda t: (-t[1], t[0].index))
    return scored[: settings.copilot_top_k]


def answer_question(text: str, query: str, *, kind: str = "text", provider: str | None = None) -> AnswerResult:
    """Answer a plain-language question strictly from the user's document, with citations — or abstain.

    Trust posture identical to Summarize: the model only ever sees sanitized passages + the sanitized question;
    the answer must be grounded in a retrieved passage or we **abstain** (abstention over hallucination); tokens
    re-hydrate locally for display. A never-egress class blocks the whole thing (fail-closed).
    """
    provider = provider or settings.provider
    q = (query or "").strip()

    # Sanitize BOTH the document and the question before anything can leave.
    doc = sanitize(text, default_policy())
    ques = sanitize(q, default_policy())
    handled = len(doc.spans) + len(ques.spans)
    classes = sorted(set(doc.classes) | set(ques.classes))
    base = dict(
        query=q, handled_count=handled, handled_classes=classes, decision=doc.decision,
        provider=provider, kind=kind, source_chars=len(text),
    )

    if doc.safe_text is None or ques.safe_text is None:
        which = "document" if doc.safe_text is None else "question"
        return AnswerResult(**{**base, "decision": doc.decision if doc.safe_text is None else ques.decision,
                               "blocked": True,
                               "block_message": _BLOCK_MSG.format(classes=", ".join(classes) or "restricted content")
                               + f" (the {which} contains data that must stay on your device.)"})

    safe_text, safe_query = doc.safe_text, ques.safe_text
    tmap = {**doc.token_map, **ques.token_map}
    spans = split_document(safe_text)

    # RETRIEVE relevant passages; nothing relevant → abstain before the model sees anything.
    retrieved = _retrieve(safe_query, spans)
    if not retrieved:
        return AnswerResult(**{**base, "answered": False, "abstained": True,
                               "abstain_reason": "No passage in the document matched the question.",
                               "answer": _ABSTAIN})

    ranked_spans = [sp for sp, _ in retrieved]
    raw = draft_answer(safe_query, ranked_spans, provider)

    # The model may abstain explicitly; or the answer may fail to ground → abstain (never show an ungrounded answer).
    grounded_ok = raw != NOT_IN_DOCUMENT and support(raw, " ".join(sp.text for sp in ranked_spans)) >= settings.ground_threshold
    if not grounded_ok:
        return AnswerResult(**{**base, "answered": False, "abstained": True,
                               "abstain_reason": ("the model reported the answer isn't in the document"
                                                  if raw == NOT_IN_DOCUMENT else
                                                  "the drafted answer wasn't supported by any passage — withheld"),
                               "answer": _ABSTAIN})

    # Cite the retrieved passages that actually support the answer; re-hydrate everything for local display.
    cites = [
        Claim(text=rehydrate(sp.text, tmap), span_id=sp.id, span_text=rehydrate(sp.text, tmap),
              support=round(support(raw, sp.text), 4))
        for sp in ranked_spans if support(raw, sp.text) > 0
    ]
    return AnswerResult(**{**base, "answered": True, "answer": rehydrate(raw, tmap), "citations": cites})


def answer_document(filename: str, data: bytes | str, query: str, *, provider: str | None = None) -> AnswerResult:
    r: IngestResult = extract_text(filename, data)
    return answer_question(r.text, query, kind=r.kind, provider=provider)


def answer_paste(text: str, query: str, *, provider: str | None = None) -> AnswerResult:
    r = from_paste(text)
    return answer_question(r.text, query, kind=r.kind, provider=provider)


# --- Draft: a grounded memo/brief from the document — cite-or-block, no prompt ------------------------


@dataclass(frozen=True)
class DraftOutcome:
    kind_slug: str = ""
    kind_label: str = ""
    title: str = ""
    sections: list = field(default_factory=list)   # DraftSection (re-hydrated text + Claim citations)
    omitted: list = field(default_factory=list)     # headings dropped (optional, couldn't ground)
    markdown: str = ""                              # the assembled memo (for copy/export)
    handled_count: int = 0
    handled_classes: list = field(default_factory=list)
    decision: str = "clear"
    provider: str = "stub"
    doc_kind: str = "text"
    source_chars: int = 0
    blocked: bool = False
    block_message: str | None = None
    note: str | None = None

    @property
    def handled_note(self) -> str:
        n = self.handled_count
        if n == 0:
            return "No sensitive items detected"
        return f"{n} sensitive {'item' if n == 1 else 'items'} handled before the model"


def _doc_title(safe_text: str, tmap: dict) -> str:
    """A memo title from the document's first non-empty line (re-hydrated for local display), trimmed."""
    for line in safe_text.splitlines():
        line = line.strip()
        if line:
            t = rehydrate(line, tmap)
            return (t[:70].rstrip() + "…") if len(t) > 70 else t
    return ""


# Draft grounds each section on the document's most information-dense passages (like Summarize), not on the
# section's meta-question (which shares no vocabulary with an arbitrary document). The model answers each section
# over those; a section it can't ground is omitted/blocked.
_DRAFT_MIN_TOKENS = 4
_DRAFT_SALIENT_K = 8


def _salient_spans(spans: list[Span]) -> list[Span]:
    scored = [(len(content_tokens(sp.text)), sp) for sp in spans]
    scored = [(n, sp) for n, sp in scored if n >= _DRAFT_MIN_TOKENS]
    scored.sort(key=lambda t: (-t[0], t[1].index))
    top = [sp for _, sp in scored[:_DRAFT_SALIENT_K]]
    return sorted(top, key=lambda sp: sp.index)  # emit in document order


def _section_grounder(salient: list[Span], tmap: dict, provider: str):
    """Return a `ground(section, index) -> GroundedSection | None`. Both providers go through `draft_answer`
    (so the model-only-sees-safe-text invariant is uniform and testable); the passages are rotated per section so
    the offline stub yields a distinct salient passage per section. A section that can't ground returns None."""

    def ground(sec, i: int) -> GroundedSection | None:
        if not salient:
            return None
        k = i % len(salient)
        rotated = salient[k:] + salient[:k]          # stub reads passage 0 → a distinct salient span per section
        raw = draft_section(sec.heading, sec.query, rotated, provider)
        if raw == NOT_IN_DOCUMENT:
            return None
        if support(raw, " ".join(sp.text for sp in salient)) < settings.ground_threshold:
            return None
        cites = [
            Claim(text=rehydrate(sp.text, tmap), span_id=sp.id, span_text=rehydrate(sp.text, tmap),
                  support=round(support(raw, sp.text), 4))
            for sp in salient if support(raw, sp.text) > 0
        ][:3]
        if not cites:  # grounded overall but nothing single-span attributable → cite the best-supporting span
            best = max(salient, key=lambda sp: support(raw, sp.text))
            cites = [Claim(text=rehydrate(best.text, tmap), span_id=best.id, span_text=rehydrate(best.text, tmap),
                           support=round(support(raw, best.text), 4))]
        return GroundedSection(text=rehydrate(raw, tmap), citations=cites)

    return ground


def draft_text(text: str, kind_slug: str | None = None, *, doc_kind: str = "text",
               provider: str | None = None) -> DraftOutcome:
    """Build a grounded memo/brief of the chosen kind from the document. Every section is document-supported or it
    is omitted; a required section that can't ground **blocks** the draft (never fabricates). Same trust posture:
    the model only ever sees sanitized passages; sections re-hydrate locally."""
    provider = provider or settings.provider
    kind = get_kind(kind_slug) or default_kind()
    doc = sanitize(text, default_policy())
    base = dict(
        kind_slug=kind.slug, kind_label=kind.label, handled_count=len(doc.spans), handled_classes=doc.classes,
        decision=doc.decision, provider=provider, doc_kind=doc_kind, source_chars=len(text),
    )

    if doc.safe_text is None:
        return DraftOutcome(**base, blocked=True,
                            block_message=_BLOCK_MSG.format(classes=", ".join(doc.classes) or "restricted content"))

    spans = split_document(doc.safe_text)
    salient = _salient_spans(spans)
    ground = _section_grounder(salient, doc.token_map, provider)
    result = assemble(kind, _doc_title(doc.safe_text, doc.token_map), ground)

    if result.blocked:
        return DraftOutcome(**base, blocked=True,
                            block_message=(f"Couldn't build a grounded {kind.label.lower()} — {result.block_reason}. "
                                           "The tool won't fabricate; try a different draft kind or document."))
    return DraftOutcome(**base, title=result.title, sections=result.sections, omitted=result.omitted,
                        markdown=result.text)


def draft_document(filename: str, data: bytes | str, kind_slug: str | None = None, *,
                   provider: str | None = None) -> DraftOutcome:
    r: IngestResult = extract_text(filename, data)
    return draft_text(r.text, kind_slug, doc_kind=r.kind, provider=provider)


def draft_paste(text: str, kind_slug: str | None = None, *, provider: str | None = None) -> DraftOutcome:
    r = from_paste(text)
    return draft_text(r.text, kind_slug, doc_kind=r.kind, provider=provider)


# --- Extractor: pull the fields you need into a clean, typed table — flag the uncertain, never guess -------------


@dataclass(frozen=True)
class ExtractOutcome:
    fieldset_slug: str = ""
    fieldset_label: str = ""
    items: list = field(default_factory=list)      # ExtractedItem (re-hydrated label/value + confidence + status)
    handled_count: int = 0
    handled_classes: list = field(default_factory=list)
    decision: str = "clear"
    provider: str = "stub"
    doc_kind: str = "text"
    source_chars: int = 0
    flagged_count: int = 0
    empty: bool = False
    empty_note: str | None = None
    note: str | None = None
    blocked: bool = False
    block_message: str | None = None

    @property
    def needs_review(self) -> bool:
        return self.flagged_count > 0

    @property
    def handled_note(self) -> str:
        n = self.handled_count
        if n == 0:
            return "No sensitive items detected"
        return f"{n} sensitive {'item' if n == 1 else 'items'} handled before the model"


def extract_fields(text: str, fieldset_slug: str | None = None, *, doc_kind: str = "text",
                   provider: str | None = None) -> ExtractOutcome:
    """Pull typed items of the chosen field-set from the document into a table. Each value is **type-validated** and
    **confidence-gated** (`min(validation, model)`); a value that fails validation or scores low is **flagged for
    review**, never silently trusted or guessed. Same trust posture: the model only sees sanitized text; the
    extracted values re-hydrate locally."""
    provider = provider or settings.provider
    fs = get_fieldset(fieldset_slug) or default_fieldset()
    doc = sanitize(text, default_policy())
    base = dict(
        fieldset_slug=fs.slug, fieldset_label=fs.label, handled_count=len(doc.spans), handled_classes=doc.classes,
        decision=doc.decision, provider=provider, doc_kind=doc_kind, source_chars=len(text),
    )

    if doc.safe_text is None:
        return ExtractOutcome(**base, blocked=True,
                              block_message=_BLOCK_MSG.format(classes=", ".join(doc.classes) or "restricted content"))

    safe_text = doc.safe_text
    # One pass for a short doc; MAP-REDUCE for a long one (extract per window, then merge) so fields from the WHOLE
    # document are caught — not just its start.
    windows = _text_windows(safe_text, settings.max_draft_chars)
    truncated = len(windows) > settings.max_chunks
    windows = windows[: settings.max_chunks]
    raw_items: list[dict] = []
    for w in windows:
        raw_items += extract_items(w, fs, provider)
    covered = sum(len(w) for w in windows)
    note = _long_doc_note("extracted", covered, len(safe_text), len(windows), truncated)

    # Merge: dedupe by (label, value); cap the table so a huge doc can't produce a runaway list.
    tmap = doc.token_map
    seen: set[tuple[str, str]] = set()
    items = []
    for it in raw_items:
        label, value = rehydrate(it["label"], tmap), rehydrate(it["value"], tmap)
        key = (label.strip().lower(), value.strip())
        if not value.strip() or key in seen:
            continue
        seen.add(key)
        items.append(score_item(label, value, fs.item_type, bool(it.get("uncertain", False)),
                                threshold=settings.extract_threshold))
        if len(items) >= settings.extract_max_items:
            break

    if not items:
        return ExtractOutcome(**base, empty=True, empty_note=fs.empty_note, note=note)
    return ExtractOutcome(**base, items=items, flagged_count=sum(1 for it in items if it.status == "flagged"),
                          note=note)


def extract_document(filename: str, data: bytes | str, fieldset_slug: str | None = None, *,
                     provider: str | None = None) -> ExtractOutcome:
    r: IngestResult = extract_text(filename, data)
    return extract_fields(r.text, fieldset_slug, doc_kind=r.kind, provider=provider)


def extract_paste(text: str, fieldset_slug: str | None = None, *, provider: str | None = None) -> ExtractOutcome:
    r = from_paste(text)
    return extract_fields(r.text, fieldset_slug, doc_kind=r.kind, provider=provider)


# --- Compare: two documents, side by side — rules detect the differences, the model never decides --------------


@dataclass(frozen=True)
class CompareRow:
    field: str
    a: str
    b: str
    status: str          # "match" | "differ" | "only_a" | "only_b"
    rule: str = ""
    severity: str = ""
    note: str = ""       # a grounded, decision-free explanation (for a difference)


@dataclass(frozen=True)
class CompareOutcome:
    fieldset_slug: str = ""
    fieldset_label: str = ""
    rows: list = field(default_factory=list)
    n_differ: int = 0
    n_match: int = 0
    handled_count: int = 0
    handled_classes: list = field(default_factory=list)
    provider: str = "stub"
    doc_a_kind: str = "text"
    doc_b_kind: str = "text"
    doc_a_chars: int = 0
    doc_b_chars: int = 0
    empty: bool = False
    empty_note: str | None = None
    blocked: bool = False
    block_message: str | None = None

    @property
    def handled_note(self) -> str:
        n = self.handled_count
        if n == 0:
            return "No sensitive items detected"
        return f"{n} sensitive {'item' if n == 1 else 'items'} handled before the model"


_ALIGN_THRESHOLD = 0.62


def _align_labels(items_a: list[tuple[str, str]], items_b: list[tuple[str, str]]):
    """Greedy fuzzy align two label/value lists by label similarity (the two docs were extracted independently, so
    their labels rarely match exactly). Returns (pairs, only_a, only_b)."""
    used_b: set[int] = set()
    pairs, only_a = [], []
    for la, va in items_a:
        best_j, best_r = -1, 0.0
        for j, (lb, _vb) in enumerate(items_b):
            if j in used_b:
                continue
            r = SequenceMatcher(None, la.lower(), lb.lower()).ratio()
            if r > best_r:
                best_r, best_j = r, j
        if best_j >= 0 and best_r >= _ALIGN_THRESHOLD:
            used_b.add(best_j)
            pairs.append((la, va, items_b[best_j][1]))
        else:
            only_a.append((la, va))
    only_b = [items_b[j] for j in range(len(items_b)) if j not in used_b]
    return pairs, only_a, only_b


def _uniq(name: str, used: set[str]) -> str:
    key, i = name, 2
    while key in used:
        key, i = f"{name} ({i})", i + 1
    used.add(key)
    return key


def compare_two(text_a: str, text_b: str, fieldset_slug: str | None = None, *,
                doc_a_kind: str = "text", doc_b_kind: str = "text", provider: str | None = None) -> CompareOutcome:
    """Pull the chosen field-set from BOTH documents (each via the Extractor pipeline — sanitized, re-hydrated),
    align the items by label, and compare the values **type-aware** (money cent-tolerance · dates normalized ·
    strings fuzzy · missing-on-one-side). The rules detect every difference; the explanation never decides which
    document is right. The model is used only for the two extractions; the comparison itself is deterministic."""
    provider = provider or settings.provider
    fs = get_fieldset(fieldset_slug) or default_fieldset()
    out_a = extract_fields(text_a, fs.slug, doc_kind=doc_a_kind, provider=provider)
    out_b = extract_fields(text_b, fs.slug, doc_kind=doc_b_kind, provider=provider)
    base = dict(
        fieldset_slug=fs.slug, fieldset_label=fs.label,
        handled_count=out_a.handled_count + out_b.handled_count,
        handled_classes=sorted(set(out_a.handled_classes) | set(out_b.handled_classes)),
        provider=provider, doc_a_kind=out_a.doc_kind, doc_b_kind=out_b.doc_kind,
        doc_a_chars=out_a.source_chars, doc_b_chars=out_b.source_chars,
    )

    if out_a.blocked or out_b.blocked:
        which = "first" if out_a.blocked else "second"
        return CompareOutcome(**base, blocked=True,
                              block_message=(f"The {which} document contains data that must stay on your device, "
                                             "so the comparison was not run."))

    items_a = [(it.label, it.value) for it in out_a.items]
    items_b = [(it.label, it.value) for it in out_b.items]
    if not items_a and not items_b:
        return CompareOutcome(**base, empty=True,
                              empty_note=f"Couldn't find any {fs.label.lower()} in either document to compare.")

    pairs, only_a, only_b = _align_labels(items_a, items_b)
    ftype = CompareFieldType(fs.item_type.value)
    used: set[str] = set()
    fields, a_dict, b_dict = [], {}, {}
    for la, va, vb in pairs:
        k = _uniq(la, used); fields.append(CompareField(k, ftype)); a_dict[k] = va; b_dict[k] = vb
    for la, va in only_a:
        k = _uniq(la, used); fields.append(CompareField(k, ftype)); a_dict[k] = va
    for lb, vb in only_b:
        k = _uniq(lb, used); fields.append(CompareField(k, ftype)); b_dict[k] = vb

    schema = CompareSchema(fs.slug, tuple(fields))
    discreps = {d.field: d for d in compare(schema, a_dict, b_dict)}
    rows = []
    for f in fields:
        av, bv = a_dict.get(f.name), b_dict.get(f.name)
        d = discreps.get(f.name)
        if d is None:
            rows.append(CompareRow(f.name, str(av or ""), str(bv or ""), "match"))
        elif d.rule == "missing_on_one_side":
            status = "only_a" if d.b is None else "only_b"
            rows.append(CompareRow(f.name, str(av or ""), str(bv or ""), status, d.rule, d.severity, explain_stub(d).text))
        else:
            rows.append(CompareRow(f.name, str(av or ""), str(bv or ""), "differ", d.rule, d.severity, explain_stub(d).text))

    rows.sort(key=lambda r: (0 if r.status != "match" else 1, r.field.lower()))   # differences first
    return CompareOutcome(**base, rows=rows,
                          n_differ=sum(1 for r in rows if r.status != "match"),
                          n_match=sum(1 for r in rows if r.status == "match"))


def _ingest_side(filename: str | None, data: bytes | None, paste: str | None) -> IngestResult:
    if data is not None:
        return extract_text(filename or "document", data)
    return from_paste(paste or "")


def compare_inputs(a_filename, a_data, a_paste, b_filename, b_data, b_paste,
                   fieldset_slug: str | None = None, *, provider: str | None = None) -> CompareOutcome:
    """Resolve each side (file or paste) → text, then compare. `IngestError` propagates (friendly)."""
    ra = _ingest_side(a_filename, a_data, a_paste)
    rb = _ingest_side(b_filename, b_data, b_paste)
    return compare_two(ra.text, rb.text, fieldset_slug, doc_a_kind=ra.kind, doc_b_kind=rb.kind, provider=provider)
