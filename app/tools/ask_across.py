"""The Ask-across-documents tool — "Ask across your documents" (Suver's first true N-document tool).

Add several documents (a contract library, a policy set, a claims batch), ask a plain-language question → a
**grounded answer that cites the document each fact came from**, or an honest **"not in any of your documents."**
Same trust posture as Copilot — the model only ever sees sanitized passages, the answer must ground in a retrieved
passage or we **abstain** — but retrieval now runs across the whole corpus and every citation names its source
document. Each document is sanitized independently before egress; a document that must stay local is skipped (and
named), never searched. It proves the shell generalizes once more: a *set* of documents needed one optional `many`
field on the contract and a multi-file drop zone — still no prompt craft, just the user's input and question.
"""

from __future__ import annotations

from app.ingest import IngestError
from app.pipeline import ask_across_inputs
from app.tools import Tool, ToolError, ToolInput, ToolOutput, register


def run(inp: ToolInput) -> ToolOutput:
    if not inp.has_many:
        raise ToolError("Add two or more documents to ask across.")
    if not inp.has_query:
        raise ToolError("Type a question to ask across your documents.")
    try:
        result = ask_across_inputs(inp.many, inp.paste or "", inp.query or "")
    except IngestError as e:
        raise ToolError(str(e)) from e
    return ToolOutput(result=result, template="_ask_across_result.html")


ASK_ACROSS = register(
    Tool(
        slug="ask-across",
        name="Ask across your documents",
        blurb="Add several documents and ask one question — get a cited answer that names which document each fact came from.",
        icon="🗂️",
        accepts="Several PDFs · DOCX · TXT · MD",
        action_label="Ask across all",
        run=run,
        status="live",
        tags=("Documents", "Whole library", "Cited by document", "Won’t guess"),
        needs_many=True,
        needs_query=True,
        query_label="Your question",
        query_placeholder="e.g. Which contracts auto-renew, and on what notice period?",
    )
)
