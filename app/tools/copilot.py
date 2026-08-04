"""The Copilot tool — "Ask this document" (Suver's second Documents tool).

Add a document (or paste), ask a plain-language question → a **grounded, cited answer** from your document, or an
honest **"not in your document."** Same trust posture as Summarize (the model only ever sees sanitized text; the
answer is grounded in a retrieved passage or we **abstain** — abstention over hallucination), and it proves the
tool-app shell generalizes: this tool needs a *question* as well as a document, so the contract grew one optional
`query` field and the shell renders one question box — still no prompt craft, just the user's information need.
"""

from __future__ import annotations

from app.ingest import IngestError
from app.pipeline import answer_document, answer_paste
from app.tools import Tool, ToolError, ToolInput, ToolOutput, register


def run(inp: ToolInput) -> ToolOutput:
    if inp.is_empty:
        raise ToolError("Add a document or paste some text to ask about.")
    if not inp.has_query:
        raise ToolError("Type a question about your document.")
    try:
        if inp.data is not None:
            result = answer_document(inp.filename or "document", inp.data, inp.query or "")
        else:
            result = answer_paste(inp.paste or "", inp.query or "")
    except IngestError as e:
        raise ToolError(str(e)) from e
    return ToolOutput(result=result, template="_answer_result.html")


COPILOT = register(
    Tool(
        slug="copilot",
        name="Ask this document",
        blurb="Add a document and ask a question — get a cited answer, or an honest “not in your document.”",
        icon="💬",
        accepts="PDF · DOCX · TXT · MD · or paste",
        action_label="Ask",
        run=run,
        status="live",
        tags=("Documents", "Cited answers", "Won’t guess"),
        needs_query=True,
        query_label="Your question",
        query_placeholder="e.g. What are the key deadlines, and who is responsible?",
    )
)
