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

# --- Vertical field-set packs (the "adaptation ladder": a new vertical is config, not a new engine) --------------
# Each targets a common structured-document job. They appear in BOTH the Extractor's select AND Compare's — so
# "compare a vendor contract vs. our standard, term by term" works with no new code.

CONTRACT_TERMS = FieldSet(
    slug="contract",
    label="Contract terms  (legal)",
    item_type=FieldType.STRING,
    instruction=("Extract the key terms of this contract as label → value pairs. Look for: the **parties**, "
                 "**effective/commencement date**, **term or duration**, **renewal / auto-renewal**, **termination "
                 "notice period**, **governing law / jurisdiction**, **payment terms**, **fees or price**, "
                 "**liability cap / limitation of liability**, **indemnification**, **confidentiality**, and any "
                 "other material term. Use ONLY what the document states; omit a term that isn't present (don't "
                 "invent it). Keep each value concise."),
    blurb="Pull the key contract terms — parties, dates, term, governing law, liability, payment — into a table.",
    empty_note="No clear contract terms were found — is this a contract or agreement?",
    stub_kind="keyvalue",
)

INVOICE = FieldSet(
    slug="invoice",
    label="Invoice details  (finance)",
    item_type=FieldType.STRING,
    instruction=("Extract the invoice details as label → value pairs: **invoice number**, **invoice date**, **due "
                 "date**, **vendor / supplier**, **bill-to**, **PO number**, **subtotal**, **tax**, **total amount "
                 "due**, and **payment terms**. Use ONLY what the document states; omit anything absent."),
    blurb="Pull invoice details — number, dates, vendor, subtotal, tax, total, payment terms — into a table.",
    empty_note="No invoice details were found — is this an invoice or bill?",
    stub_kind="keyvalue",
)

RESUME = FieldSet(
    slug="resume",
    label="Résumé fields  (HR)",
    item_type=FieldType.STRING,
    instruction=("Extract the candidate's details as label → value pairs: **full name**, **contact** (email/phone), "
                 "**current or most recent title**, **years of experience**, **key skills**, **education** "
                 "(degrees/institutions), **certifications**, and any **notable achievements**. Use ONLY what the "
                 "résumé states; omit anything absent."),
    blurb="Pull résumé fields — name, contact, title, experience, skills, education — into a table.",
    empty_note="No résumé fields were found — is this a CV or résumé?",
    stub_kind="keyvalue",
)

_FIELDSETS = {fs.slug: fs for fs in
              (KEY_FACTS, DATES, PEOPLE, AMOUNTS, CONTRACT_TERMS, INVOICE, RESUME)}


def get_fieldset(slug: str | None) -> FieldSet | None:
    return _FIELDSETS.get((slug or "").strip())


def all_fieldsets() -> list[FieldSet]:
    return list(_FIELDSETS.values())


def default_fieldset() -> FieldSet:
    return KEY_FACTS
