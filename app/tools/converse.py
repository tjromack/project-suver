"""The Converse tool — "Chat with a document" (Suver's 6th Documents tool; the platform's first multi-turn tool).

Add a document, then **ask questions in a conversation** — follow-ups and all. Same trust posture as Copilot
(each answer is grounded in the document or it's an honest "not in your document"; the model only ever sees
sanitized passages), plus **conversation state**: the document is sanitized and split **once**, and follow-ups run
against the stored safe passages. It follows the `converse-grounded-assistant` discipline — *history resolves the
query (a follow-up retrieves with the prior questions as context), but only retrieval answers it* — so the bot
can't "answer from its own chat log." The first turn takes the document + a question; each follow-up takes only the
next question (the conversation carries the doc).
"""

from __future__ import annotations

from app.ingest import IngestError
from app.pipeline import converse_document, converse_followup, converse_paste
from app.tools import Tool, ToolError, ToolInput, ToolOutput, register


def run(inp: ToolInput) -> ToolOutput:
    if inp.session:                       # a follow-up turn — the document is already loaded
        if not inp.has_query:
            raise ToolError("Type your next question.")
        result = converse_followup(inp.session, inp.query or "")
    else:                                 # the first turn — needs the document + the first question
        if inp.is_empty:
            raise ToolError("Add a document to chat with.")
        if not inp.has_query:
            raise ToolError("Ask your first question about the document.")
        try:
            if inp.data is not None:
                result = converse_document(inp.filename or "document", inp.data, inp.query or "")
            else:
                result = converse_paste(inp.paste or "", inp.query or "")
        except IngestError as e:
            raise ToolError(str(e)) from e
    return ToolOutput(result=result, template="_converse_result.html")


CONVERSE = register(
    Tool(
        slug="converse",
        name="Chat with a document",
        blurb="Add a document and ask questions in a conversation — grounded, cited, follow-ups and all.",
        icon="🗨️",
        accepts="PDF · DOCX · TXT · MD · or paste",
        action_label="Send",
        run=run,
        status="live",
        tags=("Documents", "Multi-turn", "Grounded · won’t guess"),
        needs_query=True,
        query_label="Your question",
        query_placeholder="Ask about the document… (follow-ups welcome)",
        is_chat=True,
    )
)
