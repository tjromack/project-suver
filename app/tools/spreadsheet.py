"""The Spreadsheet tool — "Ask your spreadsheet" (Suver's 10th tool; the FIRST Data & Analysis tool).

Add a CSV (or paste a table) and ask a plain question → an **exact answer computed from your rows**, showing the
cells it used. Signature discipline — **the model plans, the code computes**: the model turns your question into a
structured plan (which operation, which columns, any filter), and the pipeline executes it **deterministically** over
your data, so the arithmetic is always right and every answer traces to real rows. If the question can't be answered
from the table's columns → an honest abstention. Strong privacy story: the model only ever sees the **schema + a
small sanitized sample** — never the full dataset (that stays local for the computation).

⭐ Opens **platform #3 — Data & Analysis** (a new, non-prose *tabular* modality), proving the hub scales past
documents/text. Adds a lean CSV/TSV ingest + a table parser (`app/table.py`); no heavy deps.
"""

from __future__ import annotations

from app.ingest import IngestError
from app.pipeline import ask_table_document, ask_table_paste
from app.tools import Tool, ToolError, ToolInput, ToolOutput, register


def run(inp: ToolInput) -> ToolOutput:
    if inp.is_empty:
        raise ToolError("Add a CSV file, or paste a table (a header row + rows) to ask about.")
    if not inp.has_query:
        raise ToolError("Type a question about your table — e.g. “total revenue in the West region”.")
    try:
        if inp.data is not None:
            result = ask_table_document(inp.filename or "table.csv", inp.data, inp.query or "")
        else:
            result = ask_table_paste(inp.paste or "", inp.query or "")
    except IngestError as e:
        raise ToolError(str(e)) from e
    return ToolOutput(result=result, template="_spreadsheet_result.html")


SPREADSHEET = register(
    Tool(
        slug="spreadsheet",
        name="Ask your spreadsheet",
        blurb="Add a CSV (or paste a table) and ask a plain question — get an exact answer computed from your rows, "
              "showing the cells it used.",
        icon="🔎",
        accepts="CSV · TSV · or paste a table",
        action_label="Ask",
        run=run,
        status="live",
        tags=("Data & Analysis", "Computed, not guessed", "Cites the rows"),
        sample_text=("Rep,Region,Units,Revenue\nAlice,West,120,9600\nBob,East,90,7200\nAlice,West,60,4800\n"
                     "Carol,East,150,12000\nBob,West,45,3600"),
        sample_query="Which region had the most revenue?",
        platform="Data & Analysis",
        lane="Ask",
        needs_query=True,
        query_label="Your question",
        query_placeholder="e.g. total revenue in the West region",
    )
)
