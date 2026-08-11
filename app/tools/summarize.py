"""The Summarize tool — Suver's first tool (Phase 5, DEC 006).

Drop a real document (or paste) → a **cited summary**: every key-point cites a source span; unsupported points are
withheld; sensitive data is sanitized before the model and re-hydrated locally. **3 clicks, no prompt, no config.**

The tool is thin: it maps the shell's `ToolInput` onto the pipeline and hands back the `SummaryResult` + its result
partial. All the trust behavior lives in `app/pipeline.py` (which every tool reuses) — that's the point of the
contract.
"""

from __future__ import annotations

from app.ingest import IngestError
from app.pipeline import summarize_document, summarize_paste
from app.tools import Tool, ToolError, ToolInput, ToolOutput, register


def run(inp: ToolInput) -> ToolOutput:
    if inp.is_empty:
        raise ToolError("Add a document or paste some text to summarize.")
    try:
        if inp.data is not None:
            result = summarize_document(inp.filename or "document", inp.data)
        else:
            result = summarize_paste(inp.paste or "")
    except IngestError as e:
        raise ToolError(str(e)) from e
    return ToolOutput(result=result, template="_summary_result.html")


SUMMARIZE = register(
    Tool(
        slug="summarize",
        name="Summarize",
        blurb="Drop a document and get a short, cited summary — every point traces to your source.",
        icon="📝",
        accepts="PDF · DOCX · TXT · MD · or paste",
        action_label="Summarize",
        run=run,
        status="live",
        tags=("Documents", "Cited", "Safe on sensitive data"),
        sample_text=("Project Atlas — status update. The migration finished on March 12, two weeks ahead of schedule, "
                     "moving all 4,200 customer accounts with zero data loss. Monthly infrastructure cost dropped "
                     "from $48,000 to $31,000. One open risk remains: the legacy billing API is deprecated on June 30 "
                     "and three integrations still depend on it. The next review is scheduled for April 5."),
    )
)
