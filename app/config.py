"""Configuration — read once from the environment (and an optional .env).

A single `settings` object + a `stub` provider so the whole flow runs offline. The provider governs only the
DRAFTING step (candidate key-points); sanitize, split, and grounding are always deterministic and never call a
model. See CLAUDE.md.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:  # optional — tests and CI run without it
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover
    pass

from app import __version__

REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    # Provider for the DRAFTING step only: "stub" (deterministic, offline) | "anthropic".
    provider: str = os.getenv("PROVIDER", "stub").strip().lower()
    anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5")
    # Max size (bytes) of a dropped document (real reports run large — 20 MB default).
    max_doc_bytes: int = int(os.getenv("MAX_DOC_BYTES", "20000000"))
    # Cap on characters sent to the drafting model (long docs → draft over the leading portion, transparently).
    max_draft_chars: int = int(os.getenv("MAX_DRAFT_CHARS", "40000"))
    # Grounding support threshold (fraction of a claim's content tokens that must appear in its best span).
    ground_threshold: float = float(os.getenv("GROUND_THRESHOLD", "0.6"))
    # Copilot ("Ask this document") retrieval: how many passages to consider, and the minimum question↔passage
    # relevance below which we abstain ("not in your document") rather than answer.
    copilot_top_k: int = int(os.getenv("COPILOT_TOP_K", "4"))
    copilot_min_relevance: float = float(os.getenv("COPILOT_MIN_RELEVANCE", "0.12"))
    samples_dir: Path = REPO_ROOT / os.getenv("SAMPLES_DIR", "data/samples")

    def provenance(self) -> dict:
        return {"app_version": __version__, "provider": self.provider}


settings = Settings()
