"""The Extractor tool — "Extract fields" (Suver's 4th and final Documents tool).

Drop a document (or paste), **pick a field-set** (Key facts · Dates & deadlines · People & contacts · Amounts &
totals) → the fields you need in a **clean, typed table**, with the **uncertain ones flagged**. The signature move
(from the `document-structured-extractor` engine): **confidence = min(validation, model)** — every value is
type-validated deterministically, and anything that fails validation or scores low is **flagged for review, never
guessed**. Same trust posture (the model only sees sanitized text; values re-hydrate locally). It reuses the
contract's `choice`/`options` (added for Draft) — a pick, not a prompt — so no new plumbing was needed.
"""

from __future__ import annotations

from app._engines.extract import all_fieldsets, default_fieldset
from app.ingest import IngestError
from app.pipeline import extract_document, extract_paste
from app.tools import Tool, ToolError, ToolInput, ToolOutput, register


def run(inp: ToolInput) -> ToolOutput:
    if inp.is_empty:
        raise ToolError("Add a document or paste some text to extract from.")
    fs_slug = inp.choice or default_fieldset().slug
    try:
        if inp.data is not None:
            result = extract_document(inp.filename or "document", inp.data, fs_slug)
        else:
            result = extract_paste(inp.paste or "", fs_slug)
    except IngestError as e:
        raise ToolError(str(e)) from e
    return ToolOutput(result=result, template="_extract_result.html")


EXTRACTOR = register(
    Tool(
        slug="extractor",
        name="Extract fields",
        blurb="Drop a document and pull the fields you need into a clean, typed table — the uncertain ones flagged.",
        icon="🧾",
        accepts="PDF · DOCX · TXT · MD · or paste",
        action_label="Extract",
        run=run,
        status="live",
        tags=("Documents", "Typed", "Flags the uncertain"),
        sample_text=("INVOICE #4471. Bill to: Dana Reyes. Invoice date: May 3, 2026. Due date: June 2, 2026. "
                     "Subtotal $4,000. Tax $320. Total due $4,320. Payment terms: net 30 days."),
        options=tuple((fs.slug, fs.label) for fs in all_fieldsets()),
        choice_label="What to pull",
    )
)
