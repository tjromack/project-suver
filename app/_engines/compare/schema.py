"""The typed comparison schema.

ORIGIN: c:/ai/two-source-comparator/app/schema.py (verbatim; stdlib-only, no internal imports). A comparison
schema is a set of typed fields; each field's `type` selects the comparison rule in `compare.py`. In Suver the
schema is built on the fly from a field-set's labels (see `app/pipeline.py`).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class FieldType(str, Enum):
    STRING = "string"
    DATE = "date"
    MONEY = "money"
    NUMBER = "number"


@dataclass(frozen=True)
class CompareField:
    name: str
    type: FieldType
    required: bool = True


@dataclass(frozen=True)
class CompareSchema:
    name: str
    fields: tuple[CompareField, ...]

    def field_names(self) -> list[str]:
        return [f.name for f in self.fields]

    def field(self, name: str) -> CompareField:
        for f in self.fields:
            if f.name == name:
                return f
        raise KeyError(name)
