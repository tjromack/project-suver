"""Ephemeral conversation state — for the Converse tool ("Chat with a document").

The one-shot tools are stateless (one input → one result). Converse is multi-turn: the document is sanitized and
split **once**, and each follow-up question runs against the stored (safe) spans — the model never re-reads the
raw document, and only the sanitized spans + a local token map ever persist. State is **in-memory and ephemeral**
(lost on restart), bounded by a simple LRU cap — a demo/pilot posture, not a datastore. The token map lives only
inside this process (the boundary's local trust zone), never leaves.
"""

from __future__ import annotations

import secrets
from collections import OrderedDict
from dataclasses import dataclass, field

_MAX_SESSIONS = 200


@dataclass
class ConverseTurn:
    question: str                 # re-hydrated for display
    answer: str
    citations: list = field(default_factory=list)   # Claim list (re-hydrated)
    answered: bool = True         # False → abstained ("not in your document")


@dataclass
class ConverseSession:
    id: str
    spans: list = field(default_factory=list)        # sanitized doc spans (never raw)
    token_map: dict = field(default_factory=dict)    # LOCAL ONLY — re-hydrates for display
    handled_count: int = 0
    handled_classes: list = field(default_factory=list)
    decision: str = "clear"
    doc_kind: str = "text"
    source_chars: int = 0
    provider: str = "stub"
    turns: list = field(default_factory=list)         # ConverseTurn
    safe_questions: list = field(default_factory=list)  # sanitized prior questions (for follow-up retrieval context)


_SESSIONS: "OrderedDict[str, ConverseSession]" = OrderedDict()


def create_session(**kw) -> ConverseSession:
    """Make + store a new session with a fresh id. Evicts the oldest when the cap is hit."""
    sid = secrets.token_urlsafe(12)
    s = ConverseSession(id=sid, **kw)
    _SESSIONS[sid] = s
    _SESSIONS.move_to_end(sid)
    while len(_SESSIONS) > _MAX_SESSIONS:
        _SESSIONS.popitem(last=False)
    return s


def get_session(sid: str | None) -> ConverseSession | None:
    s = _SESSIONS.get(sid or "")
    if s is not None:
        _SESSIONS.move_to_end(sid)   # keep active conversations warm
    return s
