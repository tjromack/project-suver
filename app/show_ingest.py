"""`make ingest FILE=path` — extract plain text from a real document (a quick check)."""

from __future__ import annotations

import sys
from pathlib import Path

from app.ingest import IngestError, extract_text


def main(argv: list[str]) -> int:
    if not argv:
        print('usage: python -m app.show_ingest <path>')
        return 2
    p = Path(argv[0])
    try:
        r = extract_text(p.name, p.read_bytes())
    except IngestError as e:
        print(f"[ingest error] {e}")
        return 1
    print(f"kind={r.kind}  chars={r.chars:,}  ({r.note})")
    preview = r.text[:600]
    print("--- preview ---")
    print(preview + (" …" if r.chars > 600 else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
