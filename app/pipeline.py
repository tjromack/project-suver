"""The tool pipeline: ingest → **sanitize** → split → **draft(LLM)** → **ground** → re-hydrate → result.

This is where the composition lives. The invariant that makes Suver safe on real data: **the model only ever
sees `BoundaryResult.safe_text`** — sanitize runs before the drafter, the token map stays local, and re-hydration
happens only when building the view. The invariant has a test (`tests/test_sanitize_flow.py`). Every displayed
claim cites a source span or it is withheld (cite-or-drop; `tests/test_pipeline.py`).

Fail-closed: if the boundary decides `route_local`/`block`, `safe_text` is `None` — nothing may leave, so we do
**not** summarize; we tell the user their document stays on-device instead.
"""

from __future__ import annotations

import re
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
from app.provider import (
    NOT_IN_DOCUMENT,
    classify_messages,
    draft_answer,
    draft_candidates,
    draft_reply,
    draft_section,
    extract_action_items,
    extract_items,
    narrate_table,
    plan_query,
)
from app.sessions import ConverseTurn, create_session, get_session
from app.table import ColumnProfile, TableData, parse_table, to_number


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


def _answer_over_spans(spans: list[Span], safe_query: str, tmap: dict, provider: str,
                       *, fallback_query: str | None = None, context: list[str] | None = None):
    """Answer `safe_query` from already-sanitized spans → (answered, answer_text, citations). Retrieve on the
    question alone first; only if that finds nothing (an **elliptical** follow-up) fall back to `fallback_query`
    (the question + prior-question context — *history resolves the query*). `context` (recent prior questions,
    already sanitized) is handed to the model so a referential follow-up's pronoun resolves — retrieval finds the
    right passage, context lets the model understand the question. The model answers from the retrieved passages or
    we abstain. Shared by Copilot (one-shot, no context) and Converse (multi-turn)."""
    retrieved = _retrieve(safe_query, spans)
    if not retrieved and fallback_query:
        retrieved = _retrieve(fallback_query, spans)   # elliptical follow-up → resolve with prior questions
    if not retrieved:
        return False, _ABSTAIN, []                     # no vocabulary match → abstain (over hallucination)
    ranked = [sp for sp, _ in retrieved]
    raw = draft_answer(safe_query, ranked, provider, context=context)
    if raw == NOT_IN_DOCUMENT or support(raw, " ".join(sp.text for sp in ranked)) < settings.ground_threshold:
        return False, _ABSTAIN, []
    cites = [
        Claim(text=rehydrate(sp.text, tmap), span_id=sp.id, span_text=rehydrate(sp.text, tmap),
              support=round(support(raw, sp.text), 4))
        for sp in ranked if support(raw, sp.text) > 0
    ]
    return True, rehydrate(raw, tmap), cites


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

    tmap = {**doc.token_map, **ques.token_map}
    spans = split_document(doc.safe_text)

    answered, answer_text, cites = _answer_over_spans(spans, ques.safe_text, tmap, provider)
    if not answered:
        return AnswerResult(**{**base, "answered": False, "abstained": True,
                               "abstain_reason": "the document doesn't support an answer to that question",
                               "answer": answer_text})
    return AnswerResult(**{**base, "answered": True, "answer": answer_text, "citations": cites})


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


def _section_grounder(salient: list[Span], all_spans: list[Span], tmap: dict, provider: str):
    """Return a `ground(section, index) -> GroundedSection | None`. The model **reads** the salient passages
    (bounded, safe context — rotated per section so the offline stub yields a distinct span each time), but the
    section is then grounded and cited against the **whole document**. A synthesis section (e.g. an Overview) whose
    support is spread across the doc still grounds — while a section the document truly doesn't support is still
    omitted/blocked (cite-or-block). Both providers go through `draft_section` (so the model-only-sees-safe-text
    invariant is uniform and testable). A section that can't ground returns None."""

    def ground(sec, i: int) -> GroundedSection | None:
        if not salient:
            return None
        k = i % len(salient)
        rotated = salient[k:] + salient[:k]          # stub reads passage 0 → a distinct salient span per section
        raw = draft_section(sec.heading, sec.query, rotated, provider)
        if raw == NOT_IN_DOCUMENT:
            return None
        if support(raw, " ".join(sp.text for sp in all_spans)) < settings.ground_threshold:
            return None
        scored = sorted(((support(raw, sp.text), sp) for sp in all_spans), key=lambda t: -t[0])
        cites = [
            Claim(text=rehydrate(sp.text, tmap), span_id=sp.id, span_text=rehydrate(sp.text, tmap), support=round(sc, 4))
            for sc, sp in scored if sc > 0
        ][:3]
        if not cites:  # grounded overall but nothing single-span attributable → cite the best-supporting span
            best = scored[0][1]
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
    ground = _section_grounder(salient, spans, doc.token_map, provider)
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


# --- Converse: chat with a document — multi-turn, grounded; history resolves the query, retrieval answers it -----


@dataclass(frozen=True)
class ConverseResult:
    session_id: str = ""
    turns: list = field(default_factory=list)     # ConverseTurn (whole conversation, re-hydrated)
    handled_count: int = 0
    handled_classes: list = field(default_factory=list)
    decision: str = "clear"
    provider: str = "stub"
    doc_kind: str = "text"
    source_chars: int = 0
    answered_last: bool = False
    blocked: bool = False
    block_message: str | None = None
    expired: bool = False                         # the session was lost (restart / evicted) — re-add the document

    @property
    def handled_note(self) -> str:
        n = self.handled_count
        if n == 0:
            return "No sensitive items detected"
        return f"{n} sensitive {'item' if n == 1 else 'items'} handled before the model"


def _converse_answer(session, raw_question: str, ques) -> ConverseResult:
    """Answer one turn against the session's stored (safe) spans, append it, and return the whole conversation.
    Follow-up questions retrieve with recent prior questions as context (history resolves the query); the model
    still answers only from the retrieved passages (retrieval answers it)."""
    session.token_map.update(ques.token_map)         # merge this question's reversible tokens (local only)
    session.handled_count += len(ques.spans)
    safe_query = ques.safe_text
    prior = session.safe_questions[-2:]              # recent prior questions — the referent + conversation context
    fallback = (safe_query + " " + prior[-1]).strip() if prior else None
    answered, answer_text, cites = _answer_over_spans(
        session.spans, safe_query, session.token_map, session.provider,
        fallback_query=fallback, context=(prior or None))
    session.safe_questions.append(safe_query)
    session.turns.append(ConverseTurn(question=rehydrate(safe_query, session.token_map),
                                      answer=answer_text, citations=cites, answered=answered))
    return ConverseResult(
        session_id=session.id, turns=session.turns, handled_count=session.handled_count,
        handled_classes=session.handled_classes, decision=session.decision, provider=session.provider,
        doc_kind=session.doc_kind, source_chars=session.source_chars, answered_last=answered)


def converse_start(text: str, question: str, *, doc_kind: str = "text", provider: str | None = None) -> ConverseResult:
    """Start a conversation: sanitize + split the document ONCE, store it, and answer the first question."""
    provider = provider or settings.provider
    q = (question or "").strip()
    doc = sanitize(text, default_policy())
    ques = sanitize(q, default_policy())
    handled = len(doc.spans)
    classes = sorted(set(doc.classes) | set(ques.classes))
    if doc.safe_text is None or ques.safe_text is None:
        which = "document" if doc.safe_text is None else "question"
        return ConverseResult(handled_count=handled + len(ques.spans), handled_classes=classes,
                              decision=doc.decision, provider=provider, doc_kind=doc_kind, source_chars=len(text),
                              blocked=True,
                              block_message=(f"The {which} contains data that must stay on your device, so nothing "
                                             "was sent to the model."))
    session = create_session(
        spans=split_document(doc.safe_text), token_map=dict(doc.token_map), handled_count=handled,
        handled_classes=classes, decision=doc.decision, doc_kind=doc_kind, source_chars=len(text), provider=provider)
    return _converse_answer(session, q, ques)


def converse_followup(session_id: str, question: str, *, provider: str | None = None) -> ConverseResult:
    """Answer a follow-up question against an existing conversation's stored document."""
    session = get_session(session_id)
    if session is None:
        return ConverseResult(expired=True,
                              block_message="This conversation expired — please re-add the document to start again.")
    q = (question or "").strip()
    ques = sanitize(q, default_policy())
    if ques.safe_text is None:
        session.turns.append(ConverseTurn(question=q, answered=False,
                                          answer="That question contains data that can't leave your device, so it "
                                                 "wasn't sent. Try rephrasing it."))
        return ConverseResult(session_id=session.id, turns=session.turns, handled_count=session.handled_count,
                              handled_classes=session.handled_classes, decision=session.decision,
                              provider=session.provider, doc_kind=session.doc_kind, source_chars=session.source_chars,
                              answered_last=False)
    return _converse_answer(session, q, ques)


def converse_document(filename: str, data: bytes | str, question: str, *, provider: str | None = None) -> ConverseResult:
    r: IngestResult = extract_text(filename, data)
    return converse_start(r.text, question, doc_kind=r.kind, provider=provider)


def converse_paste(text: str, question: str, *, provider: str | None = None) -> ConverseResult:
    r = from_paste(text)
    return converse_start(r.text, question, doc_kind=r.kind, provider=provider)


# --- Communications · Meeting notes → action items: cite-or-drop the action; owner/due only if stated ------------


@dataclass(frozen=True)
class ActionItem:
    task: str            # the action, re-hydrated for local display
    owner: str = ""      # who is responsible — only if the notes state it (re-hydrated; may be a real name)
    due: str = ""        # the deadline — only if the notes state it
    span_id: str = ""    # the cited source span
    span_text: str = ""  # the cited span's text, re-hydrated
    support: float = 0.0


@dataclass(frozen=True)
class ActionsOutcome:
    items: list = field(default_factory=list)      # ActionItem
    withheld_count: int = 0                         # actions dropped because they didn't ground (cite-or-drop)
    handled_count: int = 0
    handled_classes: list = field(default_factory=list)
    decision: str = "clear"
    provider: str = "stub"
    doc_kind: str = "text"
    source_chars: int = 0
    empty: bool = False
    empty_note: str | None = None
    note: str | None = None
    blocked: bool = False
    block_message: str | None = None

    @property
    def handled_note(self) -> str:
        n = self.handled_count
        if n == 0:
            return "No sensitive items detected"
        return f"{n} sensitive {'item' if n == 1 else 'items'} handled before the model"


_WORD_RX = re.compile(r"[A-Za-z0-9]+")


def _stated(value: str, safe_text_lower: str) -> str:
    """Return `value` only if the document actually states it — else "". Guards against a **guessed** owner or
    deadline: a boundary name-token must appear verbatim; any other value must have ≥60% of its words present in
    the (sanitized) document. So an owner/due is shown only when the notes contain it, never inferred."""
    v = (value or "").strip()
    if not v:
        return ""
    if v.startswith("[") and v.endswith("]"):            # a boundary token (e.g. a name) — must be present verbatim
        return v if v.lower() in safe_text_lower else ""
    words = _WORD_RX.findall(v.lower())
    if not words:
        return ""
    hits = sum(1 for w in words if w in safe_text_lower)
    return v if hits / len(words) >= 0.6 else ""


def extract_actions(text: str, *, doc_kind: str = "text", provider: str | None = None) -> ActionsOutcome:
    """Turn meeting notes / a transcript into a clean list of action items — **who, what, by when** — grounded in the
    notes. Trust posture: the model only ever sees sanitized text (names arrive as boundary tokens); every action is
    **cite-or-drop** (it must ground to a source span, or it's withheld — never invented); an **owner or due is shown
    only if the notes state it** (`_stated`), never guessed; values re-hydrate locally. Map-reduces a long transcript."""
    provider = provider or settings.provider
    doc = sanitize(text, default_policy())
    base = dict(
        handled_count=len(doc.spans), handled_classes=doc.classes, decision=doc.decision,
        provider=provider, doc_kind=doc_kind, source_chars=len(text),
    )

    if doc.safe_text is None:
        return ActionsOutcome(**base, blocked=True,
                              block_message=_BLOCK_MSG.format(classes=", ".join(doc.classes) or "restricted content"))

    safe_text = doc.safe_text
    safe_lower = safe_text.lower()
    spans = split_document(safe_text)

    # One pass for short notes; MAP-REDUCE over windows for a long transcript so actions from the WHOLE thing are caught.
    windows = _text_windows(safe_text, settings.max_draft_chars)
    truncated = len(windows) > settings.max_chunks
    windows = windows[: settings.max_chunks]
    raw_items: list[dict] = []
    for w in windows:
        raw_items += extract_action_items(w, provider)
    covered = sum(len(w) for w in windows)
    note = _long_doc_note("scanned", covered, len(safe_text), len(windows), truncated)

    tmap = doc.token_map
    seen: set[str] = set()
    items, withheld = [], 0
    for it in raw_items:
        task = (it.get("task") or "").strip()
        if not task:
            continue
        best, best_s = None, 0.0
        for sp in spans:                                  # cite-or-drop: the action must ground to a source span
            s = support(task, sp.text)
            if s > best_s:
                best_s, best = s, sp
        if best is None or best_s < settings.ground_threshold:
            withheld += 1
            continue
        key = task.lower()
        if key in seen:
            continue
        seen.add(key)
        items.append(ActionItem(
            task=rehydrate(task, tmap),
            owner=rehydrate(_stated(it.get("owner", ""), safe_lower), tmap),
            due=rehydrate(_stated(it.get("due", ""), safe_lower), tmap),
            span_id=best.id, span_text=rehydrate(best.text, tmap), support=round(best_s, 4)))
        if len(items) >= settings.extract_max_items:
            break

    if not items:
        return ActionsOutcome(**base, empty=True,
                              empty_note="No action items were stated in these notes.", note=note)
    return ActionsOutcome(**base, items=items, withheld_count=withheld, note=note)


def actions_document(filename: str, data: bytes | str, *, provider: str | None = None) -> ActionsOutcome:
    r: IngestResult = extract_text(filename, data)
    return extract_actions(r.text, doc_kind=r.kind, provider=provider)


def actions_paste(text: str, *, provider: str | None = None) -> ActionsOutcome:
    r = from_paste(text)
    return extract_actions(r.text, doc_kind=r.kind, provider=provider)


# --- Communications · Triage messages: bucket each message by what it needs; ambiguous → 'review', never guessed ---

_TRIAGE_LABELS = {"needs_reply": "Needs reply", "action": "Action needed", "fyi": "FYI",
                  "ignore": "Can ignore", "unsure": "Review"}
_TRIAGE_ORDER = ("needs_reply", "action", "unsure", "fyi", "ignore")   # important buckets first
_TRIAGE_CATS = ("needs_reply", "action", "fyi", "ignore")


@dataclass(frozen=True)
class TriageItem:
    snippet: str                 # a short preview of the message, re-hydrated for display
    category: str                # needs_reply | action | fyi | ignore | unsure
    category_label: str
    reason: str = ""             # one line, drawn from the message (grounded) — why it's in that bucket
    confidence: float = 0.0


@dataclass(frozen=True)
class TriageOutcome:
    items: list = field(default_factory=list)      # TriageItem, important buckets first
    counts: dict = field(default_factory=dict)     # category -> count (for the summary line)
    handled_count: int = 0
    handled_classes: list = field(default_factory=list)
    decision: str = "clear"
    provider: str = "stub"
    doc_kind: str = "text"
    source_chars: int = 0
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


def _split_messages(text: str) -> list[str]:
    """Split a paste/thread into individual messages. Primary unit = a blank-line-separated block (the common
    'list of messages' / thread paste); a trivially short fragment (e.g. a lone signature) merges into the block
    above it. A single email with no blank lines is one message."""
    text = (text or "").strip()
    if not text:
        return []
    blocks = [b.strip() for b in re.split(r"\n\s*\n+", text) if b.strip()]
    merged: list[str] = []
    for b in blocks:
        if merged and len(b) < 15:
            merged[-1] = merged[-1] + "\n" + b
        else:
            merged.append(b)
    return merged or [text]


def _snippet(message: str, limit: int = 150) -> str:
    """A one-line preview: the message's non-empty lines joined (so a 'From:' header and the body both show), trimmed."""
    flat = " · ".join(ln.strip() for ln in message.splitlines() if ln.strip())
    return (flat[:limit].rstrip() + "…") if len(flat) > limit else flat


def triage_messages(text: str, *, doc_kind: str = "text", provider: str | None = None) -> TriageOutcome:
    """Sort a batch of messages by what each needs — **needs reply · action · FYI · ignore** — each with a one-line
    reason drawn from the message. Trust posture: the model only ever sees sanitized text; a classification below the
    confidence threshold is shown as **Review** (honest uncertainty over a confident wrong bucket); the reason must
    ground to the message or it's dropped (never invented); snippets/reasons re-hydrate locally."""
    provider = provider or settings.provider
    doc = sanitize(text, default_policy())
    base = dict(
        handled_count=len(doc.spans), handled_classes=doc.classes, decision=doc.decision,
        provider=provider, doc_kind=doc_kind, source_chars=len(text),
    )

    if doc.safe_text is None:
        return TriageOutcome(**base, blocked=True,
                             block_message=_BLOCK_MSG.format(classes=", ".join(doc.classes) or "restricted content"))

    messages = _split_messages(doc.safe_text)[: settings.triage_max_messages]
    if not messages:
        return TriageOutcome(**base, empty=True, empty_note="No messages to triage — paste one or more messages.")

    raw = classify_messages(messages, provider)
    tmap = doc.token_map
    items: list[TriageItem] = []
    for m, r in zip(messages, raw):
        try:
            conf = float(r.get("confidence", 0.0))
        except (TypeError, ValueError):
            conf = 0.0
        cat = (r.get("category") or "unsure").strip().lower()
        if cat not in _TRIAGE_CATS:
            cat = "unsure"
        if cat != "unsure" and conf < settings.triage_threshold:   # honest uncertainty → review, not a wrong bucket
            cat = "unsure"
        reason = (r.get("reason") or "").strip()
        if reason and support(reason, m) < settings.ground_threshold:   # reason must ground to the message
            reason = ""
        items.append(TriageItem(
            snippet=rehydrate(_snippet(m), tmap), category=cat, category_label=_TRIAGE_LABELS[cat],
            reason=rehydrate(reason, tmap), confidence=round(conf, 4)))

    items.sort(key=lambda it: (_TRIAGE_ORDER.index(it.category) if it.category in _TRIAGE_ORDER else 99))
    counts = {c: sum(1 for it in items if it.category == c) for c in _TRIAGE_ORDER}
    counts = {c: n for c, n in counts.items() if n}
    return TriageOutcome(**base, items=items, counts=counts)


def triage_document(filename: str, data: bytes | str, *, provider: str | None = None) -> TriageOutcome:
    r: IngestResult = extract_text(filename, data)
    return triage_messages(r.text, doc_kind=r.kind, provider=provider)


def triage_paste(text: str, *, provider: str | None = None) -> TriageOutcome:
    r = from_paste(text)
    return triage_messages(r.text, doc_kind=r.kind, provider=provider)


# --- Communications · Draft a reply: a grounded reply; unknowns → [placeholders]; invented specifics flagged -------

_REPLY_INTENTS = {
    "acknowledge": ("Acknowledge & confirm", "acknowledge the message and confirm receipt; warm and brief."),
    "answer": ("Answer their question", "answer the question(s) the message asks, using only what the message provides."),
    "decline": ("Politely decline", "politely decline or say no to what the message asks, with a courteous reason."),
    "request_info": ("Ask for more detail", "ask for the specific additional information you'd need to respond properly."),
    "follow_up": ("Say I'll follow up", "acknowledge and say you'll follow up, noting what you'll get back to them on."),
}


def reply_intents() -> list[tuple[str, str]]:
    """(slug, label) pairs for the intent `<select>` — a pick, not a prompt. The first is the default."""
    return [(slug, label) for slug, (label, _focus) in _REPLY_INTENTS.items()]


def _reply_intent(slug: str | None):
    return _REPLY_INTENTS.get((slug or "").strip()) or _REPLY_INTENTS["acknowledge"]


# A "specific" the reply must not invent: money, a clock time, or an ISO date. If one appears in the draft but not
# in the message, it's flagged "verify" (the model is told to use placeholders, so this is a backstop).
_SPECIFIC_RX = re.compile(
    r"(\$\s?\d[\d,]*(?:\.\d{2})?|\b\d{1,2}:\d{2}\s?(?:am|pm)?\b|\b\d{1,2}\s?(?:am|pm)\b|\b\d{4}-\d{2}-\d{2}\b)", re.I)


def _invented_specifics(draft: str, message: str) -> list[str]:
    msg_low = message.lower()
    found: list[str] = []
    for m in _SPECIFIC_RX.findall(draft):
        s = m.strip()
        if s and s.lower() not in msg_low and s not in found:
            found.append(s)
    return found


@dataclass(frozen=True)
class ReplyOutcome:
    intent_slug: str = ""
    intent_label: str = ""
    reply: str = ""                                 # the drafted reply, re-hydrated for local display
    placeholders: list = field(default_factory=list)   # bracketed [things to fill] the tool left for the user
    unverified: list = field(default_factory=list)     # specifics in the draft not found in the message (verify)
    handled_count: int = 0
    handled_classes: list = field(default_factory=list)
    decision: str = "clear"
    provider: str = "stub"
    doc_kind: str = "text"
    source_chars: int = 0
    blocked: bool = False
    block_message: str | None = None

    @property
    def handled_note(self) -> str:
        n = self.handled_count
        if n == 0:
            return "No sensitive items detected"
        return f"{n} sensitive {'item' if n == 1 else 'items'} handled before the model"


def draft_reply_text(text: str, intent_slug: str | None = None, *, doc_kind: str = "text",
                     provider: str | None = None) -> ReplyOutcome:
    """Draft a reply to a received message for a chosen **intent** (a pick, not a prompt). Trust posture: the model
    only ever sees the sanitized message; it **uses only the message's facts** and inserts **[placeholders]** for
    anything it doesn't know (never invents a date/number/name/commitment); the pipeline lists those placeholders and
    **flags any invented specific** (a money/time/date in the draft not in the message) for the user to verify. The
    reply re-hydrates locally (real names restored)."""
    provider = provider or settings.provider
    slug = (intent_slug or "acknowledge").strip() or "acknowledge"
    label, focus = _reply_intent(slug)
    if slug not in _REPLY_INTENTS:
        slug = "acknowledge"
    doc = sanitize(text, default_policy())
    base = dict(
        intent_slug=slug, intent_label=label, handled_count=len(doc.spans), handled_classes=doc.classes,
        decision=doc.decision, provider=provider, doc_kind=doc_kind, source_chars=len(text),
    )

    if doc.safe_text is None:
        return ReplyOutcome(**base, blocked=True,
                            block_message=_BLOCK_MSG.format(classes=", ".join(doc.classes) or "restricted content"))

    safe_msg = doc.safe_text
    raw = draft_reply(safe_msg, slug, focus, provider)     # the model sees only the sanitized message
    unverified = _invented_specifics(raw, safe_msg)        # backstop: specifics in the draft not in the message
    reply = rehydrate(raw, doc.token_map)                  # restore real names locally; [placeholders] survive
    placeholders = re.findall(r"\[([^\]]+)\]", reply)      # boundary tokens are already re-hydrated → these are fills
    return ReplyOutcome(**base, reply=reply, placeholders=placeholders, unverified=unverified)


def reply_document(filename: str, data: bytes | str, intent_slug: str | None = None, *,
                   provider: str | None = None) -> ReplyOutcome:
    r: IngestResult = extract_text(filename, data)
    return draft_reply_text(r.text, intent_slug, doc_kind=r.kind, provider=provider)


def reply_paste(text: str, intent_slug: str | None = None, *, provider: str | None = None) -> ReplyOutcome:
    r = from_paste(text)
    return draft_reply_text(r.text, intent_slug, doc_kind=r.kind, provider=provider)


# --- Data & Analysis · Ask your spreadsheet: the model plans, the CODE computes (numbers always right, cells cited) --

_AGG_LABEL = {"sum": "Total", "avg": "Average", "min": "Minimum", "max": "Maximum"}
_SPREADSHEET_ABSTAIN = ("I couldn't answer that from this table — try asking about one of its columns "
                        "(a total/average/count, or a lookup).")


@dataclass(frozen=True)
class AskTableOutcome:
    query: str = ""
    answer: str | None = None                       # the computed answer, in words
    operation: str = ""                             # a plain description of what was computed (auditable)
    columns: list = field(default_factory=list)     # header row of the supporting rows (or the grouped table)
    rows: list = field(default_factory=list)        # the supporting rows (the cells the answer came from)
    grouped: bool = False                           # True → rows are group→value results, not raw source rows
    n_matched: int = 0                              # how many rows the operation covered
    handled_count: int = 0
    handled_classes: list = field(default_factory=list)
    decision: str = "clear"
    provider: str = "stub"
    doc_kind: str = "text"
    source_chars: int = 0
    n_table_rows: int = 0
    n_table_cols: int = 0
    answered: bool = False
    abstained: bool = False
    blocked: bool = False
    block_message: str | None = None
    empty: bool = False
    empty_note: str | None = None

    @property
    def handled_note(self) -> str:
        n = self.handled_count
        if n == 0:
            return "No sensitive items detected"
        return f"{n} sensitive {'item' if n == 1 else 'items'} handled before the model"


def _fmt_num(v: float) -> str:
    """Render a computed number cleanly (drop a trailing .0; thousands separators)."""
    if v == int(v):
        return f"{int(v):,}"
    return f"{v:,.2f}"


def _filter_indices(table: TableData, filt: dict | None) -> list[int]:
    """Row indices matching an optional {column, match, value} filter (eq/contains, case-insensitive)."""
    if not filt:
        return list(range(table.n_rows))
    ci = table.col_index(str(filt.get("column", "")))
    if ci < 0:
        return list(range(table.n_rows))
    val = str(filt.get("value", "")).strip().lower()
    match = filt.get("match", "eq")
    out = []
    for r_i, r in enumerate(table.rows):
        cell = (r[ci] if ci < len(r) else "").strip().lower()
        if (match == "contains" and val in cell) or (match != "contains" and cell == val):
            out.append(r_i)
    return out


def _aggregate(nums: list[float], agg: str):
    if not nums:
        return None
    return {"sum": sum(nums), "avg": sum(nums) / len(nums), "min": min(nums), "max": max(nums)}.get(agg)


def _execute_plan(table: TableData, plan: dict):
    """Run the model's PLAN deterministically over the local data → (answer, operation, matched_indices, grouped) or
    None to abstain. `grouped` is None for row ops, or (columns, rows) for a group-by result. The arithmetic happens
    here, never in the model — so the number is exact and traces to real rows."""
    if not isinstance(plan, dict) or plan.get("answerable") is False:
        return None
    op = str(plan.get("op") or "").lower()
    filt = plan.get("filter") if isinstance(plan.get("filter"), dict) else None
    where = ""
    if filt and table.col_index(str(filt.get("column", ""))) >= 0:
        where = f' where {filt.get("column")} {"contains" if filt.get("match") == "contains" else "="} "{filt.get("value")}"'
    idx = _filter_indices(table, filt)

    if op == "count":
        return (f"{len(idx):,}", f"Count of rows{where}", idx, None)

    if op == "aggregate":
        ci = table.col_index(str(plan.get("column", "")))
        if ci < 0 or ci not in table.numeric_cols:
            return None
        agg = str(plan.get("agg") or "sum").lower()
        val = _aggregate([n for i in idx if (n := table.numbers(ci)[i]) is not None], agg)
        if val is None:
            return None
        label = _AGG_LABEL.get(agg, agg.capitalize())
        n = sum(1 for i in idx if table.numbers(ci)[i] is not None)
        return (f"{label} of {table.headers[ci]}{where}: {_fmt_num(val)}",
                f"{label} of “{table.headers[ci]}”{where} — over {n} value(s)", idx, None)

    if op == "groupby":
        gci = table.col_index(str(plan.get("group_column", "")))
        agg = str(plan.get("agg") or "sum").lower()
        if gci < 0:
            return None
        nci = table.col_index(str(plan.get("column", "")))
        if agg != "count" and (nci < 0 or nci not in table.numeric_cols):
            return None
        groups: dict[str, list[int]] = {}
        for i in idx:
            key = (table.rows[i][gci] if gci < len(table.rows[i]) else "").strip() or "(blank)"
            groups.setdefault(key, []).append(i)
        results = []
        for key, members in groups.items():
            val = float(len(members)) if agg == "count" else \
                _aggregate([n for m in members if (n := table.numbers(nci)[m]) is not None], agg)
            if val is not None:
                results.append((key, val))
        if not results:
            return None
        order = str(plan.get("order") or "desc").lower()
        results.sort(key=lambda t: t[1], reverse=(order != "asc"))
        top = plan.get("top")
        num_name = "rows" if agg == "count" else table.headers[nci]
        gname = table.headers[gci]
        label = "Count" if agg == "count" else _AGG_LABEL.get(agg, agg.capitalize())
        cols = [gname, f"{label} of {num_name}"]
        grouped = (cols, [[k, _fmt_num(v)] for k, v in results])
        if top == 1:
            k, v = results[0]
            sup = "highest" if order != "asc" else "lowest"
            answer = f"{k} — {label.lower()} of {num_name} is {_fmt_num(v)} (the {sup} of {len(results)} {gname} groups)"
            operation = f"{label} of “{num_name}” by “{gname}”{where}, ranked {order} — top group"
            grouped = (cols, [[k, _fmt_num(v)]])
        else:
            answer = f"{label} of {num_name} by {gname}{where} — {len(results)} groups (see below)"
            operation = f"{label} of “{num_name}” grouped by “{gname}”{where}"
        return (answer, operation, idx, grouped)

    if op == "filter":
        if not idx:
            return None
        return (f"{len(idx):,} row(s) match{where}.", f"Rows{where}", idx, None)

    return None


def ask_table(text: str, query: str, *, doc_kind: str = "text", provider: str | None = None) -> AskTableOutcome:
    """Answer a plain question about a table by **planning with the model and computing in code**. The model only
    ever sees the sanitized **schema + a small sanitized sample** (never the full dataset) + the sanitized question,
    and returns a structured plan; the pipeline executes that plan deterministically over the local rows, so the
    number is exact and the answer shows the exact rows it used. Unanswerable → an honest abstention."""
    provider = provider or settings.provider
    q = (query or "").strip()
    table = parse_table(text)
    base = dict(query=q, provider=provider, doc_kind=doc_kind, source_chars=len(text))
    if table is None:
        return AskTableOutcome(**base, empty=True,
                               empty_note="That doesn't look like a table — add a CSV (or paste rows with a header).")
    base = dict(base, n_table_rows=table.n_rows, n_table_cols=table.n_cols)

    # The model sees only the sanitized schema + a small sanitized SAMPLE + the sanitized question — never all rows.
    schema = sanitize(table.schema_text(), default_policy())
    sample = sanitize(table.sample_text(settings.table_sample_rows), default_policy())
    ques = sanitize(q, default_policy())
    handled = len(schema.spans) + len(sample.spans) + len(ques.spans)
    classes = sorted(set(schema.classes) | set(sample.classes) | set(ques.classes))
    base = dict(base, handled_count=handled, handled_classes=classes, decision=ques.decision)
    if ques.safe_text is None:
        return AskTableOutcome(**base, blocked=True,
                               block_message="That question contains data that can't leave your device. Try rephrasing.")

    numeric_headers = [table.headers[i] for i in sorted(table.numeric_cols)]
    plan = plan_query(schema.safe_text or "", sample.safe_text or "", ques.safe_text,
                      list(table.headers), numeric_headers, provider)
    result = _execute_plan(table, plan) if plan else None
    if result is None:
        return AskTableOutcome(**base, answered=False, abstained=True, answer=_SPREADSHEET_ABSTAIN)

    answer, operation, idx, grouped = result
    if grouped is not None:                                # a group-by result → show the grouped table, not raw rows
        columns, rows = grouped
        return AskTableOutcome(**base, answered=True, answer=answer, operation=operation,
                               columns=columns, rows=rows[: settings.table_max_rows_shown],
                               n_matched=len(idx), grouped=True)
    show = idx[: settings.table_max_rows_shown]
    rows = [table.rows[i] for i in show]
    return AskTableOutcome(**base, answered=True, answer=answer, operation=operation,
                           columns=list(table.headers), rows=rows, n_matched=len(idx))


def ask_table_document(filename: str, data: bytes | str, query: str, *, provider: str | None = None) -> AskTableOutcome:
    r: IngestResult = extract_text(filename, data)
    return ask_table(r.text, query, doc_kind=r.kind, provider=provider)


def ask_table_paste(text: str, query: str, *, provider: str | None = None) -> AskTableOutcome:
    r = from_paste(text)
    return ask_table(r.text, query, doc_kind=r.kind, provider=provider)


# --- Data & Analysis · Summarize a spreadsheet: a computed profile + a grounded plain-language overview -------------


@dataclass(frozen=True)
class ProfileRow:
    name: str
    kind: str            # "number" | "text"
    stats: str           # a display-ready summary of the computed facts
    missing: int


@dataclass(frozen=True)
class DataSummaryOutcome:
    overview: str = ""                              # the plain-language narrative (model), re-hydrated
    profile: list = field(default_factory=list)     # ProfileRow per column (computed)
    n_rows: int = 0
    n_cols: int = 0
    n_numeric: int = 0
    handled_count: int = 0
    handled_classes: list = field(default_factory=list)
    decision: str = "clear"
    provider: str = "stub"
    doc_kind: str = "text"
    source_chars: int = 0
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


def _profile_stats(p: ColumnProfile) -> str:
    """A display-ready one-line summary of a column's computed profile."""
    if p.kind == "number":
        parts = []
        if p.minimum is not None:
            parts.append(f"min {_fmt_num(p.minimum)}")
        if p.maximum is not None:
            parts.append(f"max {_fmt_num(p.maximum)}")
        if p.mean is not None:
            parts.append(f"mean {_fmt_num(round(p.mean, 2))}")
        if p.total is not None:
            parts.append(f"total {_fmt_num(p.total)}")
        return " · ".join(parts) or "—"
    top = ", ".join(f"{v} ({c})" for v, c in (p.top or [])) or "—"
    return f"{p.distinct} distinct · top: {top}"


def _profile_text(profiles: list[ColumnProfile], n_rows: int) -> str:
    """The computed facts as text for the model to narrate (numbers already calculated — it must not recompute)."""
    lines = [f"{n_rows:,} rows, {len(profiles)} columns."]
    for p in profiles:
        miss = f", {p.missing} missing" if p.missing else ""
        lines.append(f'- "{p.name}" ({p.kind}): {_profile_stats(p)}{miss}')
    return "\n".join(lines)


def summarize_table(text: str, *, doc_kind: str = "text", provider: str | None = None) -> DataSummaryOutcome:
    """Summarize a table: compute a per-column **profile** deterministically, then have the model write a plain-language
    **overview** from that profile (it narrates, the code computes — every figure is calculated, not invented). The
    model only ever sees the sanitized profile + a sanitized sample, never the full data; the overview re-hydrates
    locally, the profile table shown alongside is the computed ground truth."""
    provider = provider or settings.provider
    table = parse_table(text)
    base = dict(provider=provider, doc_kind=doc_kind, source_chars=len(text))
    if table is None:
        return DataSummaryOutcome(**base, empty=True,
                                  empty_note="That doesn't look like a table — add a CSV (or paste rows with a header).")

    profiles = table.profile()
    prof_text = _profile_text(profiles, table.n_rows)

    # The model sees only the sanitized profile + a sanitized sample — never the full dataset.
    prof = sanitize(prof_text, default_policy())
    sample = sanitize(table.sample_text(settings.table_sample_rows), default_policy())
    handled = len(prof.spans) + len(sample.spans)
    classes = sorted(set(prof.classes) | set(sample.classes))
    tmap = {**prof.token_map, **sample.token_map}

    overview = rehydrate(narrate_table(prof.safe_text or prof_text, sample.safe_text or "",
                                       table.n_rows, table.n_cols, provider), tmap)
    display = [ProfileRow(name=p.name, kind=p.kind, stats=_profile_stats(p), missing=p.missing) for p in profiles]
    return DataSummaryOutcome(
        **base, overview=overview, profile=display, n_rows=table.n_rows, n_cols=table.n_cols,
        n_numeric=len(table.numeric_cols), handled_count=handled, handled_classes=classes, decision=prof.decision)


def summarize_table_document(filename: str, data: bytes | str, *, provider: str | None = None) -> DataSummaryOutcome:
    r: IngestResult = extract_text(filename, data)
    return summarize_table(r.text, doc_kind=r.kind, provider=provider)


def summarize_table_paste(text: str, *, provider: str | None = None) -> DataSummaryOutcome:
    r = from_paste(text)
    return summarize_table(r.text, doc_kind=r.kind, provider=provider)


# --- Data & Analysis · Chart your spreadsheet: bars computed from your rows — accurate by construction, no model ----


@dataclass(frozen=True)
class ChartBar:
    label: str           # the category (re-hydrated is unnecessary — never sent to a model; local only)
    value: str           # the computed aggregate, formatted
    pct: int             # bar width 0–100 (relative to the largest bar in this chart)


@dataclass(frozen=True)
class Chart:
    measure: str         # the numeric column charted
    category: str        # the category column grouped by
    agg: str             # "total"
    bars: list = field(default_factory=list)   # ChartBar, largest first
    n_groups: int = 0    # total groups (bars may be capped)


@dataclass(frozen=True)
class ChartOutcome:
    charts: list = field(default_factory=list)      # Chart per numeric measure
    category: str = ""
    n_rows: int = 0
    n_cols: int = 0
    doc_kind: str = "text"
    source_chars: int = 0
    empty: bool = False
    empty_note: str | None = None


def _pick_category(table: TableData) -> int:
    """The best column to group bars by: a TEXT column with 2–20 distinct values (and fewer distinct than rows —
    not an id). Prefer the fewest distinct (cleanest bars), leftmost on a tie. -1 if none is suitable."""
    best_i, best_d = -1, 999
    for i, _h in enumerate(table.headers):
        if i in table.numeric_cols:
            continue
        vals = {(r[i] if i < len(r) else "").strip() for r in table.rows if (r[i] if i < len(r) else "").strip()}
        d = len(vals)
        if 2 <= d <= 20 and d < table.n_rows and d < best_d:
            best_i, best_d = i, d
    return best_i


def chart_table(text: str, *, doc_kind: str = "text") -> ChartOutcome:
    """Build bar chart(s) from a table — for the primary categorical column, the **total** of each numeric column by
    category. Fully **deterministic and local**: the sums are computed from your rows and the chart is drawn from
    them, so it's accurate by construction — nothing is sent to a model at all."""
    table = parse_table(text)
    base = dict(doc_kind=doc_kind, source_chars=len(text))
    if table is None:
        return ChartOutcome(**base, empty=True,
                            empty_note="That doesn't look like a table — add a CSV (or paste rows with a header).")
    base = dict(base, n_rows=table.n_rows, n_cols=table.n_cols)

    ci = _pick_category(table)
    numeric = sorted(table.numeric_cols)[: settings.chart_max_measures]
    if ci < 0 or not numeric:
        note = ("This table doesn't have an obvious category to chart by — try **Ask your spreadsheet** or "
                "**Summarize a spreadsheet** instead.")
        return ChartOutcome(**base, empty=True, empty_note=note)

    cat_name = table.headers[ci]
    charts = []
    for nci in numeric:
        groups: dict[str, float] = {}
        for r_i, row in enumerate(table.rows):
            key = (row[ci] if ci < len(row) else "").strip() or "(blank)"
            v = table.numbers(nci)[r_i]
            if v is not None:
                groups[key] = groups.get(key, 0.0) + v
        if not groups:
            continue
        items = sorted(groups.items(), key=lambda t: -t[1])
        shown = items[: settings.chart_max_bars]
        top = shown[0][1] if shown and shown[0][1] > 0 else 1.0
        bars = [ChartBar(label=k, value=_fmt_num(v), pct=max(1, round(v / top * 100)) if v > 0 else 0)
                for k, v in shown]
        charts.append(Chart(measure=table.headers[nci], category=cat_name, agg="total", bars=bars, n_groups=len(items)))

    if not charts:
        return ChartOutcome(**base, empty=True, empty_note="No numeric values to chart by category.")
    return ChartOutcome(**base, charts=charts, category=cat_name)


def chart_table_document(filename: str, data: bytes | str) -> ChartOutcome:
    r: IngestResult = extract_text(filename, data)
    return chart_table(r.text, doc_kind=r.kind)


def chart_table_paste(text: str) -> ChartOutcome:
    r = from_paste(text)
    return chart_table(r.text, doc_kind=r.kind)
