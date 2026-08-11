"""Daily usage quotas (DEC 037) — the guardrail that makes public exposure safe: a stranger can't run up the API
bill. Model-invoking runs count against a per-subject daily cap by tier; the fully-local Chart tool is exempt."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app import store
from app.config import settings
from app.main import _quota_subject, app

client = TestClient(app)

_DOC = {"paste": "The deadline is March 1.", "query": "What is the deadline?"}


class _Req:  # a minimal stand-in for the request's client IP
    client = type("c", (), {"host": "9.9.9.9"})()


def test_quota_subject_tiers():
    # anonymous → per-IP, the anon cap
    subj, limit = _quota_subject(_Req(), None)
    assert subj == "ip:9.9.9.9" and limit == settings.quota_anon
    # signed-in free → per-user, the free cap; pro → the (much higher) pro cap
    u = store.create_user("tier@example.com", "goodpass12")
    assert _quota_subject(_Req(), store.get_user(u.id)) == (f"u:{u.id}", settings.quota_free)
    store.set_plan(u.id, "pro")
    assert _quota_subject(_Req(), store.get_user(u.id)) == (f"u:{u.id}", settings.quota_pro)


def test_anonymous_quota_enforced_with_friendly_message():
    # burn the anonymous allowance for this IP, then the next model run is blocked (429) with guidance
    for _ in range(settings.quota_anon):
        store.bump_usage("ip:testclient")
    r = client.post("/t/copilot/run", data=_DOC)
    assert r.status_code == 429
    assert "DAILY LIMIT" in r.text.upper() and "sign in" in r.text.lower()


def test_successful_run_counts_against_the_quota():
    assert store.usage_today("ip:testclient") == 0
    assert client.post("/t/copilot/run", data=_DOC).status_code == 200
    assert store.usage_today("ip:testclient") == 1


def test_chart_is_exempt_from_the_quota():
    # even at/over the cap, the fully-local Chart tool still runs (no model call = no API cost) and doesn't count
    for _ in range(settings.quota_anon + 5):
        store.bump_usage("ip:testclient")
    r = client.post("/t/chart/run", data={"paste": "Region,Sales\nWest,100\nEast,220\nWest,140"})
    assert r.status_code == 200
    # chart didn't increment the model-run counter beyond what we bumped
    assert store.usage_today("ip:testclient") == settings.quota_anon + 5


def test_pro_plan_gets_the_higher_ceiling_end_to_end():
    c = TestClient(app)
    c.post("/register", data={"email": "pro@example.com", "password": "goodpass12"})
    u = store.authenticate("pro@example.com", "goodpass12")
    store.set_plan(u.id, "pro")
    # push this user's count past the FREE cap — a pro plan keeps going
    for _ in range(settings.quota_free + 2):
        store.bump_usage(f"u:{u.id}")
    assert c.post("/t/copilot/run", data=_DOC).status_code == 200   # not blocked — pro ceiling is far higher
