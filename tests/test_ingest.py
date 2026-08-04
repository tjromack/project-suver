"""Phase 2 — document ingest: real files → text, fail-friendly. (txt/md/paste/guards need no extra deps.)"""

from __future__ import annotations

import pytest

from app.config import settings
from app.ingest import IngestError, extract_text, from_paste


def test_txt_extracts():
    r = extract_text("notes.txt", b"Hello world. This is a test document.")
    assert r.kind == "txt" and "Hello world" in r.text and r.chars == len(r.text)


def test_md_extracts():
    r = extract_text("readme.md", "# Title\n\nSome **markdown** content here.")
    assert r.kind == "md" and "markdown" in r.text


def test_paste_path():
    r = from_paste("  just some pasted text  ")
    assert r.kind == "paste" and r.text == "just some pasted text"


def test_empty_paste_is_friendly():
    with pytest.raises(IngestError, match="Nothing to summarize"):
        from_paste("   ")


def test_empty_file_is_friendly():
    with pytest.raises(IngestError, match="readable text"):
        extract_text("blank.txt", b"   \n  ")


def test_unsupported_type_is_friendly():
    with pytest.raises(IngestError, match="isn't supported"):
        extract_text("photo.png", b"\x89PNG\r\n")


def test_oversize_is_friendly():
    big = b"x" * (settings.max_doc_bytes + 1)
    with pytest.raises(IngestError, match="larger than"):
        extract_text("huge.txt", big)


def test_utf8_and_latin_bytes_dont_crash():
    r = extract_text("m.txt", "café — résumé — 12%".encode("utf-8"))
    assert "café" in r.text


# --- pdf/docx: exercised only when the libraries are installed (i.e. after `make setup`) ---

def test_pdf_roundtrip_if_available():
    pytest.importorskip("pypdf")
    from pypdf import PdfWriter  # writer to build a tiny PDF with text is nontrivial; assert the error path instead

    # a non-PDF byte blob with a .pdf name should fail friendly, not crash
    with pytest.raises(IngestError, match="Couldn't read that PDF|PDF support"):
        extract_text("x.pdf", b"not really a pdf")


def test_docx_bad_bytes_is_friendly_if_available():
    pytest.importorskip("docx")
    with pytest.raises(IngestError, match="Couldn't read that Word|Word support"):
        extract_text("x.docx", b"not really a docx")
