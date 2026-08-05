"""The tool-app contract + registry — the reusable asset (DEC 002).

Every Suver tool is a `Tool`: a slug, a name/blurb/icon, what it `accepts`, and a `run(ToolInput) -> ToolOutput`.
The **shell** (one drop/paste zone, one primary action, one result slot, a trust-chip slot, zero config) and the
**hub** (browse → click → open) are generic over this contract, so the next tool is a small add — not a new app.

The contract IS the product principle in code: `input → [sanitize] → engine → output`. `run` receives one input
(an uploaded file *or* pasted text) and returns one output the tool's result partial renders. Sanitize-before-egress
and cite-or-drop live in the pipeline the tool calls — not in the shell — so every tool inherits them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


class ToolError(ValueError):
    """A friendly, user-facing tool error (bad/empty/unreadable input). The shell renders it as a calm message,
    never a stack trace. Any tool's `run` may raise it."""


@dataclass(frozen=True)
class ToolInput:
    """The user's own content: an uploaded file (filename+data) or pasted text, plus an optional plain-language
    `query` for tools that answer a question about the document (Copilot). A question is the user's information
    need in plain words — NOT prompt craft; the no-prompt principle still holds (you ask what you want to know,
    you don't instruct the model how to behave)."""

    filename: str | None = None
    data: bytes | None = None
    paste: str | None = None
    query: str | None = None
    choice: str | None = None   # a picked option (e.g. the draft kind) — a select value, never prompt text
    # A second document, for tools that compare two (Compare). Still just the user's input — no prompt.
    filename2: str | None = None
    data2: bytes | None = None
    paste2: str | None = None

    @property
    def is_empty(self) -> bool:
        return not (self.data or (self.paste and self.paste.strip()))

    @property
    def has_second(self) -> bool:
        return bool(self.data2 or (self.paste2 and self.paste2.strip()))

    @property
    def has_query(self) -> bool:
        return bool(self.query and self.query.strip())


@dataclass(frozen=True)
class ToolOutput:
    """What `run` returns: the tool-specific `result` object + the partial that renders it."""

    result: object
    template: str  # the result partial, e.g. "_summary_result.html"


@dataclass(frozen=True)
class Tool:
    slug: str
    name: str
    blurb: str            # one calm sentence — what you get
    icon: str             # an emoji
    accepts: str          # human string, e.g. "PDF · DOCX · TXT · MD · or paste"
    action_label: str     # the single primary button, e.g. "Summarize"
    run: Callable[[ToolInput], ToolOutput] | None = None
    status: str = "live"  # "live" | "soon"
    tags: tuple[str, ...] = field(default_factory=tuple)
    # Some tools ask a plain-language question about the document (Copilot). The shell renders one question field
    # when needs_query is set — still no prompt craft, just the user's information need.
    needs_query: bool = False
    query_label: str = "Your question"
    query_placeholder: str = "Ask a question about this document…"
    # Some tools offer a fixed set of output kinds to PICK (Draft). The shell renders a <select> of (value, label)
    # pairs when options is non-empty — a pick, not a prompt. The first option is the default.
    options: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    choice_label: str = "What to make"
    # Some tools compare TWO documents (Compare). The shell renders a second drop/paste zone when set.
    needs_second: bool = False
    doc_labels: tuple[str, str] = ("Document A", "Document B")

    @property
    def has_options(self) -> bool:
        return bool(self.options)

    @property
    def is_live(self) -> bool:
        return self.status == "live" and self.run is not None


_REGISTRY: dict[str, Tool] = {}


def register(tool: Tool) -> Tool:
    _REGISTRY[tool.slug] = tool
    return tool


def get(slug: str) -> Tool | None:
    return _REGISTRY.get(slug)


def all_tools() -> list[Tool]:
    """Registered tools — live ones first, then 'coming soon', each group in registration order."""
    tools = list(_REGISTRY.values())
    return [t for t in tools if t.is_live] + [t for t in tools if not t.is_live]


def load_builtin() -> None:
    """Import the built-in tools so they self-register. Called once at app startup."""
    from app.tools import summarize  # noqa: F401  (live — the 1st Documents tool)
    from app.tools import copilot  # noqa: F401  (live — the 2nd Documents tool)
    from app.tools import draft  # noqa: F401  (live — the 3rd Documents tool)
    from app.tools import extractor  # noqa: F401  (live — the 4th Documents tool)
    from app.tools import compare  # noqa: F401  (live — the 5th Documents tool; first two-document tool)
    from app.tools import coming_soon  # noqa: F401  (no soon cards currently — the Documents platform is fully live)
