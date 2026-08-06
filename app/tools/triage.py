"""The Triage tool — "Triage messages" (Suver's 8th tool; the 2nd Communications tool).

Paste your messages or an email thread → each message **sorted by what it needs**: *Needs reply · Action needed ·
FYI · Can ignore*, with a one-line reason drawn from the message. Signature discipline: **honest uncertainty** — a
message the model isn't sure about is shown as **Review**, never forced into a confident wrong bucket; and the
reason must **ground to the message** (never invented). Same trust posture — the model only ever sees Data-Boundary-
safe text; snippets/reasons re-hydrate locally.

Composes the classify-then-gate shape (a model call per batch + a deterministic confidence gate), no new engine and
no new contract field. The 2nd Communications tool alongside Meeting-actions — *sort what came in, pull actions from
meetings* (reply drafting is the natural third).
"""

from __future__ import annotations

from app.ingest import IngestError
from app.pipeline import triage_document, triage_paste
from app.tools import Tool, ToolError, ToolInput, ToolOutput, register


def run(inp: ToolInput) -> ToolOutput:
    if inp.is_empty:
        raise ToolError("Paste your messages (one per block, separated by a blank line) or add a file to triage.")
    try:
        if inp.data is not None:
            result = triage_document(inp.filename or "messages", inp.data)
        else:
            result = triage_paste(inp.paste or "")
    except IngestError as e:
        raise ToolError(str(e)) from e
    return ToolOutput(result=result, template="_triage_result.html")


TRIAGE = register(
    Tool(
        slug="triage",
        name="Triage messages",
        blurb="Paste your messages or a thread and see what needs a reply, what needs an action, what's just FYI — "
              "each with the reason it was sorted that way.",
        icon="📥",
        accepts="Paste your messages · or PDF · DOCX · TXT · MD",
        action_label="Triage",
        run=run,
        status="live",
        tags=("Communications", "Sorted", "Flags the unsure"),
        platform="Communications",
        lane="Triage",
    )
)
