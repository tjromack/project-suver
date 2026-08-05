"""Phase 5+6 — the tool-app shell, the Summarize tool end-to-end, and the hub. Stub-backed (no network)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_hub_lists_tools():
    r = client.get("/")
    assert r.status_code == 200
    # all four Documents tools are listed on the platform front door
    for name in ("Summarize", "Ask this document", "Draft from a document", "Extract fields"):
        assert name in r.text
    assert "Documents platform" in r.text            # the product framing
    assert "Governed by design" in r.text            # the trust band (the buyer's "yes")
    assert "no prompt" in r.text.lower()             # the no-prompt promise
    # the read · ask · write · pull-data lanes
    for lane in ("Read", "Ask", "Write", "Pull data"):
        assert lane in r.text


def test_tool_shell_renders():
    r = client.get("/t/summarize")
    assert r.status_code == 200
    assert "Drop a document" in r.text
    assert "Summarize" in r.text                            # the single primary action
    assert "prompt" in r.text.lower()                       # the no-prompt promise is on the page


def test_unknown_tool_404():
    r = client.get("/t/does-not-exist")
    assert r.status_code == 404


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


def test_copilot_shell_has_a_question_field():
    r = client.get("/t/copilot")
    assert r.status_code == 200
    assert "Your question" in r.text                        # the shell renders the query field
    assert 'name="query"' in r.text


def test_copilot_run_answers_with_citation():
    doc = "The launch date is April 3. The venue is the downtown conference center."
    r = client.post("/t/copilot/run", data={"paste": doc, "query": "When is the launch?"})
    assert r.status_code == 200
    assert "April 3" in r.text
    assert "From your document" in r.text                    # the sources panel


def test_copilot_abstains_in_the_ui():
    doc = "The launch date is April 3."
    r = client.post("/t/copilot/run", data={"paste": doc, "query": "What is the refund policy?"})
    assert r.status_code == 200
    assert "Not in your document" in r.text


def test_copilot_needs_a_question():
    r = client.post("/t/copilot/run", data={"paste": "Some document text here.", "query": "  "})
    assert r.status_code == 200
    assert "Type a question" in r.text


def test_draft_shell_has_a_kind_select():
    r = client.get("/t/draft")
    assert r.status_code == 200
    assert "<select" in r.text and 'name="choice"' in r.text
    assert "Summary memo" in r.text                          # the pickable kinds


def test_draft_run_produces_a_cited_memo():
    doc = ("Project Atlas is a company-wide billing migration that began in March across four regions and cut "
           "invoice errors by thirty percent. The finance team must finish reconciliation by June 30.")
    r = client.post("/t/draft/run", data={"paste": doc, "choice": "memo"})
    assert r.status_code == 200
    assert "Overview" in r.text or "Key Points" in r.text     # section headings
    assert "from your document" in r.text.lower()             # per-section citations
    assert "🛡" in r.text                                      # the trust chip


def test_draft_blocks_do_not_fabricate():
    r = client.post("/t/draft/run", data={"paste": "x y z.", "choice": "memo"})
    assert r.status_code == 200
    assert "Nothing drafted" in r.text


def test_extractor_shell_has_a_fieldset_select():
    r = client.get("/t/extractor")
    assert r.status_code == 200
    assert "<select" in r.text and 'name="choice"' in r.text
    assert "Dates &amp; deadlines" in r.text or "Key facts" in r.text


def test_extractor_run_produces_a_typed_table():
    doc = "Subtotal: $1,200.00\nTax: $96.00\nTotal: $1,296.00"
    r = client.post("/t/extractor/run", data={"paste": doc, "choice": "amounts"})
    assert r.status_code == 200
    assert "<table" in r.text
    assert "Confidence" in r.text
    assert "🛡" in r.text


def test_extractor_empty_is_honest():
    r = client.post("/t/extractor/run", data={"paste": "The sky is blue.", "choice": "dates"})
    assert r.status_code == 200
    assert "No dates" in r.text


def test_healthz():
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and "summarize" in body["tools"]
