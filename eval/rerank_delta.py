"""Retrieval-stress before/after — the LLM re-ranking lift, as a reproducible number (DEC 040/046).

Runs the `RERANK_STRESS` recall set twice on the REAL model — re-ranking OFF, then ON — and prints recall for each.
This is kept SEPARATE from the flagship SCORECARD (which stays at ceiling): the stress cases are deliberately hard
(the answer is buried among competing passages and phrased unlike the question), so they measure the recall the
re-ranker recovers.

Usage:
    PYTHONUTF8=1 .venv/Scripts/python.exe -m eval.rerank_delta      # needs PROVIDER=anthropic (+ a key)

⚠️ CALIBRATION (first run): if a case already answers with rerank OFF, or never answers even with rerank ON, it needs
tuning — tell Trevor's assistant which case ids did what and the docs will be adjusted (bury deeper / loosen).
"""

from __future__ import annotations

import app.pipeline as pipeline
from app.config import Settings, settings
from eval.cases import RERANK_STRESS
from eval.run import _run_case, _score


def _recall(provider: str):
    passed = 0
    rows = []
    for c in RERANK_STRESS:
        r = _score(c, *_run_case(c, provider))
        passed += 1 if r.passed else 0
        rows.append((c.id, r.passed, r.detail))
    return passed, len(RERANK_STRESS), rows


def main() -> None:
    provider = settings.provider
    if provider != "anthropic":
        print("This measurement needs the REAL model. Set PROVIDER=anthropic (with an ANTHROPIC_API_KEY) and re-run.")
        return
    original = pipeline.settings
    try:
        pipeline.settings = Settings(retrieval_rerank=False)
        off, n, off_rows = _recall(provider)
        pipeline.settings = Settings(retrieval_rerank=True)
        on, _, on_rows = _recall(provider)
    finally:
        pipeline.settings = original

    print(f"\nRetrieval-stress recall (n={n}) — the LLM re-ranking lift (real model):")
    print(f"  rerank OFF : {off}/{n}")
    print(f"  rerank ON  : {on}/{n}")
    print(f"  lift       : {'+' if on >= off else ''}{on - off}")
    print("\n  per-case (OFF → ON):")
    for (cid, poff, doff), (_, pon, don) in zip(off_rows, on_rows):
        print(f"    {cid}: {'✅' if poff else '❌'} → {'✅' if pon else '❌'}")
        if poff != pon:
            print(f"        off: {doff[:90]}")
            print(f"        on : {don[:90]}")


if __name__ == "__main__":
    main()
