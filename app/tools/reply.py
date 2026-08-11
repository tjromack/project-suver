"""The Reply tool — "Draft a reply" (Suver's 9th tool; the 3rd Communications tool).

Paste a message you received, **pick the kind of reply** (Acknowledge · Answer · Decline · Ask for detail · Follow
up) → a grounded draft reply. Signature discipline: it **uses only the message's facts** and inserts clearly-labeled
**[placeholders]** for anything it doesn't know — it never invents a date, number, name, or commitment on your
behalf; and any concrete specific it did add that isn't in the message is **flagged for you to verify**. Same trust
posture — the model only ever sees Data-Boundary-safe text; the reply re-hydrates locally (real names restored).

Completes the Communications trio — *triage what came in · pull actions from meetings · draft what goes out.* Reuses
the contract's `choice`/`options` (a pick, not a prompt); no new engine.
"""

from __future__ import annotations

from app.ingest import IngestError
from app.pipeline import reply_document, reply_intents, reply_paste
from app.tools import Tool, ToolError, ToolInput, ToolOutput, register


def run(inp: ToolInput) -> ToolOutput:
    if inp.is_empty:
        raise ToolError("Paste the message you want to reply to (or add a file).")
    intent = inp.choice or "acknowledge"
    try:
        if inp.data is not None:
            result = reply_document(inp.filename or "message", inp.data, intent)
        else:
            result = reply_paste(inp.paste or "", intent)
    except IngestError as e:
        raise ToolError(str(e)) from e
    return ToolOutput(result=result, template="_reply_result.html")


REPLY = register(
    Tool(
        slug="reply",
        name="Draft a reply",
        blurb="Paste a message and pick the kind of reply — get a grounded draft that leaves clear [placeholders] "
              "for anything it doesn't know, and never invents specifics on your behalf.",
        icon="✍️",
        accepts="Paste a message · or PDF · DOCX · TXT · MD",
        action_label="Draft reply",
        run=run,
        status="live",
        tags=("Communications", "Grounded", "Placeholders, not guesses"),
        sample_text=("Hi — we'd like to move our onboarding call to next week. Does Tuesday or Wednesday afternoon "
                     "work for you? Also, could you send the pricing sheet over beforehand? Thanks, Jordan."),
        platform="Communications",
        lane="Reply",
        options=tuple(reply_intents()),
        choice_label="What kind of reply",
    )
)
