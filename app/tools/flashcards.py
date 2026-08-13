"""The Flashcards tool — Suver's Learning platform (platform #4), first tool (DEC 044).

Drop a document → a set of study **flashcards** (a question + a short answer), each answer **cited to a span of your
document**. Same trust discipline as Summarize: the model drafts the cards from sanitized text, and the deterministic
grounding gate keeps only the cards whose answer is actually supported — an ungroundable card is **dropped, never
invented** (cite-or-drop). A new *output modality* (study aids), not a new engine: it reuses sanitize + split + the
grounding gate. The hub gains a fourth platform, and the shell needed no new contract field.
"""

from __future__ import annotations

from app.ingest import IngestError
from app.pipeline import flashcards_document, flashcards_paste
from app.tools import Tool, ToolError, ToolInput, ToolOutput, register

_SAMPLE = ("The water cycle describes how water moves through Earth's environment. Evaporation turns liquid water into "
           "vapor using heat from the sun. Condensation forms clouds as water vapor cools and turns back into tiny "
           "droplets. Precipitation is water that falls to the ground as rain, snow, or hail when the droplets grow "
           "heavy. Collection returns the water to oceans, lakes, and rivers, where the cycle begins again.")


def run(inp: ToolInput) -> ToolOutput:
    if inp.is_empty:
        raise ToolError("Add a document or paste some text to make flashcards from.")
    try:
        if inp.data is not None:
            result = flashcards_document(inp.filename or "document", inp.data)
        else:
            result = flashcards_paste(inp.paste or "")
    except IngestError as e:
        raise ToolError(str(e)) from e
    return ToolOutput(result=result, template="_flashcards_result.html")


FLASHCARDS = register(
    Tool(
        slug="flashcards",
        name="Flashcards",
        blurb="Drop a document → study flashcards, each answer cited to your text — unsupported ones are dropped.",
        icon="🃏",
        accepts="PDF · DOCX · TXT · MD · or paste",
        action_label="Make flashcards",
        run=run,
        status="live",
        platform="Learning",
        lane="Study",
        tags=("Learning", "Cited answers", "Won’t invent"),
        sample_text=_SAMPLE,
    )
)
