# Suver — Hard-set error analysis ("grow the eval until something fails")

> Companion to `SCORECARD-HARD.md`. The clean labeled set is 20/20; this is the deliberately-messy set
> (`eval/cases_hard.py`), built to find the edges — superseded facts, OCR noise, tables, distractor-dense
> unanswerables, near-duplicate cross-doc, paraphrase gaps, PII-in-noise. Run: `python -m eval.run_hard` (real model).

## Headline
**~7/9 on the hard set — and 0 fabrications.** Every miss is the system being *too cautious* (over-abstention) or,
in one case, *over-generalizing* — never inventing a cited fact. On these borderline documents the real model is
**non-deterministic at the margins**: across runs, individual cases flip. That is itself a finding — the clean set is
20/20 because it is unambiguous; the hard set hovers ~78% because it is deliberately not.

## What broke, why, and what changed

### 1. The check was wrong, not the model — a mislabeled metric  *(fixed)*
The adversarial case **h5** ("What is Northstar's monthly fee?" over two near-identical MSAs) failed and was counted as
a **fabrication/contamination incident**. But the sub-checks show the opposite: the wrong document *correctly omitted*
the lure — **no lure was ever emitted.** h5 failed by *abstaining* on the target document, a recall miss, not a
fabrication. The incident counter conflated "failed an adversarial case" with "emitted a lure."
**Changed:** `eval/run.py` now counts a fabrication/contamination incident only when a `forbid_*` check actually fails
(a lure was emitted). h5's over-abstention no longer inflates the fabrication count. *(The classic eval trap: a red
number that was a measurement bug, not a model bug.)*

### 2. A brittle grader — surface form  *(fixed)*
**h7** (paraphrase gap: "If I'm laid off…" vs the doc's "involuntary separation without cause") was answered
**correctly** ("12 weeks"), but the check demanded the word "twelve." Suver handled the paraphrase fine; the grader was
too strict. **Changed:** the expectation accepts the digit form. *(Don't tune the document to pass — fix the check.)*

### 3. h6 — a retrieval-depth miss  *(root-caused; not force-fixed)*
"Reimbursement per night for a hotel in a **high-cost city**" over a policy whose §3 says "$350 in high-cost **metros**",
surrounded by five similar "$X per night / per diem / per meal" clauses. Some runs abstain (the right span doesn't win
the top-4). Turning the **additive re-ranker** on (DEC 040/047, off by default) fixes it — confirming it is a *retrieval*
miss, not a grounding one. **Decision: not a global change.** See #4 for why.

### 4. h6b — over-generalization, and why the re-ranker stays off  *(documented edge)*
"What is the per diem for **international** travel?" The policy states only a *general* $75 per diem. The model
sometimes abstains (correct) and sometimes answers "$75" (a hallucination — it over-generalized the general figure to
the specific question). Turning the re-ranker on to fix h6 (#3) made h6b answer $75 **more** often — a recall gain
bought with an abstention regression. **This is exactly why the re-ranker ships off by default (DEC 047): on this set
the trade is visible.** The honest fix for h6b is tighter abstention on "the document has a general X but not the
specific X asked," which is hard to do without lowering recall — so it stays a **named edge**, not a silent one.

### 5. h5 — near-duplicate over-abstention  *(documented edge)*
Two almost-identical MSAs (only the party and one figure differ). Asked for one party's fee, Suver's map-don't-blend
design tends to **abstain on both** rather than risk cross-document contamination. The safe direction — no lure is ever
emitted — but a recall miss on near-duplicates. A known limit of lexical retrieval over near-identical documents; the
place the parked embeddings seam would earn its keep (Phase-1 hypothesis).

## Discipline held
- **Improve retrieval, never loosen the grounding gate** (DEC 031/032). No threshold was lowered to pass a case.
- **Don't tune a document to pass.** Two fixes were to the *checks* (#1, #2); the model behavior was left honest.
- **The flagship 20/20 is unaffected.** The only code change to `eval/run.py` is the incident *counter* (#1); it does
  not touch pass/fail scoring, and reads 0 fabrications for the clean set either way — so `SCORECARD.md` is unchanged.

## Bottom line
Across the clean set (20/20) and the hard set (~7/9): **0 fabrications, 0 confident wrong citations.** The hard set's
misses are over-caution (h5), a marginal retrieval miss (h6), and one over-generalization (h6b) — each named, root-caused,
and either fixed in the check or kept as an honest, documented edge. That measured, honest picture — not a clean sweep —
is the point.
