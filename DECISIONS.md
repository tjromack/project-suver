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

### DEC 002 — The tool-app contract + one reusable shell (input → [sanitize] → engine → output; zero config)
**Decision.** Every Suver tool is a `Tool{slug, name, blurb, icon, accepts, action_label, run(ToolInput)→
ToolOutput, status, tags}` (`app/tools/__init__.py`); tools self-register. The **shell** (`app/shell/templates/`)
is generic over the contract: one **drop/paste zone**, one **primary action**, one **result slot**, a **trust
chip**, **zero visible config** — no prompt box, no options. `run` receives one input (an uploaded file *or*
pasted text) and returns the tool-specific `result` + the result partial that renders it; trust behavior
(sanitize-before-egress, cite-or-drop) lives in `app/pipeline.py`, which every tool calls, so each tool inherits
it. The UI is dependency-free (vanilla `fetch`, no CDN) and theme-aware; `ToolError` renders as a calm message,
never a stack trace.
**Why.** The contract is the reusable asset — it makes the *next* tool a small add and lets the hub launch
anything that fits. Keeping trust in the shared pipeline (not the shell) means no tool can ship without the rails.
**Rules out.** A prompt/config surface; per-tool trust reimplementation; a CDN/JS-framework dependency; a raw
error reaching the user.
**Status.** Accepted — Phase 1. `app/tools/__init__.py`, `app/shell/templates/{base,hub,tool}.html`, `app/main.py`.

### DEC 006 — The Summarize tool-app: the 3-click, no-prompt, no-config product surface
**Decision.** `app/tools/summarize.py` is the first `Tool`: `run` maps `ToolInput` onto the pipeline and returns a
`SummaryResult` + `_summary_result.html`. The result panel renders the **🛡 trust chip** ("N sensitive items
handled before the model" + the boundary decision + classes + drafting provider), the **cited key-points** (each
with a `› source` reveal showing the verified span, its id, and support %), a **truncation note** for long docs,
and a **withheld** panel (points not grounded — shown for transparency, never as trusted). Blocked docs show a
"kept on your device" state. **Drop a real document → cited summary, 3 clicks, zero prompt/config.**
**Why.** This is the flagship pilot — the product face of the whole suite on real data. It proves the loop:
consumer-grade surface + governed-by-construction backend.
**Rules out.** Showing a summary without its citations; hiding what was withheld or what the boundary handled;
any knob that reintroduces prompt craft.
**Status.** Accepted — Phase 5. `app/tools/summarize.py`, `app/shell/templates/_summary_result.html`,
`tests/test_app.py`. **Live-verified** (uvicorn): paste + file upload; the sample's SSN re-hydrated in the view,
never seen by the model; a real 5.5 MB PDF summarized with a truncation note.

### DEC 007 — The hub launches anything implementing the tool-app contract
**Decision.** `GET /` is the **hub**: it lists registered tools as cards — **live** ones open (`GET /t/{slug}`),
**coming-soon** ones show as roadmap cards (no `run`). The rest of the Documents platform (Copilot/"Ask this
document", Draft, Extractor) is registered as `soon` so the hub shows *where Suver is going*, not just the one
tool. Even with a single live tool, the **browse → click → use** path is real.
**Why.** The hub is the product's front door and the thing that makes "a tool hub that removes the prompt"
literal. Registering the soon tools makes the platform legible and each future tool a drop-in.
**Rules out.** A bespoke landing page per tool; a hub that can't grow without code changes to itself.
**Status.** Accepted — Phase 6. `app/main.py` (`/`, `/t/{slug}`), `app/tools/coming_soon.py`, `hub.html`.
**Live-verified**: hub lists 1 live + 3 soon; opening Summarize renders its shell.
