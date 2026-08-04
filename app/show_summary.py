"""`make summarize FILE=path` / `make summarize TEXT="..."` — run the full pipeline and print the cited summary.

Also `make sanitize TEXT="..."` (via --sanitize-only) to show just the boundary step. A quick CLI check; the real
surface is the tool-app (Phase 5).
"""

from __future__ import annotations

import sys
from pathlib import Path

from app._engines.boundary import default_policy, sanitize
from app.config import settings
from app.ingest import IngestError
from app.pipeline import summarize_document, summarize_text


def _sanitize_only(text: str) -> int:
    r = sanitize(text, default_policy())
    print(f"decision : {r.decision}")
    print(f"handled  : {len(r.spans)} item(s) — classes: {', '.join(r.classes) or '(none)'}")
    if r.safe_text is None:
        print("safe_text: <none — nothing may leave this device>")
    else:
        print("safe_text (what the model would see):")
        print("  " + r.safe_text[:600].replace("\n", "\n  ") + (" …" if len(r.safe_text) > 600 else ""))
    return 0


def _print_summary(text: str = None, file: Path = None) -> int:
    try:
        res = summarize_document(file.name, file.read_bytes()) if file else summarize_text(text)
    except IngestError as e:
        print(f"[ingest error] {e}")
        return 1
    print(f"provider : {res.provider}   ·   boundary: {res.decision}   ·   kind: {res.kind}")
    print(f"trust    : 🛡 {res.handled_note}")
    if res.note:
        print(f"note     : {res.note}")
    if res.blocked:
        print(f"\nBLOCKED (kept local): {res.block_message}")
        return 0
    print(f"\nKEY POINTS ({len(res.claims)} cited):")
    for i, c in enumerate(res.claims, 1):
        print(f"  {i}. {c.text}   [{c.span_id} · support {c.support:.2f}]")
    if res.withheld:
        print(f"\nWITHHELD ({len(res.withheld)} not grounded):")
        for w in res.withheld:
            print(f"  – {w.text[:90]}  ({w.reason})")
    return 0


def main(argv: list[str]) -> int:
    args = list(argv)
    sanitize_only = "--sanitize-only" in args
    if sanitize_only:
        args.remove("--sanitize-only")
    if not args:
        print('usage: python -m app.show_summary [--sanitize-only] (<file> | "text ...")')
        print(f"       provider={settings.provider}  (set PROVIDER=anthropic in .env for a real draft)")
        return 2
    arg = args[0]
    p = Path(arg)
    if p.exists() and p.is_file():
        if sanitize_only:
            return _sanitize_only(p.read_text(encoding="utf-8", errors="replace"))
        return _print_summary(file=p)
    # treat the argument as literal text
    if sanitize_only:
        return _sanitize_only(arg)
    return _print_summary(text=arg)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
