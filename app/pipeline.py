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
from app._engines.summarize import Span, ground, split_document, support
from app.config import settings
from app.ingest import IngestResult, extract_text, from_paste
from app.provider import NOT_IN_DOCUMENT, draft_answer, draft_candidates


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
