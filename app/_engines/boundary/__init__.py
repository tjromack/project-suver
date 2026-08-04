"""Vendored PHI/PII Data-Boundary core — deterministic sanitize-before-egress.

ORIGIN: c:/ai/phi-pii-data-boundary/app/{policy,detect,sanitize}.py  (re-syncable — keep changes minimal).
Pilot adaptations (documented in ../../DECISIONS.md DEC 004):
  * policy.py — dropped the file/dir loaders (`_resolve_path`/`load_policy`/`load_all` needed the engine's
    own `settings.policies_dir`); added a self-contained `DEFAULT_POLICY` + `default_policy()` so the pilot
    needs no policy files. `parse_policy` + the fail-closed validation are unchanged.
  * No other logic changed — detection, the fail-closed decision, tokenize/redact, and `rehydrate` are verbatim.

The model only ever sees `BoundaryResult.safe_text`; the `token_map` is LOCAL-ONLY and re-hydrates for display.
"""

from app._engines.boundary.policy import DEFAULT_POLICY, SensitivityPolicy, default_policy  # noqa: F401
from app._engines.boundary.sanitize import BoundaryResult, rehydrate, sanitize  # noqa: F401
