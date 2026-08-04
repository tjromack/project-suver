"""The sensitivity policy — the single adaptation surface.

ORIGIN: c:/ai/phi-pii-data-boundary/app/policy.py.
Vendored for Project Suver: the class model + `parse_policy` + the **fail-closed** validation are verbatim; the
file/dir loaders (`_resolve_path`/`load_policy`/`load_all`, which needed the engine's `settings.policies_dir`)
are replaced by a self-contained `DEFAULT_POLICY` dict + `default_policy()` so the pilot needs no policy files.

Fail-closed validation (unchanged): a `never_egress` class must resolve to a LOCAL action (route_local | block),
and the policy `default_action` (applied to an unresolvable span) must be LOCAL — a policy that could let raw
sensitive data leave by omission is rejected at load.
"""

from __future__ import annotations

from dataclasses import dataclass

# The four boundary actions.
VALID_ACTIONS = ("tokenize", "redact", "route_local", "block")
# Actions that emit sanitized text which LEAVES the boundary (the model/egress sees it):
EGRESS_ACTIONS = frozenset({"tokenize", "redact"})
# Actions that keep the data inside the local trust zone (nothing leaves):
LOCAL_ACTIONS = frozenset({"route_local", "block"})
# A fail-closed default must keep data local:
SAFE_DEFAULTS = LOCAL_ACTIONS
RISK_TIERS = ("low", "medium", "high")


class PolicyError(ValueError):
    """A malformed or fail-open policy — rejected at load."""


@dataclass(frozen=True)
class SensitiveClass:
    """One sensitive data class: what detects it, and what the boundary does with it."""

    name: str
    detector: str
    risk_tier: str = "high"
    # If True, this class may not leave the boundary at all — even sanitized — so its action must be LOCAL.
    never_egress: bool = False
    # Reversible → tokenize (a stable placeholder re-hydrated locally); irreversible → redact (masked, no map).
    reversible: bool = True
    # An explicit action overriding the derived one (must still satisfy the never_egress invariant).
    action: str | None = None

    @property
    def resolved_action(self) -> str:
        """The action actually applied for this class (explicit override, else derived from the flags)."""
        if self.action is not None:
            return self.action
        if self.never_egress:
            return "route_local"
        return "tokenize" if self.reversible else "redact"


@dataclass(frozen=True)
class SensitivityPolicy:
    id: str
    version: str
    classes: tuple[SensitiveClass, ...]
    default_action: str = "block"

    def get(self, name: str) -> SensitiveClass | None:
        for c in self.classes:
            if c.name == name:
                return c
        return None

    @property
    def class_names(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.classes)


def parse_policy(data: dict) -> SensitivityPolicy:
    """Build + fully validate a policy from a dict. Raises PolicyError on anything malformed or fail-open."""
    if not isinstance(data, dict):
        raise PolicyError("policy must be a JSON object")
    pid = data.get("id")
    version = data.get("version")
    if not isinstance(pid, str) or not pid:
        raise PolicyError("policy needs a non-empty string 'id'")
    if not isinstance(version, str) or not version:
        raise PolicyError(f"policy '{pid}' needs a non-empty string 'version'")

    default_action = data.get("default_action", "block")
    # ⭐ Fail-closed: the default applied to an unresolvable/uncertain span must keep data local.
    if default_action not in SAFE_DEFAULTS:
        raise PolicyError(
            f"policy '{pid}': default_action must be one of {sorted(SAFE_DEFAULTS)} (fail-closed) — "
            f"got '{default_action}', which could let raw data leave by omission"
        )

    raw_classes = data.get("classes")
    if not isinstance(raw_classes, list) or not raw_classes:
        raise PolicyError(f"policy '{pid}' needs a non-empty 'classes' list")

    classes: list[SensitiveClass] = []
    seen: set[str] = set()
    for i, rc in enumerate(raw_classes):
        if not isinstance(rc, dict):
            raise PolicyError(f"policy '{pid}' class #{i} must be an object")
        name = rc.get("name")
        detector = rc.get("detector")
        if not isinstance(name, str) or not name:
            raise PolicyError(f"policy '{pid}' class #{i} needs a non-empty 'name'")
        if name in seen:
            raise PolicyError(f"policy '{pid}' has a duplicate class name '{name}'")
        seen.add(name)
        if not isinstance(detector, str) or not detector:
            raise PolicyError(f"policy '{pid}' class '{name}' needs a non-empty 'detector'")
        risk_tier = rc.get("risk_tier", "high")
        if risk_tier not in RISK_TIERS:
            raise PolicyError(f"policy '{pid}' class '{name}' has unknown risk_tier '{risk_tier}'")
        action = rc.get("action")
        if action is not None and action not in VALID_ACTIONS:
            raise PolicyError(f"policy '{pid}' class '{name}' has unknown action '{action}'")

        sc = SensitiveClass(
            name=name,
            detector=detector,
            risk_tier=risk_tier,
            never_egress=bool(rc.get("never_egress", False)),
            reversible=bool(rc.get("reversible", True)),
            action=action,
        )
        # ⭐ The headline fail-open rejection: a never_egress class must resolve to a LOCAL action.
        if sc.never_egress and sc.resolved_action not in LOCAL_ACTIONS:
            raise PolicyError(
                f"policy '{pid}' class '{name}' is never_egress but resolves to egress action "
                f"'{sc.resolved_action}' — a never_egress class must be route_local/block (fail-open rejected)"
            )
        classes.append(sc)

    return SensitivityPolicy(id=pid, version=version, classes=tuple(classes), default_action=default_action)


# --- the pilot's built-in policy (replaces the engine's data/policies/*.json loaders) ----------------
#
# Consumer-document defaults: the clearly-sensitive PII classes, all reversible → tokenize, so the model sees
# stable placeholders and the user's real values re-hydrate locally in the displayed summary. `dob`/date
# detection is intentionally omitted — dates are usually salient facts a summary should keep readable, not the
# sensitive thing. default_action is fail-closed (route_local): an uncertain/unknown span never egresses raw.
DEFAULT_POLICY: dict = {
    "id": "suver-documents",
    "version": "1.0.0",
    "default_action": "route_local",
    "classes": [
        {"name": "ssn", "detector": "ssn", "risk_tier": "high", "reversible": True},
        {"name": "credit_card", "detector": "credit_card", "risk_tier": "high", "reversible": True},
        {"name": "mrn", "detector": "mrn", "risk_tier": "high", "reversible": True},
        {"name": "email", "detector": "email", "risk_tier": "medium", "reversible": True},
        {"name": "phone", "detector": "phone", "risk_tier": "medium", "reversible": True},
        {"name": "address", "detector": "address", "risk_tier": "medium", "reversible": True},
        {"name": "person_name", "detector": "person_name", "risk_tier": "medium", "reversible": True},
    ],
}


def default_policy() -> SensitivityPolicy:
    """The pilot's self-contained, validated sensitivity policy."""
    return parse_policy(DEFAULT_POLICY)
