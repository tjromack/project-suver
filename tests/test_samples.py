"""'Try an example' (DEC 037) — a curated built-in sample per single-input tool, so a first-time visitor sees a real
cited result in one click without bringing a document. Multi-document tools (Compare, Ask-across) deliberately opt
out (their input shape doesn't fit a one-click paste)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.tools import get, load_builtin

load_builtin()

_SINGLE_INPUT = ["summarize", "copilot", "draft", "extractor", "converse",
                 "meeting-actions", "triage", "reply", "spreadsheet", "data-summary", "chart"]

client = TestClient(app)


def test_every_single_input_tool_has_a_sample():
    for slug in _SINGLE_INPUT:
        t = get(slug)
        assert t is not None and t.has_sample, f"{slug} is missing a built-in example"
        assert t.sample_text.strip()


def test_multi_document_tools_opt_out_of_samples():
    for slug in ("compare", "ask-across"):
        assert not get(slug).has_sample   # their multi-input shape doesn't fit one-click paste


def test_tool_page_offers_try_an_example_with_the_sample_payload():
    h = client.get("/t/copilot").text
    assert 'id="trybtn"' in h                         # the button
    assert 'id="sampledata"' in h                     # the JSON the button loads
    assert "governing law" in h                       # the sample question is present for the JS to fill


def test_sample_runs_end_to_end():
    t = get("copilot")
    r = client.post("/t/copilot/run", data={"paste": t.sample_text, "query": t.sample_query})
    assert r.status_code == 200
    assert "york" in r.text.lower()   # a grounded, cited answer from the sample (governing law → State of New York)
