# DECISIONS — Project Suver · the Summarize tool-app

Architecture & product decisions, newest last. Each entry: the choice, why, and what it rules out.

---

### DEC 001 — This repo is the product (Project Suver); the first tool is Summarize, built by composing the engines
**Decision.** Stand up `project-suver` as the home of the *product* — the reusable tool-app shell, the hub
launcher, and the tools — and build its **first tool, Summarize**, doc-set-first. The tool is a **consumer-grade,
3-click, real-document** experience (drop a file → a cited summary), built by **composing** the built engines
(vendoring the `phi-pii-data-boundary` sanitize core + the `summarize-brief-generator` cite-or-drop grounding core)
into a single-process pilot, **not** by forking or rebuilding trust machinery. The model only ever sees
Data-Boundary-safe text; every claim cites a source span or is withheld.
**Why.** The engines are done and proven; the product is the *end-user surface* + the *trust posture on real data*
+ the *reusable shell/hub*. Composing (vs. rebuilding) is fast and keeps one source of truth for the trust
mechanisms. Documents is the widest audience; Summarize is the lowest-friction, most-differentiated flagship (see
`../_PLATFORM/VISION.md`).
**Rules out.** A prompt box / config / chat surface; a new summarization or sanitization engine; unsanitized
egress; shipping a demo-grade UI as the product.
**Status.** Accepted — Phase 0. Detailed choices land as DEC 002+ per `TODO.md` (the tool-app contract, ingest,
sanitize-in-flow, cite-or-drop, the tool, the hub).

<!-- Upcoming (per TODO):
DEC 002 — the tool-app contract (input → [sanitize] → engine → output; one shell; zero config) (Phase 1)
DEC 003 — supported formats (.txt/.md/.pdf/.docx + paste) + fail-friendly ingest guards (Phase 2)
DEC 004 — sanitize-before-egress + local re-hydration in the product flow (the model only sees safe text) (Phase 3)
DEC 005 — cite-or-drop grounding: the model drafts candidates, deterministic grounding keeps/withholds (Phase 4)
DEC 006 — the Summarize tool-app; the 3-click, no-prompt, no-config product surface (Phase 5)
DEC 007 — the hub launches anything implementing the tool-app contract (Phase 6)
-->
