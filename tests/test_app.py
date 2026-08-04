"""Phase 5+6 — the tool-app shell, the Summarize tool end-to-end, and the hub. Stub-backed (no network)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_hub_lists_tools():
    r = client.get("/")
    assert r.status_code == 200
    assert "Summarize" in r.text
    assert "Live" in r.text and "Soon" in r.text          # the live tool + the coming-soon platform
    assert "removes the prompt" in r.text or "no prompt" in r.text.lower()


def test_tool_shell_renders():
    r = client.get("/t/summarize")
    assert r.status_code == 200
    assert "Drop a document" in r.text
    assert "Summarize" in r.text                            # the single primary action
    assert "prompt" in r.text.lower()                       # the no-prompt promise is on the page


def test_unknown_tool_404():
    r = client.get("/t/does-not-exist")
    assert r.status_code == 404


def test_coming_soon_tool_shows_placeholder():
    r = client.get("/t/draft")
    assert r.status_code == 200
    assert "Coming soon" in r.text


def test_summarize_run_paste_is_cited():
    doc = ("The migration completed on schedule. Latency dropped by 40 percent after the cutover. "
           "The team retired three legacy load balancers. Incidents fell to a two-year low.")
    r = client.post("/t/summarize/run", data={"paste": doc})
    assert r.status_code == 200
    assert "source ·" in r.text                             # each claim exposes its citation
    assert "🛡" in r.text                                    # the trust chip
    assert "No sensitive items detected" in r.text          # clean doc


def test_summarize_run_rehydrates_planted_ssn_in_view_only():
    doc = "Contact Jane Roe (SSN 123-45-6789). Throughput rose twelve percent across the platform this quarter."
    r = client.post("/t/summarize/run", data={"paste": doc})
    assert r.status_code == 200
    # the trust chip shows the boundary handled items…
    assert "sensitive item" in r.text
    # …and the user sees their real value back (re-hydrated locally in the rendered view)
    assert "123-45-6789" in r.text


def test_empty_input_is_friendly():
    r = client.post("/t/summarize/run", data={"paste": "   "})
    assert r.status_code == 200
    assert "Add a document or paste" in r.text


def test_healthz():
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and "summarize" in body["tools"]
