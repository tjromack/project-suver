"""The Chart tool — "Chart your spreadsheet" (Suver's 12th tool; the 3rd Data & Analysis tool).

Drop a CSV (or paste a table) → **bar chart(s)**: for the primary categorical column, the **total** of each numeric
column by category. Signature: **accurate by construction, entirely local** — the sums are computed from your rows
and the bars are drawn from them, so nothing is invented and **nothing is sent to a model at all**. Zero-config (no
question, no pick). Adds a genuinely new *output modality* to the hub (a visualization).

Rounds out Data & Analysis — *summarize it · ask it · chart it.* Reuses `app/table.py`; the chart is dependency-free
CSS bars (no CDN, theme-aware).
"""

from __future__ import annotations

from app.ingest import IngestError
from app.pipeline import chart_table_document, chart_table_paste
from app.tools import Tool, ToolError, ToolInput, ToolOutput, register


def run(inp: ToolInput) -> ToolOutput:
    if inp.is_empty:
        raise ToolError("Add a CSV file, or paste a table (a header row + rows) to chart.")
    try:
        if inp.data is not None:
            result = chart_table_document(inp.filename or "table.csv", inp.data)
        else:
            result = chart_table_paste(inp.paste or "")
    except IngestError as e:
        raise ToolError(str(e)) from e
    return ToolOutput(result=result, template="_chart_result.html")


CHART = register(
    Tool(
        slug="chart",
        name="Chart your spreadsheet",
        blurb="Drop a CSV and get instant bar charts — each numeric column totalled by category, drawn from your "
              "actual rows (accurate by construction, nothing sent to a model).",
        icon="📊",
        accepts="CSV · TSV · or paste a table",
        action_label="Chart",
        run=run,
        status="live",
        tags=("Data & Analysis", "Computed locally", "No model needed"),
        platform="Data & Analysis",
        lane="Chart",
    )
)
