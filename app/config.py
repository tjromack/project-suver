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
    # Model provider: "anthropic" (the real product) | "stub" (deterministic, offline — tests/CI/no-key).
    # Default to the REAL model when a key is present (this is a product; the stub is only a fallback); an explicit
    # PROVIDER always wins (tests force PROVIDER=stub via tests/conftest.py to stay offline).
    provider: str = (
        os.getenv("PROVIDER") or ("anthropic" if os.getenv("ANTHROPIC_API_KEY") else "stub")
    ).strip().lower()
    anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5")
    # Max size (bytes) of a dropped document (real reports run large — 20 MB default).
    max_doc_bytes: int = int(os.getenv("MAX_DOC_BYTES", "20000000"))
    # Long-document handling. `max_draft_chars` is the per-call WINDOW: a doc up to this size is processed in one
    # model call (~120K chars ≈ 30K tokens — comfortable for current models). A larger doc is split into windows
    # and **map-reduced** (each window processed, then merged), capped at `max_chunks` so cost stays bounded; a doc
    # beyond that is processed up to the cap with an honest note. (Copilot is unaffected — it retrieves over the
    # whole doc.) See DECISIONS.md DEC 012.
    max_draft_chars: int = int(os.getenv("MAX_DRAFT_CHARS", "200000"))
    max_chunks: int = int(os.getenv("MAX_CHUNKS", "6"))
    # Merge caps for map-reduced output: the summary keeps its top-N points; the table keeps up to N rows.
    summary_max_points: int = int(os.getenv("SUMMARY_MAX_POINTS", "12"))
    extract_max_items: int = int(os.getenv("EXTRACT_MAX_ITEMS", "60"))
    # Grounding support threshold (fraction of a claim's content tokens that must appear in its best span).
    ground_threshold: float = float(os.getenv("GROUND_THRESHOLD", "0.6"))
    # Copilot ("Ask this document") retrieval: how many passages to consider, and the minimum question↔passage
    # relevance below which we abstain ("not in your document") rather than answer.
    copilot_top_k: int = int(os.getenv("COPILOT_TOP_K", "4"))
    copilot_min_relevance: float = float(os.getenv("COPILOT_MIN_RELEVANCE", "0.12"))
    # Extractor: confidence below this (or a value that fails type-validation) → the field is flagged for review.
    extract_threshold: float = float(os.getenv("EXTRACT_THRESHOLD", "0.75"))
    samples_dir: Path = REPO_ROOT / os.getenv("SAMPLES_DIR", "data/samples")

    def provenance(self) -> dict:
        return {"app_version": __version__, "provider": self.provider}


settings = Settings()
