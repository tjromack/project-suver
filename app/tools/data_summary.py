"""The Data-summary tool — "Summarize a spreadsheet" (Suver's 11th tool; the 2nd Data & Analysis tool).

Drop a CSV (or paste a table) → a plain-language **overview** of the data plus a **computed column profile** (row/
column counts · per-column type · numeric min/mean/max/total · top categories · missing counts). The tabular analog
of the flagship Summarize. Signature discipline — **the model narrates, the code computes**: every figure is
calculated deterministically; the model only phrases the overview and is told to use only the computed numbers (the
profile table is the ground truth). Same trust posture — the model sees only the sanitized profile + a sanitized
sample, never the full dataset; the overview re-hydrates locally.

Deepens the Data & Analysis platform (understand your data → then *Ask your spreadsheet*). Reuses `app/table.py`;
zero-config (no question, no pick).
"""

from __future__ import annotations

from app.ingest import IngestError
from app.pipeline import summarize_table_document, summarize_table_paste
from app.tools import Tool, ToolError, ToolInput, ToolOutput, register


def run(inp: ToolInput) -> ToolOutput:
    if inp.is_empty:
        raise ToolError("Add a CSV file, or paste a table (a header row + rows) to summarize.")
    try:
        if inp.data is not None:
            result = summarize_table_document(inp.filename or "table.csv", inp.data)
        else:
            result = summarize_table_paste(inp.paste or "")
    except IngestError as e:
        raise ToolError(str(e)) from e
    return ToolOutput(result=result, template="_data_summary_result.html")


DATA_SUMMARY = register(
    Tool(
        slug="data-summary",
        name="Summarize a spreadsheet",
        blurb="Drop a CSV and get a plain-language overview plus a computed column profile — every figure calculated "
              "from your rows, nothing invented.",
        icon="📈",
        accepts="CSV · TSV · or paste a table",
        action_label="Summarize",
        run=run,
        status="live",
        tags=("Data & Analysis", "Computed profile", "Grounded overview"),
        sample_text=("Rep,Region,Units,Revenue\nAlice,West,120,9600\nBob,East,90,7200\nAlice,West,60,4800\n"
                     "Carol,East,150,12000\nBob,West,45,3600"),
        platform="Data & Analysis",
        lane="Overview",
    )
)
