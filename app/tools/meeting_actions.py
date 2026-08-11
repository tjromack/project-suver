"""The Meeting-actions tool — "Meeting notes → actions" (Suver's 7th tool; the FIRST Communications tool).

Drop meeting notes or a transcript (or paste) → a clean list of **action items** — *who, what, by when* — grounded
in the notes. Signature move: **cite-or-drop the action** (an action that doesn't ground to a source span is
withheld, never invented) and an **owner or due is shown only if the notes state it** (never guessed). Same trust
posture as every Suver tool — the model only ever sees Data-Boundary-safe text (names arrive as tokens); values
re-hydrate locally.

⭐ This is **platform #2** — it opens the **Communications** platform (meetings → action, message triage, reply
drafting are the natural next tools), proving Suver is a multi-platform *hub*, not one Documents app. It's a small
add: no new contract field (one document, no query/pick/second-doc), and it **composes** the extraction + grounding
machinery the Documents tools already use.
"""

from __future__ import annotations

from app.ingest import IngestError
from app.pipeline import actions_document, actions_paste
from app.tools import Tool, ToolError, ToolInput, ToolOutput, register


def run(inp: ToolInput) -> ToolOutput:
    if inp.is_empty:
        raise ToolError("Add meeting notes or a transcript (a file or pasted text) to pull actions from.")
    try:
        if inp.data is not None:
            result = actions_document(inp.filename or "notes", inp.data)
        else:
            result = actions_paste(inp.paste or "")
    except IngestError as e:
        raise ToolError(str(e)) from e
    return ToolOutput(result=result, template="_actions_result.html")


MEETING_ACTIONS = register(
    Tool(
        slug="meeting-actions",
        name="Meeting notes → actions",
        blurb="Drop meeting notes or a transcript and get a clean list of action items — who, what, and by when — "
              "grounded in the notes, nothing invented.",
        icon="✅",
        accepts="PDF · DOCX · TXT · MD · or paste",
        action_label="Find actions",
        run=run,
        status="live",
        tags=("Communications", "Grounded", "Owner · due"),
        sample_text=("Product sync — notes. Dana will send the revised spec to Legal by Friday. Raj to fix the export "
                     "bug before the demo. We agreed to push the launch to May 6. Priya will book the venue once the "
                     "date is confirmed. Good discussion on pricing, but no decision was made."),
        platform="Communications",
        lane="Meetings",
    )
)
