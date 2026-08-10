"""Suver Trust & Quality Eval — measure the product's core guarantee instead of asserting it.

The whole pitch is "never a confident fabrication." This harness turns that from a claim into a **number**: it runs
a labeled set of cases through the real pipeline and scores recall, abstention-correctness, cross-document
non-contamination, no-fabrication, and PII-handled. Run it deliberately against the real model (`python -m eval.run`);
it also runs offline in stub mode as a plumbing smoke test. See `eval/cases.py` for the dataset, `eval/run.py` for
the runner + scorecard.
"""
