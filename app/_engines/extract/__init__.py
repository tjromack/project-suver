"""Vendored Extractor core — typed values + the confidence = min(validation, model) gate.

ORIGIN: c:/ai/document-structured-extractor/app/{schemas,confidence,validate}.py.
Pilot adaptation (documented in ../../DECISIONS.md DEC 010): the engine fills *named domain schemas*
(invoice/claim). Suver's Extractor works on **arbitrary** documents, so it does **typed-list extraction** — pick
a **field-set kind** (a type of thing to pull) → a list of `{label, value}` items of that type. The engine's
genuine core is preserved: the **type parsers** (money/number/date) and the **confidence gate**
(`confidence = min(validation, model)` → **route/flag the uncertain, never guess**), applied per extracted item.
"""

from app._engines.extract.confidence import ExtractedItem, score_item  # noqa: F401
from app._engines.extract.fieldsets import FieldSet, all_fieldsets, default_fieldset, get_fieldset  # noqa: F401
from app._engines.extract.types import FieldType, parse_date, parse_money, parse_number, normalize_string  # noqa: F401
