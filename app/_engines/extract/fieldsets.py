"""Field-set kinds — what the user picks to extract (a *pick*, never a prompt).

Each kind targets one **type** of thing to pull from the document as a list of labeled items. Adding a kind here
makes it appear in the tool's `<select>` (reusing the tool-app contract's `options`/`choice`). The `instruction`
guides the model; the `stub_kind` tells the offline extractor how to find items deterministically.
"""

from __future__ import annotations

from dataclasses import dataclass

from app._engines.extract.types import FieldType


@dataclass(frozen=True)
class FieldSet:
    slug: str
    label: str
    item_type: FieldType
    instruction: str        # what the model should extract (each item = a label + a typed value)
    blurb: str
    empty_note: str         # shown when the document has none of this kind
    stub_kind: str          # how the offline stub finds items: "keyvalue" | "date" | "contact" | "money"


KEY_FACTS = FieldSet(
    slug="facts",
    label="Key facts",
    item_type=FieldType.STRING,
    instruction=("Extract the most important key facts. For each, give a short descriptive **label you assign** and "
                 "a concise **value** taken only from the document — e.g. \"Project: Atlas\", \"Report date: May "
                 "2026\", \"Main risk: rising Treasury yields\", \"Key recommendation: strengthen oversight\". This "
                 "works for structured docs (labelled fields) AND narrative ones (synthesize a label for each "
                 "salient fact). Prefer specific, factual statements; keep each value short."),
    blurb="Pull the document's key facts into a clean label → value table.",
    empty_note="No clear key facts were found in this document.",
    stub_kind="keyvalue",
)

DATES = FieldSet(
    slug="dates",
    label="Dates & deadlines",
    item_type=FieldType.DATE,
    instruction=("Extract every date or deadline and what it refers to. For each, the label is what the date is "
                 "for, and the value is the date in YYYY-MM-DD format. Use only dates stated in the document."),
    blurb="Pull every date and deadline — and what each one is for.",
    empty_note="No dates or deadlines were found in this document.",
    stub_kind="date",
)

PEOPLE = FieldSet(
    slug="people",
    label="People & contacts",
    item_type=FieldType.STRING,
    instruction=("Extract the people, organizations, and contact details (names, emails, phone numbers). For each, "
                 "the label is the role or type (e.g. \"Contact\", \"Email\") and the value is the name/detail."),
    blurb="Pull the people, organizations, and contact details into a table.",
    empty_note="No people or contact details were found in this document.",
    stub_kind="contact",
)

AMOUNTS = FieldSet(
    slug="amounts",
    label="Amounts & totals",
    item_type=FieldType.MONEY,
    instruction=("Extract the monetary amounts and what each is for. For each, the label is what the amount is "
                 "(e.g. \"Total\", \"Deductible\") and the value is the amount. Use only amounts in the document."),
    blurb="Pull the monetary amounts and totals — and what each is for.",
    empty_note="No monetary amounts were found in this document.",
    stub_kind="money",
)

_FIELDSETS = {fs.slug: fs for fs in (KEY_FACTS, DATES, PEOPLE, AMOUNTS)}


def get_fieldset(slug: str | None) -> FieldSet | None:
    return _FIELDSETS.get((slug or "").strip())


def all_fieldsets() -> list[FieldSet]:
    return list(_FIELDSETS.values())


def default_fieldset() -> FieldSet:
    return KEY_FACTS
