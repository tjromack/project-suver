"""Vendored lean engine cores (Project Suver composes; it does not fork the trust machinery).

Each subpackage is a re-syncable copy of a built engine's core, carrying an origin header noting the source repo
and module. We vendor only the deterministic trust cores — the boundary (sanitize) and the summarize grounding
(split + cite-or-drop) — never a model call. See ../../CLAUDE.md principle 5 (compose, don't fork).
"""
