"""Run the HARD eval set (messy documents) and write its own scorecard.

Reuses the real pipeline + the exact scoring machinery from `eval.run` — the only difference is the case list. This is
the "grow the eval with harder, messier documents until something fails" step: some of these are EXPECTED to fail on
the first real-model run, and the failures + what changed are the error-analysis deliverable for the case study.

Usage:
    PYTHONUTF8=1 .venv/Scripts/python.exe -m eval.run_hard      # real model if a key is set (PROVIDER=anthropic)
    PROVIDER=stub .venv/Scripts/python.exe -m eval.run_hard     # offline plumbing smoke only (stub can't judge content)
"""
from __future__ import annotations

from pathlib import Path

from eval.cases_hard import HARD_CASES
from eval.run import run, scorecard_md, _bar, _CATEGORIES

if __name__ == "__main__":
    results, summary = run(cases=HARD_CASES)
    print(f"\nSuver Trust & Quality Eval — HARD set — provider: {summary['provider']}")
    print(f"  overall     : {_bar(summary['total_pass'], summary['total'])}")
    for cat in _CATEGORIES:
        p, t = summary["by_category"][cat]
        if t:
            print(f"  {cat:<12}: {_bar(p, t)}")
    print(f"  hallucination incidents: {summary['hallucination_incidents']} (target 0)")
    print(f"  fabrication  incidents : {summary['fabrication_incidents']} (target 0)")
    for r in results:
        if not r.passed:
            print(f"    FAIL {r.case.id} ({r.case.category}): {r.detail}")

    md = scorecard_md(results, summary).replace(
        "# Suver — Trust & Quality Scorecard",
        "# Suver — Trust & Quality Scorecard (HARD set)")
    md = md.replace("`python -m eval.run`", "`python -m eval.run_hard`")
    out = Path(__file__).resolve().parent / "SCORECARD-HARD.md"
    out.write_text(md, encoding="utf-8")
    print(f"\n  scorecard → {out}")
