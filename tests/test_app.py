"""Phase 5+6 — the tool-app shell, the Summarize tool end-to-end, and the hub. Stub-backed (no network)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_hub_lists_tools():
    r = client.get("/")
    assert r.status_code == 200
    # the Documents tools are listed on the platform front door
    for name in ("Summarize", "Ask this document", "Draft from a document", "Extract fields"):
        assert name in r.text
    assert "Documents platform" in r.text            # the product framing
    assert "Governed by design" in r.text            # the trust band (the buyer's "yes")
    assert "no prompt" in r.text.lower()             # the no-prompt promise
    # the read · ask · write · pull-data lanes
    for lane in ("Read", "Ask", "Write", "Pull data"):
        assert lane in r.text


def test_hub_shows_a_second_platform():
    """⭐ Suver is a multi-platform HUB, not one Documents app — the hub groups tools by platform."""
    r = client.get("/")
    assert r.status_code == 200
    assert "Communications platform" in r.text       # platform #2
    assert "Meeting notes" in r.text                  # its first tool
    assert "Triage messages" in r.text                # its second tool
    assert "Draft a reply" in r.text                  # its third tool
    # the Documents platform still renders before Communications (stable order)
    assert r.text.index("Documents platform") < r.text.index("Communications platform")


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


def test_compare_shell_has_two_drop_zones():
    r = client.get("/t/compare")
    assert r.status_code == 200
    assert "Document A" in r.text and "Document B" in r.text
    assert 'name="file2"' in r.text and 'name="paste2"' in r.text     # the second input
    assert "What to compare" in r.text                                # the field-set select


def test_compare_run_shows_a_difference_table():
    a = {"paste": "Vendor: Acme\nAmount: $1,200.00", "paste2": "Vendor: Acme\nAmount: $1,500.00", "choice": "facts"}
    r = client.post("/t/compare/run", data=a)
    assert r.status_code == 200
    assert "<table" in r.text
    assert "difference" in r.text.lower()
    assert "never picks which document is right" in r.text            # the never-decides promise


def test_compare_needs_a_second_document():
    r = client.post("/t/compare/run", data={"paste": "Only one document here.", "choice": "facts"})
    assert r.status_code == 200
    assert "second document" in r.text.lower()


def test_converse_start_then_followup_over_the_route():
    doc = "The launch date is April 3. The venue is the downtown center. Catering is by Bluebird."
    first = client.post("/t/converse/run", data={"paste": doc, "query": "When is the launch?"})
    assert first.status_code == 200
    assert "April 3" in first.text
    assert "data-session=" in first.text                    # the session id the shell will reuse
    import re
    sid = re.search(r'data-session="([^"]+)"', first.text).group(1)
    # a follow-up sends only the session + the next question (no document)
    second = client.post("/t/converse/run", data={"session": sid, "query": "Who is doing catering?"})
    assert second.status_code == 200
    assert "Bluebird" in second.text
    assert "2 turns" in second.text                         # the conversation grew


def test_converse_shell_is_a_chat():
    r = client.get("/t/converse")
    assert r.status_code == 200
    assert "Chat with a document" in r.text
    assert "isChat=true" in r.text                          # the shell renders the chat behaviour


def test_meeting_actions_run_produces_a_grounded_table():
    notes = ("Standup — Tuesday.\n"
             "Finance will send the revised budget by Friday.\n"
             "We chatted about the new mugs.\n"
             "Action item: book the venue.\n")
    r = client.post("/t/meeting-actions/run", data={"paste": notes})
    assert r.status_code == 200
    assert "<table" in r.text
    assert "budget" in r.text.lower()
    assert "Finance" in r.text                              # owner shown when stated
    assert "source ·" in r.text                             # each action cites its line (cite-or-drop)
    assert "🛡" in r.text                                    # the trust chip


def test_meeting_actions_empty_is_honest():
    r = client.post("/t/meeting-actions/run", data={"paste": "It was a lovely, uneventful afternoon."})
    assert r.status_code == 200
    assert "No action items" in r.text


def test_triage_run_sorts_messages():
    inbox = ("Can you approve the budget by Friday?\n\n"
             "FLASH SALE 50% off — unsubscribe here.\n\n"
             "FYI the office is closed Monday.")
    r = client.post("/t/triage/run", data={"paste": inbox})
    assert r.status_code == 200
    assert "Needs reply" in r.text or "Action needed" in r.text
    assert "Can ignore" in r.text
    assert "🛡" in r.text


def test_triage_empty_is_honest():
    r = client.post("/t/triage/run", data={"paste": "   "})
    assert r.status_code == 200
    assert "Paste your messages" in r.text            # the friendly empty-input message


def test_hub_shows_the_data_platform():
    """⭐ platform #3 — Data & Analysis (a new tabular modality) appears as its own section, after Communications."""
    r = client.get("/")
    assert r.status_code == 200
    assert "Data &amp; Analysis platform" in r.text or "Data & Analysis platform" in r.text
    assert "Ask your spreadsheet" in r.text
    assert "Summarize a spreadsheet" in r.text                # its second tool
    assert "Chart your spreadsheet" in r.text                 # its third tool
    assert r.text.index("Communications platform") < r.text.index("Analysis platform")


def test_spreadsheet_run_computes_an_answer():
    csv = "Region,Revenue\nWest,4800\nEast,3600\nWest,5400\n"
    r = client.post("/t/spreadsheet/run", data={"paste": csv, "query": "total Revenue?"})
    assert r.status_code == 200
    assert "13,800" in r.text                             # 4800+3600+5400, computed in code
    assert "computed locally" in r.text
    assert "🛡" in r.text


def test_spreadsheet_needs_a_question():
    r = client.post("/t/spreadsheet/run", data={"paste": "A,B\n1,2", "query": "  "})
    assert r.status_code == 200
    assert "Type a question" in r.text


def test_data_summary_run_shows_profile():
    csv = "Region,Revenue\nWest,4800\nEast,3600\nWest,5400\n"
    r = client.post("/t/data-summary/run", data={"paste": csv})
    assert r.status_code == 200
    assert "COMPUTED COLUMN PROFILE" in r.text
    assert "total 13,800" in r.text                     # computed sum shown in the profile
    assert "🛡" in r.text


def test_chart_run_renders_bars():
    csv = "Region,Revenue\nWest,4800\nEast,3600\nWest,5400\n"
    r = client.post("/t/chart/run", data={"paste": csv})
    assert r.status_code == 200
    assert "Total Revenue by Region" in r.text          # the chart title
    assert "10,200" in r.text                            # West total (4800+5400), a bar value
    assert "nothing sent to a model" in r.text          # the fully-local trust line


def test_reply_shell_has_an_intent_select():
    r = client.get("/t/reply")
    assert r.status_code == 200
    assert "<select" in r.text and 'name="choice"' in r.text
    assert "Acknowledge" in r.text or "Politely decline" in r.text


def test_reply_run_drafts_with_placeholders():
    r = client.post("/t/reply/run", data={"paste": "Can you send the report?", "choice": "answer"})
    assert r.status_code == 200
    assert "fill in" in r.text                          # the placeholders note
    assert "not invented" in r.text                     # the discipline line
    assert "🛡" in r.text


def test_healthz():
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and "summarize" in body["tools"]
