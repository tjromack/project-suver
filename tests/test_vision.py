"""Read-an-image tool (DEC 041) — Suver's first IMAGE input. The one modality where sanitize-before-egress can't
hold (you can't tokenize PII inside pixels before reading them), so the tool is TRANSPARENT: the image is sent to the
model as-is, the model transcribes only what's visible (never guessing), and the data boundary is applied to the
OUTPUT transcription (detect + flag + a sanitized copy). All deterministic/offline: the stub can't read pixels (→ an
honest 'read it with the real model' note); the boundary-on-output is tested with a transcription supplied directly."""

from __future__ import annotations

import app.pipeline as pipeline
from app.main import app
from app.pipeline import image_media_type, read_image_document
from app.provider import read_image
from app.tools import get
from fastapi.testclient import TestClient

client = TestClient(app)


def test_media_type_detection():
    assert image_media_type("receipt.png") == "image/png"
    assert image_media_type("scan.JPG") == "image/jpeg"
    assert image_media_type("photo.jpeg") == "image/jpeg"
    assert image_media_type("clip.gif") == "image/gif"
    assert image_media_type("shot.webp") == "image/webp"
    assert image_media_type("notes.txt") is None          # not an image → the tool raises a friendly error
    assert image_media_type("doc.pdf") is None
    assert image_media_type("noext") is None


def test_stub_cannot_read_pixels_and_wont_pretend():
    # offline/no-key: read_image returns "" (it won't fabricate a transcription); the pipeline notes this honestly
    assert read_image(b"\x89PNG...", "image/png", "stub") == ""
    r = read_image_document(b"\x89PNG...", "image/png", provider="stub")
    assert r.offline and r.no_text
    assert r.sensitive_count == 0 and r.transcription == ""


def test_boundary_runs_on_the_output_transcription(monkeypatch):
    """⭐ The trust move: the image is sent as-is, but the boundary is applied to the RESULT — sensitive content in
    the transcription is detected, flagged, and tokenized in the sanitized copy offered for downstream use."""
    def fake_read(data, media_type, provider):
        return "Invoice for Jane Doe. Email jane@example.com, SSN 123-45-6789. Total: $250.00."

    monkeypatch.setattr(pipeline, "read_image", fake_read)
    r = read_image_document(b"img", "image/png", provider="anthropic")
    assert not r.offline and not r.no_text
    assert r.sensitive_count >= 2                          # the email + the SSN (at least)
    assert "jane@example.com" in r.transcription           # the raw read is the user's own content (shown locally)
    assert "jane@example.com" not in r.sanitized           # ...but the sanitized copy tokenizes it for sharing
    assert "123-45-6789" not in r.sanitized
    assert r.sensitive_classes                             # e.g. ["email", "ssn"]


def test_no_readable_text_is_honest(monkeypatch):
    monkeypatch.setattr(pipeline, "read_image", lambda d, m, p: "[no readable text]")
    r = read_image_document(b"img", "image/png", provider="anthropic")
    assert r.no_text and r.sensitive_count == 0


def test_tool_registered_and_live():
    t = get("read-image")
    assert t is not None and t.is_live
    assert t.platform == "Documents" and t.no_paste and t.accept_ext.endswith(".webp")


def test_tool_run_validates_input():
    from app.tools import ToolError, ToolInput
    from app.tools.vision import run

    try:
        run(ToolInput())                                  # nothing uploaded
        assert False, "expected ToolError"
    except ToolError:
        pass
    try:
        run(ToolInput(filename="notes.txt", data=b"hi"))  # not an image
        assert False, "expected ToolError"
    except ToolError:
        pass


def test_route_renders_offline_notice():
    # POST an image through the real route (stub provider) → the honest 'read it with the real model' notice, 200
    r = client.post("/t/read-image/run", files={"file": ("receipt.png", b"\x89PNG\r\n\x1a\n", "image/png")})
    assert r.status_code == 200
    assert "How this tool handles trust" in r.text
    assert "sent to the AI as-is" in r.text


def test_hub_lists_the_image_tool():
    r = client.get("/t/read-image")
    assert r.status_code == 200
    assert "Read an image" in r.text
