"""The Draft tool — "Draft from a document" (Suver's 3rd Documents tool).

Drop a document (or paste), **pick a kind** (Summary memo · Plain-language explainer · Action items) → a
**grounded first draft**: a structured memo whose every section cites the document, or is omitted — a required
section that can't ground **blocks** the draft (cite-or-block; it never fabricates). Same trust posture as the
other tools (the model only ever sees sanitized text; sections re-hydrate locally). It proves the shell
generalizes a third way: this tool needs a **pick** (an output kind), so the contract's `options`/`choice` render
as a select — a pick, not a prompt.
"""

from __future__ import annotations

from app._engines.draft import all_kinds, default_kind
from app.ingest import IngestError
from app.pipeline import draft_document, draft_paste
from app.tools import Tool, ToolError, ToolInput, ToolOutput, register


def run(inp: ToolInput) -> ToolOutput:
    if inp.is_empty:
        raise ToolError("Add a document or paste some text to draft from.")
    kind_slug = inp.choice or default_kind().slug
    try:
        if inp.data is not None:
            result = draft_document(inp.filename or "document", inp.data, kind_slug)
        else:
            result = draft_paste(inp.paste or "", kind_slug)
    except IngestError as e:
        raise ToolError(str(e)) from e
    return ToolOutput(result=result, template="_draft_result.html")


DRAFT = register(
    Tool(
        slug="draft",
        name="Draft from a document",
        blurb="Turn a document into a grounded first draft — a memo, an explainer, or an action-items list.",
        icon="✍️",
        accepts="PDF · DOCX · TXT · MD · or paste",
        action_label="Draft",
        run=run,
        status="live",
        tags=("Documents", "Grounded", "Cite-or-block"),
        sample_text=("MASTER SERVICES AGREEMENT between Acme Corp and Northwind LLC. The initial term is two years, "
                     "beginning January 1, 2026. The agreement auto-renews for successive one-year terms unless either "
                     "party gives sixty (60) days written notice. Fees are $12,000 per month, net thirty days. Either "
                     "party may terminate for material breach on thirty (30) days notice. Governing law is the State "
                     "of New York. Liability is capped at the fees paid in the preceding twelve months."),
        sample_choice="contract-memo",
        options=tuple((k.slug, k.label) for k in all_kinds()),
        choice_label="What to make",
    )
)
