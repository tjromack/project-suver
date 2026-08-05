"""Vendored Reconcile / Two-Source Comparator core — type-aware discrepancy detection + "explain, never decide".

ORIGIN: c:/ai/two-source-comparator/app/{schema,compare,explain}.py.
Pilot adaptation (documented in ../../DECISIONS.md DEC 014): the engine compares two records aligned by a shared
**named schema**. Suver compares two **arbitrary documents**, so the same field-set is pulled from each (via the
Extractor), the two label/value lists are **aligned by fuzzy label**, and the resulting `{label: value}` dicts are
handed to the engine's `compare()` verbatim. The trust cores are preserved: **rules detect** (deterministic,
type-aware, tolerant) and the **model explains but never decides** (the coherence guard). Suver uses the
deterministic **stub** explanation (guaranteed coherent, no per-difference model call — the model is only used for
the extraction step).
"""

from app._engines.compare.compare import Discrepancy, compare  # noqa: F401
from app._engines.compare.explain import Explanation, check_coherence, explain_stub  # noqa: F401
from app._engines.compare.schema import CompareField, CompareSchema, FieldType  # noqa: F401
