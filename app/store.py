"""Accounts & saved work — the persistence MVP (DEC 034).

A lean, dependency-free store (stdlib `sqlite3`) so a signed-in user can **save their work and come back to it** —
log out, walk away, return to the tools and documents they had going. Anonymous use is untouched: no account is
required to run any tool; signing in simply *adds* save + history.

Design for transferability (Trevor's ask — a generic MVP that adopts to a real org with minimal change):
  - **Auth is email + password** (the only universal, dependency-free option — no per-client OAuth setup, no
    assumption about a user's identity ecosystem). Passwords are salted + `pbkdf2_hmac` hashed (stdlib). The seam is
    deliberately small so **Google/Microsoft social login and org-SSO (OIDC/SAML)** slot in behind `authenticate()`
    later without touching callers. See `CLIENT-ADAPTATION.md`.
  - **An `org` field on every user** — the unit a client licenses; the hook for per-org branding, policy, and (later)
    a per-org model choice / bring-your-own-key (see `EMBEDDINGS-PLAN.md`).
  - **SQLite, one file** — trivial to run, back up, and hand to a client; swap for Postgres by changing this module
    only. Production hardening (encryption at rest, per-org isolation, CSRF) is documented in `CLIENT-ADAPTATION.md`.

The store never calls a model. It holds the user's own content locally; the trust pipeline (sanitize-before-egress)
is unchanged — saving a document stores the user's text on the server, exactly as documented for the client.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from app.config import settings

_PBKDF2_ROUNDS = 240_000


@dataclass(frozen=True)
class User:
    id: int
    email: str
    org: str
    created_at: float


@dataclass(frozen=True)
class SavedItem:
    id: int
    user_id: int
    tool_slug: str
    title: str
    text: str
    query: str
    created_at: float


def _conn() -> sqlite3.Connection:
    path = Path(settings.db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    return con


def init_db() -> None:
    """Create tables if absent. Idempotent; called at app startup."""
    with _conn() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                pw_salt TEXT NOT NULL,
                pw_hash TEXT NOT NULL,
                org TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS saved_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                tool_slug TEXT NOT NULL,
                title TEXT NOT NULL,
                text TEXT NOT NULL DEFAULT '',
                query TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL
            );
            """
        )


# --- password hashing (stdlib pbkdf2; the seam behind which real auth/SSO can slot) ------------------

def _hash_password(password: str, salt: str) -> str:
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), _PBKDF2_ROUNDS)
    return dk.hex()


def _verify_password(password: str, salt: str, expected: str) -> bool:
    return secrets.compare_digest(_hash_password(password, salt), expected)


class AccountError(ValueError):
    """A friendly, user-facing account error (email taken, bad credentials, weak input)."""


# --- users -------------------------------------------------------------------------------------------

def create_user(email: str, password: str, org: str = "") -> User:
    email = (email or "").strip().lower()
    if "@" not in email or len(email) < 5:
        raise AccountError("Enter a valid email address.")
    if len(password or "") < 8:
        raise AccountError("Use a password of at least 8 characters.")
    salt = secrets.token_hex(16)
    pw_hash = _hash_password(password, salt)
    now = time.time()
    try:
        with _conn() as con:
            cur = con.execute(
                "INSERT INTO users (email, pw_salt, pw_hash, org, created_at) VALUES (?,?,?,?,?)",
                (email, salt, pw_hash, (org or "").strip(), now),
            )
            uid = cur.lastrowid
    except sqlite3.IntegrityError as e:
        raise AccountError("That email is already registered — sign in instead.") from e
    return User(id=uid, email=email, org=(org or "").strip(), created_at=now)


def authenticate(email: str, password: str) -> User:
    """Verify credentials → the User, or raise. This is the seam an SSO/social backend replaces later."""
    email = (email or "").strip().lower()
    with _conn() as con:
        row = con.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if row is None or not _verify_password(password or "", row["pw_salt"], row["pw_hash"]):
        raise AccountError("That email and password don't match.")
    return User(id=row["id"], email=row["email"], org=row["org"], created_at=row["created_at"])


def get_user(user_id: int) -> User | None:
    with _conn() as con:
        row = con.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return User(row["id"], row["email"], row["org"], row["created_at"]) if row else None


# --- sessions (a random opaque token in an httponly cookie; validated server-side) -------------------

def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    with _conn() as con:
        con.execute("INSERT INTO sessions (token, user_id, created_at) VALUES (?,?,?)",
                    (token, user_id, time.time()))
    return token


def session_user(token: str | None) -> User | None:
    if not token:
        return None
    with _conn() as con:
        row = con.execute(
            "SELECT u.*, s.created_at AS s_created FROM sessions s JOIN users u ON u.id = s.user_id "
            "WHERE s.token = ?", (token,)
        ).fetchone()
    if row is None:
        return None
    # Expire stale sessions server-side (pilot-grade; a stolen/forgotten cookie doesn't live forever).
    if time.time() - row["s_created"] > settings.session_ttl_days * 86400:
        end_session(token)
        return None
    return User(row["id"], row["email"], row["org"], row["created_at"])


def end_session(token: str | None) -> None:
    if not token:
        return
    with _conn() as con:
        con.execute("DELETE FROM sessions WHERE token = ?", (token,))


# --- saved work --------------------------------------------------------------------------------------

def save_item(user_id: int, tool_slug: str, title: str, text: str = "", query: str = "") -> SavedItem:
    now = time.time()
    title = (title or "Untitled").strip()[:200]
    with _conn() as con:
        cur = con.execute(
            "INSERT INTO saved_items (user_id, tool_slug, title, text, query, created_at) VALUES (?,?,?,?,?,?)",
            (user_id, tool_slug, title, text or "", query or "", now),
        )
        iid = cur.lastrowid
    return SavedItem(iid, user_id, tool_slug, title, text or "", query or "", now)


def list_items(user_id: int) -> list[SavedItem]:
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM saved_items WHERE user_id = ? ORDER BY created_at DESC", (user_id,)
        ).fetchall()
    return [SavedItem(r["id"], r["user_id"], r["tool_slug"], r["title"], r["text"], r["query"], r["created_at"])
            for r in rows]


def get_item(user_id: int, item_id: int) -> SavedItem | None:
    with _conn() as con:
        r = con.execute("SELECT * FROM saved_items WHERE id = ? AND user_id = ?", (item_id, user_id)).fetchone()
    return SavedItem(r["id"], r["user_id"], r["tool_slug"], r["title"], r["text"], r["query"], r["created_at"]) if r else None


def delete_item(user_id: int, item_id: int) -> None:
    with _conn() as con:
        con.execute("DELETE FROM saved_items WHERE id = ? AND user_id = ?", (item_id, user_id))
