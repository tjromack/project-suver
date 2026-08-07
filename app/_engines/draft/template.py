"""Draft kinds — the template that decides what a draft says (a *pick*, never a prompt).

ORIGIN: c:/ai/draft-template-responder/app/template.py (the `Template`/`Slot` model + validation), slimmed for
document-grounded memos: a **kind** is an ordered list of **sections**, each a heading + a grounding **query**
answered from the user's document. Sections may be `required` (a kind that can't ground a required section
**blocks** — cite-or-block) or optional (omitted when the document doesn't support them).

The set of kinds is the only thing a user picks; there is no prompt. Add a kind here → it appears in the tool's
select and the hub. Deterministic; no model in this module.
"""

from __future__ import annotations

from dataclasses import dataclass


class KindError(ValueError):
    """A malformed draft kind — rejected at definition time."""


@dataclass(frozen=True)
class Section:
    key: str            # stable id
    heading: str        # the section heading shown in the memo
    query: str          # the question grounded against the document (answered from it, or the section is dropped)
    required: bool = False   # a required section that can't ground → the whole draft blocks
    max_len: int | None = None


@dataclass(frozen=True)
class DraftKind:
    slug: str           # the select value
    label: str          # the human label in the select
    title_hint: str     # the memo's title prefix, e.g. "Summary Memo — <doc>"
    blurb: str          # one line: what this kind produces
    sections: tuple[Section, ...]
    forbidden: tuple[str, ...] = ()   # phrases a section may never contain (kind-wide)

    def __post_init__(self):
        if not self.slug or not self.label:
            raise KindError("a draft kind needs a slug and a label")
        if not self.sections:
            raise KindError(f"draft kind '{self.slug}' needs at least one section")
        seen = set()
        for s in self.sections:
            if not s.key or not s.query:
                raise KindError(f"draft kind '{self.slug}' has a section missing a key or query")
            if s.key in seen:
                raise KindError(f"draft kind '{self.slug}' has a duplicate section key '{s.key}'")
            seen.add(s.key)


# --- the built-in kinds (the launch set) -------------------------------------------------------------

SUMMARY_MEMO = DraftKind(
    slug="memo",
    label="Summary memo",
    title_hint="Summary Memo",
    blurb="A short, structured memo — Overview · Key Points · Next Steps — grounded in your document.",
    sections=(
        Section("overview", "Overview",
                "In one or two sentences, what is this document about and what is its purpose?", required=True),
        Section("key_points", "Key Points",
                "What are the most important points, findings, or facts in this document?", required=True),
        Section("next_steps", "Next Steps",
                "What actions, next steps, deadlines, or recommendations does this document state?", required=False),
    ),
)

EXPLAINER = DraftKind(
    slug="explainer",
    label="Plain-language explainer",
    title_hint="Plain-Language Explainer",
    blurb="A plain-language explainer — what it says, why it matters, what to watch — grounded in your document.",
    sections=(
        Section("what", "What this says",
                "In plain language, what does this document say? Keep it simple and concrete.", required=True),
        Section("why", "Why it matters",
                "Why does this matter — what is the impact, stake, or consequence described?", required=False),
        Section("watch", "What to watch",
                "What conditions, dates, risks, or requirements should the reader watch for?", required=False),
    ),
)

ACTION_ITEMS = DraftKind(
    slug="actions",
    label="Action items",
    title_hint="Action Items",
    blurb="An action-items list — the concrete tasks, owners, and deadlines stated in your document.",
    sections=(
        Section("actions", "Action Items",
                "List the concrete actions, tasks, or to-dos this document specifies, with any owners or deadlines.",
                required=True),
        Section("decisions", "Decisions & Approvals",
                "What decisions, approvals, or sign-offs does this document call for?", required=False),
    ),
)

CONTRACT_MEMO = DraftKind(
    slug="contract-memo",
    label="Contract review memo  (legal)",
    title_hint="Contract Review Memo",
    blurb="A first-pass review memo of an agreement — Overview · Key Terms · Points to Review · Next Steps — every "
          "section grounded in the contract (cite-or-block, never invented).",
    sections=(
        Section("overview", "Overview",
                "In one or two sentences, what is this agreement, who are the parties, and what is its purpose?",
                required=True),
        Section("key_terms", "Key Terms",
                "What are the key terms this document states — the term/duration, renewal, payment or fees, governing "
                "law, termination notice, and any liability or indemnification provisions?", required=True),
        Section("review", "Points to Review",
                "Point out the clauses in this document a reviewer should look at closely — for each, name it using "
                "the document's own wording (for example the liability cap, the automatic renewal, the indemnity, or "
                "the termination/notice terms). Describe only clauses actually present.",
                required=False),
        Section("next_steps", "Next Steps",
                "What approvals, actions, or open questions does this document call for?", required=False),
    ),
)

_KINDS = {k.slug: k for k in (SUMMARY_MEMO, EXPLAINER, ACTION_ITEMS, CONTRACT_MEMO)}


def get_kind(slug: str | None) -> DraftKind | None:
    return _KINDS.get((slug or "").strip())


def all_kinds() -> list[DraftKind]:
    return list(_KINDS.values())


def default_kind() -> DraftKind:
    return SUMMARY_MEMO
