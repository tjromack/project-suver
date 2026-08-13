"""The Quiz tool — Suver's Learning platform (platform #4), second tool (DEC 044).

Drop a document → a short multiple-choice **quiz**. Each question's **correct answer is cited to a span of your
document** (cite-or-drop: a question whose correct answer can't be grounded is dropped, never invented); the distractors
are plausible wrong options. Same trust posture as Flashcards — the model drafts, the deterministic grounding gate
verifies the correct answer before a question is shown.
"""

from __future__ import annotations

from app.ingest import IngestError
from app.pipeline import quiz_document, quiz_paste
from app.tools import Tool, ToolError, ToolInput, ToolOutput, register

_SAMPLE = ("The water cycle describes how water moves through Earth's environment. Evaporation turns liquid water into "
           "vapor using heat from the sun. Condensation forms clouds as water vapor cools and turns back into tiny "
           "droplets. Precipitation is water that falls to the ground as rain, snow, or hail when the droplets grow "
           "heavy. Collection returns the water to oceans, lakes, and rivers, where the cycle begins again.")


def run(inp: ToolInput) -> ToolOutput:
    if inp.is_empty:
        raise ToolError("Add a document or paste some text to make a quiz from.")
    try:
        if inp.data is not None:
            result = quiz_document(inp.filename or "document", inp.data)
        else:
            result = quiz_paste(inp.paste or "")
    except IngestError as e:
        raise ToolError(str(e)) from e
    return ToolOutput(result=result, template="_quiz_result.html")


QUIZ = register(
    Tool(
        slug="quiz",
        name="Quiz me",
        blurb="Drop a document → a multiple-choice quiz; every correct answer is cited to your text.",
        icon="❓",
        accepts="PDF · DOCX · TXT · MD · or paste",
        action_label="Make a quiz",
        run=run,
        status="live",
        platform="Learning",
        lane="Study",
        tags=("Learning", "Cited answers", "Grounded"),
        sample_text=_SAMPLE,
    )
)
