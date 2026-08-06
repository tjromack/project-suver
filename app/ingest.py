"""Document ingest (Phase 2) — a real file (or pasted text) → plain text.

Supports `.txt / .md / .pdf / .docx` (+ a paste path), with a **size cap**, format detection, and **friendly
errors** — a too-big / unsupported / unreadable file yields a clear message, never a crash. PDF/DOCX libraries are
imported lazily, so text/markdown/paste work with no extra dependencies. No model is involved. See DESIGN.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

from app.config import settings

TEXT_EXTS = {".txt", ".md", ".markdown", ".text", ".csv", ".tsv", ""}
SUPPORTED = {".txt", ".md", ".markdown", ".text", ".pdf", ".docx", ".csv", ".tsv"}


class IngestError(ValueError):
    """A user-facing ingest problem (too big / unsupported / unreadable) — carries a friendly message."""


@dataclass(frozen=True)
class IngestResult:
    text: str
    kind: str          # txt | md | pdf | docx | paste
    chars: int
    note: str = ""     # a non-fatal note to surface (e.g. "extracted 12 pages")


def _ext(filename: str) -> str:
    return PurePosixPath(filename.replace("\\", "/")).suffix.lower()


def _as_bytes(data: bytes | str) -> bytes:
    return data.encode("utf-8") if isinstance(data, str) else data


def _guard_size(data: bytes) -> None:
    cap = settings.max_doc_bytes
    if len(data) > cap:
        raise IngestError(f"That file is larger than the {cap // 1_000_000} MB limit — try a smaller document.")


def extract_text(filename: str, data: bytes | str) -> IngestResult:
    """Extract plain text from a dropped file's bytes. Raises IngestError with a friendly message on any problem."""
    raw = _as_bytes(data)
    _guard_size(raw)
    ext = _ext(filename)
    if ext not in SUPPORTED:
        raise IngestError(f"Sorry — {ext or 'that file type'} isn't supported yet. Try a PDF, Word doc, or text file.")

    if ext in TEXT_EXTS:
        text = raw.decode("utf-8", errors="replace").strip()
        kind = "md" if ext in {".md", ".markdown"} else ("csv" if ext in {".csv", ".tsv"} else "txt")
    elif ext == ".pdf":
        text, kind = _extract_pdf(raw), "pdf"
    elif ext == ".docx":
        text, kind = _extract_docx(raw), "docx"
    else:  # pragma: no cover - guarded above
        raise IngestError("Unsupported file type.")

    text = text.strip()
    if not text:
        raise IngestError("Couldn't find any readable text in that file — is it a scan or an image?")
    note = f"read {kind.upper()} · {len(text):,} characters"
    return IngestResult(text=text, kind=kind, chars=len(text), note=note)


def from_paste(text: str) -> IngestResult:
    """The paste-text path."""
    _guard_size(text.encode("utf-8"))
    t = (text or "").strip()
    if not t:
        raise IngestError("Nothing to summarize yet — paste some text or drop a file.")
    return IngestResult(text=t, kind="paste", chars=len(t), note=f"pasted · {len(t):,} characters")


def _extract_pdf(raw: bytes) -> str:
    try:
        import io

        from pypdf import PdfReader
    except Exception:  # pragma: no cover - dependency missing in dev
        raise IngestError("PDF support isn't installed here. Run `make setup`, or paste the text instead.")
    try:
        reader = PdfReader(io.BytesIO(raw))
        return "\n\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception:
        raise IngestError("Couldn't read that PDF — it may be corrupted or password-protected.")


def _extract_docx(raw: bytes) -> str:
    try:
        import io

        import docx
    except Exception:  # pragma: no cover - dependency missing in dev
        raise IngestError("Word support isn't installed here. Run `make setup`, or paste the text instead.")
    try:
        d = docx.Document(io.BytesIO(raw))
        return "\n".join(p.text for p in d.paragraphs)
    except Exception:
        raise IngestError("Couldn't read that Word document — it may be corrupted.")
