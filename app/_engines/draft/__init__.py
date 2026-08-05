"""Vendored Draft core — the "template decides · cite-or-block" discipline, adapted for document-grounded memos.

ORIGIN: c:/ai/draft-template-responder/app/{template,fill}.py.
Pilot adaptation (documented in ../../DECISIONS.md DEC 009): the engine's templates are fixed-prose *letters*
whose `grounded` slots ground against a corpus via the RAG copilot. Suver's Draft produces a **grounded memo**
from the **user's dropped document**, so the model is slimmed to a **kind = ordered grounded sections** (each a
question answered from the doc) and the grounding is supplied by Suver's own retrieval (the Copilot path). The
engine's genuine core is preserved: **a template decides what the draft says, and a section that can't be grounded
is blocked/omitted — never fabricated** (cite-or-block).
"""

from app._engines.draft.assemble import DraftResult, DraftSection, GroundedSection, assemble  # noqa: F401
from app._engines.draft.template import (  # noqa: F401
    DraftKind,
    Section,
    all_kinds,
    default_kind,
    get_kind,
)
