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
    """One input: an uploaded file (filename+data) or pasted text. Exactly the user's own content — no prompt."""

    filename: str | None = None
    data: bytes | None = None
    paste: str | None = None

    @property
    def is_empty(self) -> bool:
        return not (self.data or (self.paste and self.paste.strip()))


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
    from app.tools import summarize  # noqa: F401  (the live tool — registers on import)
    from app.tools import coming_soon  # noqa: F401  (the rest of the Documents platform, as 'soon' cards)
