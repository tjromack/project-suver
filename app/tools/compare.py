"""The Compare tool — "Compare two documents" (Suver's 5th Documents tool; the platform's first two-input tool).

Drop **two documents**, pick **what to compare** (a field-set: facts · dates · people · amounts) → the same
fields pulled from both, aligned, and compared **type-aware** (money cent-tolerance · dates normalized · strings
fuzzy · missing-on-one-side). Every difference is shown with a grounded, plain-English note — but the tool
**never decides which document is right** (rules detect · the model explains · a human decides). It composes the
**Extractor** (pull the field-set from each doc) + the **Reconcile** engine's compare rules + coherence guard, and
stretches the tool-app contract to its **first two-document** shape.
"""

from __future__ import annotations

from app._engines.extract import all_fieldsets, default_fieldset
from app.ingest import IngestError
from app.pipeline import compare_inputs
from app.tools import Tool, ToolError, ToolInput, ToolOutput, register


def run(inp: ToolInput) -> ToolOutput:
    if inp.is_empty:
        raise ToolError("Add the first document to compare.")
    if not inp.has_second:
        raise ToolError("Add a second document to compare against.")
    fs_slug = inp.choice or default_fieldset().slug
    try:
        result = compare_inputs(inp.filename, inp.data, inp.paste, inp.filename2, inp.data2, inp.paste2, fs_slug)
    except IngestError as e:
        raise ToolError(str(e)) from e
    return ToolOutput(result=result, template="_compare_result.html")


COMPARE = register(
    Tool(
        slug="compare",
        name="Compare two documents",
        blurb="Drop two documents and see every difference — grounded in both; the tool never picks a winner.",
        icon="🔬",
        accepts="PDF · DOCX · TXT · MD · or paste",
        action_label="Compare",
        run=run,
        status="live",
        tags=("Documents", "Two documents", "Rules detect · you decide"),
        options=tuple((fs.slug, fs.label) for fs in all_fieldsets()),
        choice_label="What to compare",
        needs_second=True,
        doc_labels=("Document A", "Document B"),
    )
)
