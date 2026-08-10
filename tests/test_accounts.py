"""Accounts & saved work (persistence MVP, DEC 034) — store logic + the auth/save/resume routes.

Anonymous use must stay fully working (no tool requires an account); signing in ADDS save + history. The store uses
a throwaway SQLite DB (see conftest). Emails are unique per test to avoid cross-test collisions on the shared DB.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import store
from app.main import app
from app.store import AccountError

client = TestClient(app)


# --- store: hashing, users, sessions, saved items ----------------------------------------------------

def test_password_is_salted_and_hashed_not_stored_plaintext():
    u = store.create_user("hash@example.com", "correct horse battery", org="Acme")
    with store._conn() as con:
        row = con.execute("SELECT pw_hash, pw_salt FROM users WHERE id=?", (u.id,)).fetchone()
    assert "correct horse battery" not in row["pw_hash"]
    assert len(row["pw_salt"]) >= 16 and len(row["pw_hash"]) >= 32


def test_authenticate_roundtrip_and_wrong_password():
    store.create_user("auth@example.com", "supersecret1")
    assert store.authenticate("auth@example.com", "supersecret1").email == "auth@example.com"
    with pytest.raises(AccountError):
        store.authenticate("auth@example.com", "wrongpass1")
    with pytest.raises(AccountError):
        store.authenticate("nobody@example.com", "whatever12")


def test_duplicate_email_and_weak_input_rejected():
    store.create_user("dup@example.com", "goodpass12")
    with pytest.raises(AccountError):
        store.create_user("dup@example.com", "goodpass12")   # taken
    with pytest.raises(AccountError):
        store.create_user("bad", "goodpass12")               # invalid email
    with pytest.raises(AccountError):
        store.create_user("weak@example.com", "short")       # weak password


def test_sessions_resolve_and_end():
    u = store.create_user("sess@example.com", "goodpass12")
    tok = store.create_session(u.id)
    assert store.session_user(tok).id == u.id
    store.end_session(tok)
    assert store.session_user(tok) is None
    assert store.session_user(None) is None


def test_saved_items_are_per_user_and_isolated():
    a = store.create_user("owner-a@example.com", "goodpass12")
    b = store.create_user("owner-b@example.com", "goodpass12")
    it = store.save_item(a.id, "copilot", "My contract", text="the fee is $12,000", query="what is the fee?")
    assert store.get_item(a.id, it.id).title == "My contract"
    assert store.get_item(b.id, it.id) is None          # b can't see a's item
    assert [i.id for i in store.list_items(a.id)] == [it.id]
    store.delete_item(a.id, it.id)
    assert store.list_items(a.id) == []


# --- routes: the anonymous flow is untouched; sign-in adds save/history ------------------------------

def test_anonymous_use_still_works_no_account_required():
    assert client.get("/").status_code == 200                       # hub
    assert client.get("/t/copilot").status_code == 200              # a tool page
    r = client.post("/t/copilot/run", data={"paste": "The deadline is March 1.", "query": "What is the deadline?"})
    assert r.status_code == 200 and "March 1" in r.text            # tool runs with no login
    # protected pages redirect anonymous users to sign in
    assert client.get("/workspace", follow_redirects=False).status_code == 303
    assert client.post("/save", data={"tool_slug": "copilot", "paste": "x"}).status_code == 401


def test_register_login_logout_via_routes():
    c = TestClient(app)
    r = c.post("/register", data={"email": "flow@example.com", "password": "goodpass12", "org": "Acme", "next": "/"},
               follow_redirects=False)
    assert r.status_code == 303 and c.cookies.get("suver_session")
    # the nav now shows the signed-in user
    assert "flow@example.com" in c.get("/").text
    c.post("/logout", follow_redirects=False)
    assert "Sign in" in c.get("/").text


def test_save_then_resume_roundtrip():
    c = TestClient(app)
    c.post("/register", data={"email": "save@example.com", "password": "goodpass12", "next": "/"})
    c.post("/save", data={"tool_slug": "copilot", "title": "Lease",
                          "paste": "The rent is $2,400 per month.", "query": "What is the rent?"})
    ws = c.get("/workspace")
    assert ws.status_code == 200 and "Lease" in ws.text
    u = store.authenticate("save@example.com", "goodpass12")
    item = store.list_items(u.id)[0]
    page = c.get(f"/t/copilot?item={item.id}")
    assert page.status_code == 200
    assert "The rent is $2,400 per month." in page.text and "What is the rent?" in page.text  # prefilled to resume
