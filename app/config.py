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
    # Semantic-recall retrieval (DEC 032): the model expands the sanitized question into a few alternative phrasings,
    # and a passage is ranked by the BEST match against any phrasing — so a synonym/paraphrase ("auto-renew" ≈
    # "automatically renews", "fee" ≈ "shall pay") still surfaces. Expansion runs once per question (not per doc);
    # the grounding gate is UNCHANGED, so recall rises without loosening the trust guarantee. Off → today's behavior.
    retrieval_expand: bool = os.getenv("RETRIEVAL_EXPAND", "1").strip().lower() not in ("0", "false", "no", "")
    retrieval_max_expansions: int = int(os.getenv("RETRIEVAL_MAX_EXPANSIONS", "6"))
    # Extractor: confidence below this (or a value that fails type-validation) → the field is flagged for review.
    extract_threshold: float = float(os.getenv("EXTRACT_THRESHOLD", "0.75"))
    # Triage ("Triage messages"): cap the messages processed in one pass; a classification below the confidence
    # threshold is flagged 'review' rather than shown as a confident bucket.
    triage_max_messages: int = int(os.getenv("TRIAGE_MAX_MESSAGES", "40"))
    triage_threshold: float = float(os.getenv("TRIAGE_THRESHOLD", "0.6"))
    # "Ask your spreadsheet": how many rows the model sees as a SAMPLE (never the full dataset), and how many
    # supporting rows to show under a computed answer.
    table_sample_rows: int = int(os.getenv("TABLE_SAMPLE_ROWS", "6"))
    table_max_rows_shown: int = int(os.getenv("TABLE_MAX_ROWS_SHOWN", "12"))
    # "Chart your spreadsheet": at most this many bars per chart, and this many numeric measures charted.
    chart_max_bars: int = int(os.getenv("CHART_MAX_BARS", "12"))
    chart_max_measures: int = int(os.getenv("CHART_MAX_MEASURES", "3"))
    samples_dir: Path = REPO_ROOT / os.getenv("SAMPLES_DIR", "data/samples")
    # Accounts & saved work (persistence MVP, DEC 034). One SQLite file — trivial to run/back up/hand to a client;
    # swap for Postgres by changing app/store.py only. Cookie name for the opaque session token. Anonymous use needs
    # neither. The name of the (generic, made-up) demo org shown in the account UI — rebrand per client.
    db_path: Path = REPO_ROOT / os.getenv("SUVER_DB", "data/suver.db")
    session_cookie: str = os.getenv("SESSION_COOKIE", "suver_session")
    org_name: str = os.getenv("ORG_NAME", "Northwind Legal (demo)")
    # Pilot-grade hardening (DEC 035). Sessions expire after N days; the cookie is marked Secure in production (behind
    # HTTPS — set COOKIE_SECURE=1 on deploy); sign-in/registration is rate-limited to blunt credential-stuffing.
    session_ttl_days: int = int(os.getenv("SESSION_TTL_DAYS", "30"))
    cookie_secure: bool = os.getenv("COOKIE_SECURE", "0").strip().lower() in ("1", "true", "yes", "on")
    auth_rate_max: int = int(os.getenv("AUTH_RATE_MAX", "8"))          # attempts per window, per client IP
    auth_rate_window_s: int = int(os.getenv("AUTH_RATE_WINDOW_S", "300"))
    # Daily usage quotas (DEC 037) — the guardrail that makes public exposure safe: a stranger can't run up the API
    # bill. Counted per model-invoking run, per subject (anonymous → per IP; signed-in → per user, by plan tier).
    # Billing is deferred; "pro" is set manually for now (`store.set_plan`) and just raises the cap.
    quota_anon: int = int(os.getenv("QUOTA_ANON", "15"))
    quota_free: int = int(os.getenv("QUOTA_FREE", "75"))
    quota_pro: int = int(os.getenv("QUOTA_PRO", "100000"))

    def provenance(self) -> dict:
        return {"app_version": __version__, "provider": self.provider}


settings = Settings()
