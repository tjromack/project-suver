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

### DEC 003 — Supported formats + fail-friendly ingest
**Decision.** Accept `.txt · .md · .pdf · .docx` + a paste path, with a size cap (`MAX_DOC_BYTES`, default 5 MB),
extension detection, and **friendly `IngestError`s** — a too-big / unsupported / unreadable / empty file yields a
clear, human message ("try a smaller document" / "isn't supported yet" / "is it a scan?"), never a crash. PDF/DOCX
libraries are lazy-imported so text/markdown/paste (and all the guards) work with no extra deps.
**Why.** Production posture for a consumer tool: a stranger will drop whatever they have; the app must degrade to a
sentence, not a stack trace. Lazy imports keep the core testable offline and the dependency surface honest.
**Rules out.** Crashing on a malformed/oversized file; silently truncating; requiring PDF libs to run text paths.
**Status.** Accepted — Phase 2 (`app/ingest.py`, `tests/test_ingest.py`).

### DEC 004 — Sanitize-before-egress + local re-hydration in the product flow (the buyer's "yes")
**Decision.** The pipeline's **first** step after ingest is the vendored Data-Boundary `sanitize()` (all trust
cores live under `app/_engines/`, origin-headered, re-syncable). Everything downstream — split, the model draft,
grounding — sees **only `BoundaryResult.safe_text`**; the `token_map` never leaves the process; re-hydration
restores the user's real values **only** when building the local view. If the boundary returns `route_local` /
`block` (a never-egress class, or an uncertain span under the fail-closed `default_action`), `safe_text` is
`None` and we **do not summarize** — the document stays on-device and we say so. The pilot ships a self-contained
`DEFAULT_POLICY` (`suver-documents`): the clearly-sensitive PII classes as reversible `tokenize` (so real values
re-hydrate locally), `default_action = route_local` (fail-closed), and `dob`/date detection intentionally omitted
(dates are usually salient facts a summary should keep readable, not the sensitive thing).
**Why.** This is the product's core promise and the reason a regulated buyer says yes: *the model never sees raw
sensitive data*, on real documents, by construction — not by prompt discipline. Composing the built boundary
(vs. reimplementing) keeps one source of truth for the detectors + fail-closed logic.
**Rules out.** Sending raw text to the model "just this once"; a token map crossing the process boundary;
summarizing a document the policy says must stay local; re-hydrating on any egress path.
**Status.** Accepted — Phase 3. `app/_engines/boundary/*`, `app/pipeline.py`, `tests/test_sanitize_flow.py`
(⭐ the model-only-sees-safe-text invariant, incl. a spy asserting the drafter's input carries no planted value;
the never-egress block path). **Live-verified** with the real model: a planted SSN reached the view re-hydrated,
never the model.

### DEC 005 — Cite-or-drop grounding: the model drafts candidates; deterministic grounding keeps/withholds
**Decision.** Vendor the Summarize cite-or-drop core (`spans.split_document` + `ground`) under
`app/_engines/summarize/`. The **only** model call is `provider.draft_candidates(safe_text, …)` (`anthropic` =
a real key-points draft over the sanitized text; `stub` = extractive, offline, deterministic — the densest
sentence-length spans, which ground trivially). Each candidate is then **verified** by deterministic grounding:
support = fraction of the claim's content tokens present in its best source span; **≥ threshold → kept with a
citation**, else **withheld** and surfaced. The model may select/compress/label; it never self-certifies. Long
docs: the drafter sees the leading `MAX_DRAFT_CHARS` (transparently noted); grounding still runs over every span.
**Why.** Faithfulness by construction: a fabricated claim (tokens the source never used) scores low and is
withheld regardless of provider — the trust gate is deterministic, not the model's promise. The stub keeps the
whole flow runnable with no key/network for tests and dev.
**Rules out.** Showing an ungrounded claim as trusted; trusting the model's own citation; a summary path that
can't run offline; sending unsanitized text to the drafter.
**Status.** Accepted — Phase 4. `app/_engines/summarize/*`, `app/provider.py`, `app/pipeline.py`,
`tests/test_pipeline.py` (⭐ every displayed claim carries a citation; a fabricated claim is withheld;
reproducible; stub needs no network). **Live-verified** with `anthropic`: 7 crisp cited points, supports 0.7–1.0.

<!-- Upcoming (per TODO):
DEC 002 — the tool-app contract (input → [sanitize] → engine → output; one shell; zero config) (Phase 1)
DEC 006 — the Summarize tool-app; the 3-click, no-prompt, no-config product surface (Phase 5)
DEC 007 — the hub launches anything implementing the tool-app contract (Phase 6)
-->
