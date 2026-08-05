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

from app._engines.boundary import BoundaryResult, default_policy, rehydrate, sanitize
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

    # 3) DRAFT — the only model call. Long docs: the drafter sees the leading portion (transparently noted);
    #    grounding still runs against every span so any cited point resolves.
    note = None
    draft_text = safe_text
    if len(safe_text) > settings.max_draft_chars:
        draft_text = safe_text[: settings.max_draft_chars]
        note = f"Long document — summarized the first {len(draft_text):,} of {len(safe_text):,} characters."
    draft_spans = [s for s in spans if s.start < len(draft_text)]
    candidates = draft_candidates(draft_text, draft_spans, provider)

    # 4) GROUND — cite-or-drop. Deterministic; the model never self-certifies.
    grounding = ground(candidates, spans, settings.ground_threshold)
    by_id = {s.id: s for s in spans}

    # 5) RE-HYDRATE — LOCAL ONLY, for display. Restore the user's real values in both the claim and its citation.
    tmap = boundary.token_map
    claims = [
        Claim(
            text=rehydrate(gc.text, tmap),
            span_id=gc.span_id,
            span_text=rehydrate(by_id[gc.span_id].text, tmap) if gc.span_id in by_id else "",
            support=gc.support,
        )
        for gc in grounding.kept
    ]
    withheld = [Withheld(text=rehydrate(d.text, tmap), reason=d.reason) for d in grounding.dropped]

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

    safe_text, note = doc.safe_text, None
    if len(safe_text) > settings.max_draft_chars:
        safe_text = safe_text[: settings.max_draft_chars]
        note = f"Long document — extracted from the first {len(safe_text):,} of {len(doc.safe_text):,} characters."

    raw_items = extract_items(safe_text, fs, provider)
    tmap = doc.token_map
    items = [
        score_item(rehydrate(it["label"], tmap), rehydrate(it["value"], tmap), fs.item_type,
                   bool(it.get("uncertain", False)), threshold=settings.extract_threshold)
        for it in raw_items
    ]
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
