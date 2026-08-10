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

### DEC 008 — Copilot ("Ask this document"): the 2nd Documents tool, and the contract grows a `query`
**Decision.** Add **Copilot** — add a document (or paste), ask a plain-language question → a **grounded, cited
answer** from the document, or an honest **"not in your document."** It reuses the *same* vendored cores (no new
engine, no heavy RAG deps): `split_document` for passages + the grounding core's content-token `support` for
**deterministic retrieval** (rank passages by question↔passage overlap, keep the top-K above a relevance floor;
nothing relevant → abstain *before* the model sees anything). The model then answers **only** from the retrieved
(sanitized) passages or emits `NOT_IN_DOCUMENT`; the answer must still **ground** (support ≥ threshold) or we
**abstain** — never show an ungrounded answer. The tool-app **contract grew one optional `query`** field
(`ToolInput.query`, `Tool.needs_query/query_label/query_placeholder`); the shell renders one question box when a
tool needs it. *A question is the user's information need in plain words — not prompt craft — so the no-prompt
principle holds.* The **question is sanitized too** (the model never sees a sensitive value in the query either).
**Why.** It proves the reusable rails: a second tool with a *different shape* (needs a question) was a small add —
new provider fn + a pipeline path + a Tool + a result partial + one contract field — reusing all the trust
machinery. Retrieval-by-overlap keeps it lean (no embeddings/vector DB) and consistent with cite-or-drop; the
copilot's signature move (**abstention over hallucination**) is preserved on real documents.
**Rules out.** A heavy RAG stack (sentence-transformers/chromadb) for single-document Q&A; answering from outside
the document; showing an answer that doesn't ground; a free-form "prompt" box (the question is scoped to the doc).
**Status.** Accepted. `app/tools/copilot.py`, `app/pipeline.py` (`answer_question`), `app/provider.py`
(`draft_answer`), `app/shell/templates/_answer_result.html`, `tests/test_copilot.py`. **Live-verified** with
`anthropic`: a grounded answer with inline `[S2]`/`[S4]` citations; an out-of-document question abstained. The
Documents platform now has **2 live tools** (Summarize + Copilot) on one shell.

### DEC 009 — Draft ("Draft from a document"): the 3rd tool; a grounded memo, cite-or-block; the contract grows a `choice`
**Decision.** Add **Draft** — drop a document, **pick a kind** (Summary memo · Plain-language explainer · Action
items) → a **grounded memo/brief**: a titled document whose every **section** is drawn from the document and
**cited**, or is **omitted** (optional) / **blocks** the draft (required). It **never fabricates** a section the
document doesn't support (cite-or-block — Draft's signature, the 3rd shape of the one discipline after Summarize's
cite-or-drop and Copilot's abstain). Composed from the built engine: `app/_engines/draft/` vendors the
`draft-template-responder` **template + cite-or-block core**, slimmed to **kind = ordered grounded sections**;
the grounding is Suver's own — each section is grounded on the document's **salient passages** (density-ranked,
like Summarize; NOT the section's meta-question, which shares no vocabulary with an arbitrary document), and the
model writes each section from those or returns `NOT_IN_DOCUMENT`. The tool-app **contract grew one optional
`choice` field** (`ToolInput.choice`, `Tool.options`/`choice_label`); the shell renders a **`<select>`** of kinds
— *a pick, not a prompt.* Same trust posture: the model only ever sees sanitized passages (tested with a
`draft_section` spy); sections re-hydrate locally. A dedicated `draft_section` prompt keeps memo prose clean (no
preamble, no inline `[S#]` markers).
**Why.** It's the *write* leg of read · ask · write · pull-data, and a **third-shape** proof of the rails: a tool
that needs a *pick* was a small add reusing the salient-retrieval + answer path already built. Salient-passage
grounding (vs meta-question retrieval) is the one real adaptation — a memo draws from the document's core, not
from passages matching "what is this about."
**Rules out.** A prompt/instruction box (the kind is a select); writing a section the document doesn't support;
domain-specific letter templates (the engine's healthcare letters — too narrow for the consumer product); a
heavy per-section retriever.
**Status.** Accepted. `app/_engines/draft/{template,assemble}.py`, `app/pipeline.py` (`draft_text` +
`_salient_spans` + `_section_grounder`), `app/provider.py` (`draft_section`), `app/tools/draft.py`,
`_draft_result.html`, `tests/test_draft.py`. **Live-verified** with `anthropic`: clean, correctly-scoped sections
each cited; a doc with no next-steps → the "Next Steps" section **omitted** (not fabricated); a contentless doc →
**blocked**. The Documents platform now has **3 live tools**.

### DEC 010 — Extractor ("Extract fields"): the 4th/last tool; typed-list extraction, confidence = min(validation, model)
**Decision.** Add **Extractor** — drop a document, **pick a field-set** (Key facts · Dates & deadlines · People &
contacts · Amounts & totals) → the fields in a **clean, typed table**, the **uncertain ones flagged**. Because
consumer docs are arbitrary (not a known invoice/claim schema), it does **typed-list extraction**: a field-set is
a *type of thing to pull*, and the tool extracts a list of `{label, value}` items of that type. Composed from the
`document-structured-extractor` engine — vendored the **type parsers** (`parse_money`/`parse_number`/`parse_date`)
and the **confidence gate** into `app/_engines/extract/`, slimmed to a **per-item** score: **confidence =
min(validation_score, model_score)** where validation is the deterministic *type-validity* of the value and the
model signal is its uncertainty flag. A value that **fails type-validation or scores below threshold is flagged
for review — never guessed or silently trusted** (the engine's guardrail: confidence is anchored in validation,
not the model's self-report). Reuses the contract's `choice`/`options` (from Draft) — **no new plumbing.** Same
trust posture: the model only sees sanitized text (tested); values re-hydrate locally — which means the People &
contacts set naturally reads the boundary's own `[EMAIL_1]`/`[PHONE_1]` tokens and re-hydrates them.
**Why.** It's the *pull data* leg — the 4th tool completes the Documents platform (read · ask · write · pull data)
and is the **4th proof of the rails** (a tool needing a *pick*, like Draft, reusing the exact same contract field).
Typed-list extraction (vs filling a named schema) is the one adaptation that makes a schema-based engine work on
*any* document.
**Rules out.** Filling a fixed domain schema on arbitrary docs (mostly "not found"); trusting a value that doesn't
validate; guessing/fabricating a missing field; a prompt box (the field-set is a pick).
**Status.** Accepted. `app/_engines/extract/{types,confidence,fieldsets}.py`, `app/pipeline.py` (`extract_fields`),
`app/provider.py` (`extract_items` + offline stub), `app/tools/extractor.py`, `_extract_result.html`,
`tests/test_extractor.py`. **Live-verified** with `anthropic`: dates pulled from prose and **normalized to ISO**
(`"June 30, 2026" → 2026-06-30`); a no-dates doc returns **empty (honest)**; the confidence gate **flags** a
type-invalid or model-uncertain value. **The Documents platform is complete — 4 live tools.**

### DEC 011 — The product defaults to the real model; graceful fallback; narrative-money validation *(Trevor's 2026-08-05 Demo)*
**Decision.** Three fixes from the first full Demo of all 4 tools (which ran on the `stub` because `.env` pinned
`PROVIDER=stub`, making Copilot return a raw fragment and Extractor miss/flag amounts):
1. **Default to the real model.** `settings.provider` now resolves to **`anthropic` when an `ANTHROPIC_API_KEY`
   is present** (an explicit `PROVIDER` still wins). The stub is a *fallback/test* path, not the product's default
   — this is a product; we manage the LLM. `tests/conftest.py` forces `PROVIDER=stub` so the suite stays
   deterministic/offline regardless of a local `.env`.
2. **Graceful degradation.** Each provider dispatch (`draft_candidates`/`draft_answer`/`draft_section`/
   `extract_items`) wraps the `anthropic` call in `try/except` → the offline stub, so an API error degrades to a
   result instead of a 500 (production posture — no crash).
3. **Narrative-money validation.** `parse_money` now accepts **magnitude words/abbrevs** ("$29 trillion", "$1.5M")
   and finds an amount embedded in text ("over $29 trillion") — report amounts validate (ok) instead of flagging.
**Why.** The Demo's "quality problems" were mostly *the stub misrepresenting the product* — the real model answers
Copilot properly ("Carthage … fell in 698 …", cited S61 0.88) and extracts clean amounts. A consumer product must
default to real quality, never crash on a provider hiccup, and not flag legitimate values.
**Rules out.** Shipping the extractive stub as the default face; a raw 500 when the model is unavailable; flagging
every narrative amount as invalid.
**Status.** Accepted. `app/config.py`, `tests/conftest.py`, `app/provider.py` (fallbacks),
`app/_engines/extract/types.py` (`parse_money` magnitude/search). 57 tests. Live-verified with `anthropic`:
Copilot answers, FSOC amounts validate (0 flagged). *Open (BACKLOG): long-document handling — the 40 K cap only
processes the start of a long doc (Summarize + Extractor).*

### DEC 012 — Long-document handling: a 200K single-call window + map-reduce, so the WHOLE doc is covered *(Trevor's 2026-08-05 Demo)*
**Decision.** The 40K cap only processed a long doc's *start* (Trevor's Demo, Summarize + Extractor). Fix:
- **Raise the per-call window** (`max_draft_chars`) 40K → **200K** (~50K tokens — comfortable for current models),
  so most real docs (incl. the 143K Byzantine article) are summarized/extracted in **one** call. A single call
  lets the model prioritize globally, which avoids a pitfall of naïve chunking (a Wikipedia article's tail is its
  *bibliography* — forcing a window over it produced reference entries as "key points").
- **Map-reduce beyond one window:** split into ≤ `max_chunks` (6) windows, process each, then **merge** —
  Summarize dedupes kept points (by text) and keeps the top `summary_max_points` (12) by support in document
  order; Extractor dedupes items by (label, value) and caps at `extract_max_items` (60). An honest note reports
  "across the full document — N chars in M sections" (or a capped-truncation note past `max_chunks`). Copilot is
  unaffected (retrieves over the whole doc); Draft is unaffected (grounds on salient spans across the whole doc).
- **Extraction output-truncation fix** (why FSOC "Key facts" was empty): a full field-set is many rows, and the
  model's JSON **overflowed `max_tokens=1024`** → truncated mid-array → invalid JSON → 0 items. Raised extraction
  `max_tokens` to 4096, bounded the ask to "~25 most important," and made `_parse_items` **salvage** a truncated
  array (close it after the last complete object). Also **broadened the Key-facts instruction** so it synthesizes
  a label per fact for *narrative* docs (not just `label: value` structured ones).
**Why.** "Only the first 40 K" was the last real gap on big files — the exact thing a reports/contracts user hits.
**Rules out.** Silently summarizing/extracting only a doc's opening; a truncated-JSON extraction returning empty;
Key-facts working only on structured docs.
**Status.** Accepted. `app/config.py`, `app/pipeline.py` (`_span_windows`/`_text_windows`/`_long_doc_note` +
map-reduce in `summarize_text`/`extract_fields`), `app/provider.py` (extraction max_tokens + salvage + bound),
`app/_engines/extract/fieldsets.py` (Key-facts). `tests/test_longdoc.py` + salvage test → **63 tests**.
**Live-verified:** Byzantine (143 K) → 1 content-focused call; FSOC (326 K) → Summarize points span S47–S1425
(whole doc), Key facts → **51 items** (was 0), Amounts validate.

### DEC 013 — The hub is the product front door: platform framing + how-it-works + a trust band
**Decision.** Rework `GET /` from a flat card grid into a **product-grade landing** for the Documents platform:
a tighter hero (**"Tools, not prompts."**), a 3-step **how it works** (pick a tool → bring your input → get the
output — reinforcing *no prompt*), the tools presented under a **"🗂 The Documents platform"** section with a
*read · ask · write · pull data* framing and a per-tool **lane chip** (Read/Ask/Write/Pull data) instead of a now-
redundant "Live" badge, and a **"🛡 Governed by design"** trust band naming the buyer's "yes" (the model only sees
safe text · every result cites its source or says it can't · nothing fabricated · re-hydration is local). Calm,
consumer-grade, dependency-free — no over-design.
**Why.** The hub is the first thing a user, a buyer, or an enablement session sees; it should read as a coherent
*product* (a platform with a value prop + the trust story), not a list of apps. This directly serves the go-to-
market lanes (demos · pitches · enablement).
**Rules out.** A bare grid with no platform/trust framing; a redundant "Live" badge when every tool is live; any
flashy hero that fights the consumer-grade calm.
**Status.** Accepted. `app/shell/templates/hub.html`; `tests/test_app.py` (hub asserts the platform framing +
trust band + the four lanes). 63 tests; live-verified (200, clean render).

### DEC 014 — Compare ("Compare two documents"): the 5th tool; the platform's first TWO-document tool
**Decision.** Add **Compare** — drop **two documents**, pick a **field-set** (facts · dates · people · amounts) →
the same fields pulled from both, **aligned**, and compared **type-aware** (money cent-tolerance · dates
normalized · strings fuzzy · missing-on-one-side). Every difference shows a grounded, plain-English note, but the
tool **never decides which document is right** (rules detect · the model explains · a human decides). Composes the
**Extractor** (pull the field-set from each doc — reused whole) + the vendored **Reconcile** core
(`app/_engines/compare/` — the type-aware `compare()` rules + the `check_coherence` "explain, never decide" guard;
the deterministic **stub** explanation is used, so there's **no per-difference model call** — the model is used
only for the two extractions). The tool-app **contract grew its first TWO-document shape** (`data2`/`paste2` +
`needs_second`; the shell renders a second labelled drop/paste zone). *Adaptation:* Reconcile aligns by a shared
**named schema**; here the two docs are extracted independently, so items are **aligned by fuzzy label**
(SequenceMatcher ≥ 0.62), then the `{label: value}` dicts + an on-the-fly `CompareSchema` go to `compare()`
verbatim.
**Why.** "Compare two documents" (contract vs. standard · v1 vs. v2 · statement vs. invoice) is a universal,
high-value document job, and it deepens the platform with a genuinely *new input shape* — not just another card.
The comparison is deterministic and auditable; the model's only role (extraction) is the one it's good at.
**Rules out.** An LLM "diff" that could invent/suppress a difference or pick a winner; a shared-schema requirement
(consumer docs are arbitrary — align by label); a prompt box.
**Status.** Accepted. `app/_engines/compare/{schema,compare,explain}.py`, `app/pipeline.py` (`compare_two`/
`_align_labels`/`compare_inputs`), `app/tools/compare.py`, `_compare_result.html`, the two-doc shell + contract.
`tests/test_compare.py` (differences · type-aware money · only-in-one · **never-decides** guard · reproducible ·
both docs sanitized). **Live-verified** with `anthropic`: two contract versions → term/payment/termination
differences + a newly-added late fee (only in B) caught; the unchanged fee matched. **5 live Documents tools.**

### DEC 015 — Converse ("Chat with a document"): the 6th tool; the platform's first MULTI-TURN tool
**Decision.** Add **Converse** — add a document, then **ask questions in a conversation** (follow-ups and all).
Same trust posture as Copilot (each answer grounded in the document or an honest "not in your document"; the model
only ever sees sanitized passages), plus **conversation state**: the document is sanitized + split **once** and
stored ephemerally (in-memory, LRU-capped, `app/sessions.py`), and each follow-up runs against the stored safe
spans. It follows the `converse-grounded-assistant` discipline — **history resolves the query, only retrieval
answers it**: a follow-up retrieves on the new question alone, and *only if that finds nothing* (an **elliptical**
follow-up) falls back to the question + the **most recent prior question** as context; the model then answers from
the retrieved passages. So the bot can't answer from its own chat log. The tool-app **contract grew a `session`
field + an `is_chat` flag**; the shell keeps the conversation going (after the first answer it hides the drop zone,
keeps the question box, and posts the session id — not the doc — on each follow-up). First turn = document +
question; each follow-up = the next question. Reuses the Copilot retrieval + answer path (refactored into a shared
`_answer_over_spans` helper — Copilot now uses it too).
**Why.** "Chat with a document" is the natural multi-turn companion to Copilot's one-shot ask, and it's the first
tool with real **state** — a new shape that proves the shell handles a conversation, not just a request/response.
Retrieve-on-the-new-question-first (resolve only when elliptical) avoids the trap of a topic-changing follow-up
being dragged back to the prior topic.
**Rules out.** Answering from the chat log rather than the document; re-uploading/re-processing the doc each turn;
a persistent datastore (state is ephemeral — a demo/pilot posture); a semantic retriever (kept the lean
content-token retrieval — a known vocabulary-match limitation, honest abstention over a flaky fallback).
**Status.** Accepted. `app/sessions.py`, `app/pipeline.py` (`_answer_over_spans`, `converse_start`/
`converse_followup`/`_converse_answer`), `app/tools/converse.py`, `_converse_result.html`, the chat shell +
`session`/`is_chat` contract. `tests/test_converse.py` (start + session · follow-up continues · abstains · expired
· the-model-only-sees-safe-text · reproducible). **Live-verified** with `anthropic`: a multi-turn conversation
with a correctly-resolved **elliptical** follow-up ("what did that force?" → the navy decline → cited). **6 live
Documents tools.**


### DEC 016 — Demo-triage: fix the two regressions Trevor's real Demo pass surfaced
**Context.** Trevor ran the manual Demo pass across all 6 tools on the **real model** (see `DEMO.md`). All
81 tests were green and it still caught two real bugs (a manual Demo beats a green suite again). Two fixes + one
polish, all live-verified on `anthropic`.

**1 — Converse elliptical follow-up abstained (the flagship break).** "What did that force?" (after "When did the
navy decline?") returned "not in your document." **Root cause:** the model was handed *only* the bare question +
passages — it never saw the conversation, so it couldn't resolve "that" and correctly abstained. The `fallback_query`
from DEC 015 fixes *retrieval* (finds the right passage) but not the model's *comprehension* of the pronoun.
**Fix:** thread the **recent prior questions (already sanitized/safe)** into the model call as conversation context
(`draft_answer(..., context=...)` → `_history_block` in the answer prompt: "use these ONLY to resolve what the
current question refers to, then answer from the passages"). Retrieval finds the passage; context lets the model
understand the question. Copilot (one-shot) passes no context → unchanged. The invariant holds — the context is the
prior *sanitized* questions; the spy test now also asserts the context carries no sensitive value.
⚠️ **Corrects DEC 015's overclaim:** DEC 015 said the elliptical case was "live-verified"; it was not truly exercised
(the stub returns the passage regardless, masking the real-model gap). This is the actual fix.

**2 — Draft blocked a normal document.** "Summary memo" on a NASA press release (7K) blocked: "the document doesn't
support the required Overview section." **Root cause:** a required section was grounded against only the **8 densest
spans**, but a synthesis section (Overview) draws support from across the whole doc. **Fix:** the model still *reads*
the salient spans (bounded, safe context), but grounding + citations run against **all** spans — a genuinely-supported
section grounds; a truly-unsupported one still blocks (cite-or-block intact; the change strictly widens grounding to
a superset, so nothing the model didn't see can slip in). Live: the NASA release now drafts all three sections, cited.

**3 — polish.** The answer path leaked inline `[S#]` citation markers (citations show separately); Draft already
strips them. Added the same strip to the answer path (`_anthropic_answer`) — matches `[S<digits>]` only, leaves
boundary tokens like `[PERSON_NAME_1]` untouched. Also cleans the text grounding scores on.

**Status.** Accepted. `app/provider.py` (`draft_answer` context + `_history_block` + answer marker-strip),
`app/pipeline.py` (`_answer_over_spans` context; `_converse_answer` passes recent prior questions;
`_section_grounder` grounds/cites against all spans). Tests: `test_converse.py` +elliptical-resolves regression
(and the safe-text spy now covers context); copilot/converse spies accept the `context` kwarg. **81 → 82 tests**,
all live-verified on `anthropic`. Tuning items (Summarize lead-fact over-withhold; Extractor 50%-flags on
well-stated amounts) + a cost baseline logged to `../_PLATFORM/BACKLOG.md`, not fixed here.

### DEC 017 — Platform #2: Communications — "Meeting notes → actions" (the 7th tool; proves the hub)
**Decision.** Open a **second platform** — **Communications** — with its first tool, **"Meeting notes → actions"**:
drop meeting notes or a transcript → a clean list of **action items** (*who · what · by when*), grounded in the notes.
Signature discipline: **cite-or-drop the action** (an action that doesn't ground to a source span is withheld, never
invented) and an **owner or due is shown only if the notes state it** (`_stated` — a boundary name-token must appear
verbatim; any other value needs ≥60% of its words present in the sanitized doc), so who/when is never guessed. Same
trust posture as every tool: the model only ever sees Data-Boundary-safe text (names arrive as tokens); values
re-hydrate locally. Long transcripts map-reduce.
**Why.** Deepening the Documents platform was done (6 tools); the one unproven claim was that **Suver is a
multi-platform *hub*, not one Documents app**. A second *named* platform in the hub proves it. "Meetings → action" is
a universal, high-value job and the natural head of a Communications platform (message triage, reply drafting are the
next tools). ⭐ **The strongest rails proof yet — it needed NO new contract field** (one document, no query/pick/second
doc), and it **composes** the extraction + grounding machinery the Documents tools already use. The hub grew a
`platform`/`lane` concept (`by_platform()` groups tools into ordered sections) so it reads as a product with more than
one platform.
**Rules out.** An LLM that invents tasks nobody asked for (cite-or-drop); a guessed owner/deadline (`_stated` gate);
a prompt box; a whole new app (it's a small add on the existing shell + pipeline).
**Status.** Accepted. `app/provider.py` (`extract_action_items` + stub/`_parse_actions`), `app/pipeline.py`
(`ActionItem`/`ActionsOutcome`, `extract_actions`, `_stated`), `app/tools/meeting_actions.py`,
`app/shell/templates/_actions_result.html`, the hub grouped by platform (`Tool.platform`/`lane`, `by_platform()`),
`app/tools/__init__.py` registration. `tests/test_actions.py` (grounded + cited · non-action excluded · owner/due
only-if-stated · owner re-hydrated from a token · `_stated` guards a guessed value · honest empty · the-model-only-
sees-safe-text · reproducible) + `test_app.py` (2nd platform on the hub · the tool over the route). **82 → 93 tests**;
**live-verified** with `anthropic` (a product-sync transcript → 4 grounded actions with owners re-hydrated from
tokens + correct dues; "no decision was made" / "demo went well" correctly excluded). **7 live tools · 2 platforms.**

### DEC 018 — Communications tool #2: "Triage messages" (the 8th tool) — honest uncertainty over a wrong bucket
**Decision.** Add **Triage messages** — paste your messages or a thread → each message **sorted by what it needs**:
*Needs reply · Action needed · FYI · Can ignore*, with a one-line reason drawn from the message. Signature
discipline: **honest uncertainty** — a classification below the confidence threshold is shown as **Review**, never
forced into a confident wrong bucket; and the **reason must ground to the message** (its content appears there) or
it's dropped, never invented. Same trust posture: the model only ever sees Data-Boundary-safe text; snippets/reasons
re-hydrate locally. One model call per batch (numbered messages → aligned `{index, category, reason, confidence}`),
then a deterministic confidence gate.
**Why.** Deepens the Communications platform to a real multi-tool platform (*sort what came in · pull actions from
meetings*; reply drafting is the natural third). "What needs my reply?" is a universal, high-value inbox job, and
triage is a genuinely different *shape* (a per-item **classifier** with an abstain-to-Review gate) — proving the
platform isn't one-note. Composes the classify-then-gate pattern with **no new engine and no new contract field**.
**Rules out.** A confident label on an ambiguous message (→ Review); an invented reason (grounding gate); a prompt
box; per-message model calls (one batched call); re-ordering that buries the urgent (sorted needs-reply/action first).
**Status.** Accepted. `app/provider.py` (`classify_messages` + stub/`_parse_triage`), `app/pipeline.py`
(`TriageItem`/`TriageOutcome`, `triage_messages`, `_split_messages`, `_snippet`), `app/tools/triage.py`,
`app/shell/templates/_triage_result.html`, config (`triage_max_messages`/`triage_threshold`), registration.
`tests/test_triage.py` (buckets correctly · important-first · ambiguous→Review · reason grounded · honest empty ·
the-model-only-sees-safe-text · reproducible) + `test_app.py` (2nd Communications tool on the hub · the route).
**93 → 102 tests**; **live-verified** with `anthropic` (a 5-message inbox → needs-reply/action/FYI/2×ignore, all
correct; a promo whose ungrounded reason was correctly dropped). **8 live tools · Communications now has 2.**

### DEC 019 — Communications tool #3: "Draft a reply" (the 9th tool) — placeholders, not guesses
**Decision.** Add **Draft a reply** — paste a received message, **pick the reply intent** (Acknowledge · Answer ·
Decline · Ask for detail · Follow up) → a grounded draft reply. Signature discipline: the model **uses only the
message's facts** and inserts clearly-labeled **[placeholders]** for anything it doesn't know — it never invents a
date, number, name, or commitment; the pipeline **lists the placeholders** ("N things for you to fill in") and, as a
deterministic backstop, **flags any invented specific** (a money/time/ISO-date in the draft not present in the
message) for the user to verify. Same trust posture: the model only ever sees the sanitized message; the reply
re-hydrates locally (real names restored; `[placeholders]` survive because they aren't boundary tokens). Reuses the
contract's `choice`/`options` (a pick, not a prompt); no new engine.
**Why.** Completes the Communications trio — *triage what came in · pull actions from meetings · **draft what goes
out***. A reply is inherently generative (you add your own info), so the honest trust move isn't cite-or-drop — it's
**explicit placeholders + a no-invented-specifics guard**: the tool drafts, but never quietly makes something up on
your behalf. That's a demonstrable property a professional can trust.
**Rules out.** A confident reply with a fabricated date/number/name; a prompt box (intent is a pick); sending raw
text to the model; hiding what it didn't know (placeholders are surfaced, specifics are flagged).
**Status.** Accepted. `app/provider.py` (`draft_reply` + stub templates), `app/pipeline.py` (`ReplyOutcome`,
`draft_reply_text`, `_REPLY_INTENTS`/`reply_intents`, `_invented_specifics`), `app/tools/reply.py`,
`app/shell/templates/_reply_result.html`, registration. `tests/test_reply.py` (drafts + placeholders · intent
changes output · unknown-intent fallback · invented-specifics flagged · stub never invents · the-model-only-sees-
safe-text · reproducible) + `test_app.py` (intent select · the route). **102 → 112 tests**; **live-verified** with
`anthropic` (a real scheduling message → Answer/Ask-for-detail/Decline drafts, each grounded, unknowns as
placeholders, zero invented specifics). **9 live tools · Communications now has 3 (triage · reply · meeting-actions).**

### DEC 020 — Documents tuning from the 08-06 Demo: Summarize span-window grounding + Extractor over-flag fix
**Context.** Trevor's 08-06 Demo surfaced two over-cautious behaviors (both safe/transparent, but they undersold the
tools). Fixed both without weakening any trust discipline.

**1 — Summarize over-withheld true lead facts.** Byzantine lead facts (navy "active from 330 to 1453…") were withheld
at support **0.43–0.45 < 0.60** because grounding measured support against the single **best span**, but the fact's
tokens split across two adjacent sentences. **Fix:** ground each summary claim against the best **contiguous ≤2-span
window** (a summary point legitimately compresses 1–2 adjacent sentences), cited to the anchor span — so a true
multi-sentence fact grounds while a fabrication (tokens in no window) still doesn't. Scoped to Summarize (`ground()`
is used nowhere else). `app/_engines/summarize/ground.py` (`best_window`); +1 regression test. **Live-verified:**
the "330 to 1453" fact now grounds at **0.75** (kept); withheld 2 → 1 (the one remaining is genuinely borderline at
0.57, shown transparently).

**2 — Extractor flagged clearly-stated amounts at 50%.** FSOC amounts ($38T Treasury debt, $1.5B DPRK, …) sat at
50% · review because the **model** marked them `uncertain=true` (min(validation=1.0, model=0.5)=0.5), even though
they type-validate cleanly. **Fix at the source** (keeps the `min(validation, model)` gate fully intact): tightened
the extract prompt so the model sets `uncertain` **only** for genuinely ambiguous/estimated/interpreted values —
NOT for a clearly-stated figure (even a large or approximate-sounding one). `app/provider.py` (`_EXTRACT_PROMPT`).
**Live-verified:** FSOC "Amounts & totals" flagged **8 → 0** (all 52 clearly-stated amounts now read 95%); the gate
still flags a type-invalid or genuinely-uncertain value.

**Status.** Accepted. **112 → 113 tests**; both live-verified on `anthropic`. Closes the two 🟡 tuning items in
`../_PLATFORM/BACKLOG.md`.

### DEC 021 — Platform #3: Data & Analysis — "Ask your spreadsheet" (the 10th tool) — the model plans, the code computes
**Decision.** Open a **third platform — Data & Analysis** (a new, non-prose **tabular** modality) with its first
tool, **"Ask your spreadsheet"**: add a CSV (or paste a table) + a plain question → an **exact answer computed from
the rows**, showing the cells it used. Signature discipline: **the model PLANS, the code COMPUTES.** The model turns
the question into a structured plan (op = aggregate/count/filter · column · agg · filter{column,match,value}); the
pipeline **executes it deterministically** over the full local data (`_execute_plan`), so the arithmetic is always
right and every answer traces to real rows. Unanswerable/unsupported → an honest **abstention** (never a guessed
number). ⭐ Strong privacy property: the model only ever sees the **schema + a small sanitized SAMPLE** (`table_sample_
rows`), never the full dataset — the computation runs locally on all rows.
**Why.** Proves the hub scales past documents/text to a genuinely different modality (tabular), the strongest "this
is a real multi-platform hub" statement. And it fixes the #1 danger of LLMs on data — **arithmetic** — by keeping the
numbers deterministic (the model chooses *which* calculation, code does the math), mirroring Compare's "rules
compute, model explains." A universal job (everyone has spreadsheets); a lean build (stdlib `csv` + a table parser,
no pandas/openpyxl).
**Rules out.** The model doing the arithmetic (it plans only); a guessed answer when the question doesn't map
(abstain); sending the whole dataset to the model (schema + sample only); a heavy data dep.
**Status.** Accepted. `app/table.py` (CSV/TSV/paste → typed `TableData`, numeric-column detection), `.csv`/`.tsv`
added to ingest, `app/provider.py` (`plan_query` + stub/`_parse_plan`), `app/pipeline.py` (`AskTableOutcome`,
`ask_table`, `_execute_plan`, `_filter_indices`), `app/tools/spreadsheet.py`,
`app/shell/templates/_spreadsheet_result.html`, config (`table_sample_rows`/`table_max_rows_shown`), the hub's 3rd
platform section (`_PLATFORM_ORDER`). `tests/test_table.py` + `tests/test_spreadsheet.py` (sum/avg/count exact ·
value-filter aggregate exact · abstain when unanswerable · can't-sum-text abstains · **model sees only a sanitized
sample, never the full dataset** · full dataset still computed over · reproducible) + `test_app.py` (3rd platform on
the hub · the route). **113 → 130 tests**; **live-verified** with `anthropic` (a sales table → "total revenue in the
West region" = 19,200 over 3 rows; "Alice's units" = 180; out-of-table + argmax questions abstained). **10 live tools ·
3 platforms (Documents 6 · Communications 3 · Data & Analysis 1).** *(v1 supports aggregate/count/filter; group-by /
argmax "which X has the most Y" is a logged enhancement.)*

### DEC 022 — Spreadsheet: add group-by / argmax ("which X has the most Y?")
**Decision.** Extend "Ask your spreadsheet" (DEC 021) with a **groupby** operation — group rows by a text column,
aggregate a number column per group, and (optionally) return the single top/bottom group. Closes the one gap the
DEC 021 live check exposed: "which product had the highest revenue?" used to (honestly) abstain; it now computes.
Same discipline — **the model plans, the code computes**: the plan grew `group_column` · `top` · `order`, and
`_execute_plan` does the grouping + per-group aggregation + ranking deterministically (numbers exact, results shown
as a small group→value table). `agg="count"` groups by frequency ("how many per category").
**Why.** Group-by / argmax is the most common real spreadsheet question after a plain total; abstaining on it was the
biggest usability gap. Keeping the compute in code preserves the exact-numbers guarantee.
**Rules out.** The model computing the ranking; a guessed winner (it's the deterministic top of the computed groups).
**Status.** Accepted. `app/provider.py` (plan schema + `_stub_plan` groupby routing via argmax/argmin/"by"/"per"
words), `app/pipeline.py` (`_execute_plan` groupby branch → a 4-tuple with a `grouped` table; `AskTableOutcome.grouped`),
`_spreadsheet_result.html` (grouped-results label). `tests/test_spreadsheet.py` (argmax winner exact · all-groups sum ·
argmin). **130 → 132 tests**; **live-verified** with `anthropic` (Product by highest revenue → Gadget 9,450; revenue by
region → West 19,200 / East 7,650; fewest units → Carol). Closes the group-by/argmax BACKLOG item; multi-column
filters / sort-top-N / XLSX remain logged.

### DEC 023 — Data & Analysis tool #2: "Summarize a spreadsheet" (the 11th tool) — the model narrates, the code computes
**Decision.** Add **Summarize a spreadsheet** — drop a CSV (or paste a table) → a plain-language **overview** + a
**computed per-column profile** (row/col counts · type · numeric min/mean/max/total · top categories · missing
counts). The tabular analog of the flagship Summarize. Discipline: the code computes **every figure**
(`TableData.profile()`); the model only **narrates** from the computed profile (told to use only those numbers — the
profile table shown alongside is the ground truth). Same trust posture: the model sees only the **sanitized profile +
a sanitized sample**, never the full dataset; the overview re-hydrates locally. Zero-config (no question, no pick).
**Why.** Understanding a dataset ("what is this?") is the natural first step before **Ask your spreadsheet** ("what's
the total in X?"); this deepens the newest platform to 2 tools (as Communications was deepened). It keeps the
platform's discipline — *the model plans/narrates, the code computes* — so every number is right by construction.
**Rules out.** The model computing or inventing a stat (it narrates the computed profile); sending the full dataset
(profile + sample only); a prompt or pick.
**Status.** Accepted. `app/table.py` (`ColumnProfile` + `TableData.profile()`), `app/provider.py` (`narrate_table` +
stub), `app/pipeline.py` (`summarize_table`, `ProfileRow`/`DataSummaryOutcome`, `_profile_text`/`_profile_stats`),
`app/tools/data_summary.py`, `app/shell/templates/_data_summary_result.html`, registration. `tests/test_data_summary.py`
(profile computed exactly · missing counts · overview present · not-a-table · **model sees only sanitized profile +
sample** · reproducible) + `test_table.py` (profile) + `test_app.py` (2nd Data tool on the hub · the route). **132 →
139 tests**; **live-verified** with `anthropic` (a sales table → an accurate overview whose every figure matches the
computed profile — Units total 665, Revenue total 33,600, mean $5,600, largest sale grounded in the sample). **11 live
tools · 3 platforms (Data & Analysis now 2).** ⏳ Pending Trevor Demo-verify + a couple of Explore instances.

### DEC 024 — Data & Analysis tool #3: "Chart your spreadsheet" (the 12th tool) — a chart, computed locally, no model
**Decision.** Add **Chart your spreadsheet** — drop a CSV → **bar chart(s)**: for the primary categorical column, the
**total** of each numeric column by category, rendered as dependency-free **CSS bars** (no CDN, theme-aware). Signature:
**accurate by construction + fully local** — the sums are computed from the rows and the bars drawn from them, with
**no model call at all** (nothing is sent, so there is nothing to sanitize). Zero-config (no question, no pick):
auto-picks the category column (a text column with 2–20 distinct values, fewer than the row count — not an id) and
charts each numeric measure (top-12 bars, largest first, scaled to the max). Adds a genuinely new **output modality**
(a visualization) to the hub.
**Why.** Rounds out Data & Analysis to *summarize it · ask it · chart it*; a chart is the most visually-distinct,
demo-compelling output, and doing it **deterministically** makes it maximally trustworthy (accurate by construction),
instant, and free. Reuses `app/table.py`.
**Rules out.** An LLM-drawn or hallucinated chart (it's computed sums); sending the data anywhere (fully local); a
prompt or pick; a charting dependency (CSS bars, no library).
**Status.** Accepted. `app/pipeline.py` (`chart_table`, `Chart`/`ChartBar`/`ChartOutcome`, `_pick_category`),
`app/tools/chart.py`, `app/shell/templates/_chart_result.html`, config (`chart_max_bars`/`chart_max_measures`). Also
gave **Ask your spreadsheet** a distinct icon (🔎) so the 3 Data tools read clearly (Ask 🔎 · Summarize 📈 · Chart 📊).
`tests/test_chart.py` (computed by category · sorted+scaled bars · no-category honest · id-column not a category ·
not-a-table · reproducible) + `test_app.py` (3rd Data tool on the hub · the route renders bars). **139 → 146 tests**
(fully deterministic — the route-render test is the verification; no model to call). **12 live tools · 3 platforms
(Data & Analysis now 3: summarize · ask · chart).** ⏳ Pending Trevor Demo-verify + Explore.

### DEC 025 — Vertical field-set packs (legal-led): the adaptation ladder — config, not new engines
**Decision.** Add three **vertical field-set packs** to the Extractor's field-sets — **Contract terms (legal)**,
**Invoice details (finance)**, **Résumé fields (HR)** — each a `FieldSet` with a domain-specific extraction
`instruction`. Because both the **Extractor** and **Compare** render `all_fieldsets()`, these appear in *both* selects
automatically — so a legal user can **extract a contract's key terms** *and* **compare two contracts term-by-term**
with **no new code**. The legal pack pulls: parties · effective date · term · renewal · termination notice · governing
law · payment terms · fees · liability cap · indemnification · confidentiality (only what the document states — omit,
don't invent).
**Why.** Legal is the best-fit vertical for Suver — the trust disciplines map to lawyers' worst fears (a hallucinated
cite/clause is malpractice; privilege makes sanitize-before-egress essential; cite-or-drop + abstain are exactly what
they need). And this proves the **adaptation ladder**: a new vertical is **config** (a field-set), not a new engine —
the core economic story for verticals. The same mechanism serves finance (invoices) and HR (résumés).
**Rules out.** A per-vertical fork/engine; a prompt box (still a pick); inventing an absent term (the instruction
says omit). The generic sets (facts/dates/people/amounts) are unchanged.
**Status.** Accepted. `app/_engines/extract/fieldsets.py` (`CONTRACT_TERMS`/`INVOICE`/`RESUME`). `tests/test_extractor.py`
(the packs register · contract extracts into a table) + `test_app.py` (Contract terms selectable in Extractor **and**
Compare). **146 → 149 tests**; **live-verified** with `anthropic`: 8 contract terms extracted from **prose** (all
grounded, none flagged); two contract versions **compared term-by-term** → 6 differences (governing law · liability
cap · payment · term · termination · a new late fee) + 1 match, the tool never picking a winner. Still **12 tools · 3
platforms** — this is *adaptation*, not a new tool. First vertical example (legal); see `_LEARNING/VERTICAL-LEGAL.md`.

### DEC 026 — Legal Draft kind: "Contract review memo" — a vertical is config across Draft kinds too
**Decision.** Add a **Contract review memo** Draft kind — sections **Overview · Key Terms · Points to Review · Next
Steps**, each grounded in the dropped contract (**cite-or-block**, never invented; optional sections omit when
absent). Completes the legal workflow: *ask a contract · extract its terms · compare two · **draft a review memo** ·
chat.* Extends DEC 025's thesis — **a vertical is config across BOTH Extract field-sets AND Draft kinds** (it appears
in the Draft select via `all_kinds()`, no new code).
**Why.** The GTM's first move is a legal (or healthcare) pilot; a **complete, demo-ready** legal vertical is the asset
that lands it. A first-pass contract review memo (grounded, won't invent a clause) is exactly a transactional lawyer's
job — and the "Points to Review" section is the value-add (the clauses to scrutinize: liability cap, indemnity,
auto-renewal), surfaced from the contract's own wording so it grounds.
**Rules out.** An editorializing risk section that free-writes (the query steers to name clauses in the document's own
words → it grounds, or omits); a fabricated term (cite-or-block); a new engine (a kind is config).
**Status.** Accepted. `app/_engines/draft/template.py` (`CONTRACT_MEMO`). `tests/test_draft.py` (the kind drafts, every
section cited) + `test_app.py` (selectable in the Draft select). **149 → 150 tests**; **live-verified** with
`anthropic`: a prose MSA → Overview + Key Terms + Points to Review (liability cap $500K + indemnity flagged for
scrutiny), all grounded/cited; Next Steps correctly omitted (the contract states none). Still **12 tools · 3
platforms** — adaptation, not a new tool. Legal vertical now complete; `_LEARNING/VERTICAL-LEGAL.md` updated.

### DEC 027 — Second vertical example: Healthcare field-sets (the adaptation pattern generalizes)
**Decision.** Add two **healthcare** field-set packs — **Claim / EOB details** (member · provider · service date ·
claim # · service · billed / allowed / plan-paid · patient responsibility · status · denial reason) and **Clinical
summary** (diagnoses · medications *with dose* · procedures · allergies · follow-ups · care instructions). Like the
legal packs (DEC 025), they appear in **both** the Extractor and Compare (config, no new engine). The clinical
instruction is explicit: *use only what's stated — never infer a diagnosis or dose.*
**Why.** A **second vertical example** proving the adaptation ladder isn't legal-only. Healthcare is the natural next
fit — **real PHI makes sanitize-before-egress the whole game** (the control plane's core value), and it's
document-dense (EOBs, claims, discharge summaries). It also has the suite's deepest existing use-case library.
**Rules out.** Anything advisory/clinical-decision-support (these *extract what's written*, they don't diagnose or
opine); an inferred dose (the instruction forbids it; the confidence gate flags the uncertain).
**Status.** Accepted. `app/_engines/extract/fieldsets.py` (`CLAIM_EOB`/`CLINICAL`). `tests/test_extractor.py` (the
healthcare packs register). **150 tests** (unchanged — field-sets don't add a code path the stub exercises beyond the
existing keyvalue). **Live-verified** with `anthropic`: an EOB → 11 fields (billed vs. allowed, patient responsibility,
status), PHI (member name, email) tokenized for the model + re-hydrated locally; a discharge summary → 9 clinical
items (diagnoses, meds with exact doses, follow-ups), none inferred. Still **12 tools · 3 platforms** — adaptation,
not a new tool. Second vertical example; see `_LEARNING/VERTICAL-HEALTHCARE.md`.

### DEC 028 — Third vertical: Finance — "Financial statement lines" field-set (verticals now legal · healthcare · finance)
**Decision.** Add a **Financial statement lines** field-set (revenue · COGS · gross profit · opex · operating income ·
net income · assets · liabilities · equity · cash-flow · period · currency), in Extractor + Compare like the other
packs. Finance already had **Invoice details** (DEC 025); this + the **Data & Analysis platform** (Ask/Summarize/Chart
a financial spreadsheet — exact numbers, computed not guessed) make finance a full vertical.
**Why.** Completes the vertical set (legal · healthcare · finance). Finance's differentiator is different from the
others — it leans hardest on **exact-by-construction numbers** (the Data platform) + statement/invoice extraction; a
mis-stated figure is the failure mode, and *plan/narrate-then-compute* + *omit-don't-invent* address it.
**Rules out.** Computing/deriving a line the statement doesn't state (the instruction says omit, don't compute — the
Data tools compute; Extract only pulls what's written).
**Status.** Accepted. `app/_engines/extract/fieldsets.py` (`STATEMENT_LINES`). `tests/test_extractor.py` (registers).
**150 tests**; **live-verified** with `anthropic`: an income statement → 8 line items (revenue $4.2M → net income
$812K, period, currency), all grounded, none flagged. Still **12 tools · 3 platforms** — adaptation. Third vertical;
see `_LEARNING/VERTICAL-FINANCE.md`.

### DEC 029 — 8/8 demo-verify triage: chart breakdown + contract-memo short-doc block + a copy button
**Context.** Trevor ran the full 15-step demo-verify (`DEMO.md`). Most passed (incl. the DEC 020 tuning fixes — the
Byzantine lead fact now grounds at 75%, FSOC amounts all 95%/0-flagged). Three real fixes + one UX add:

**1 — Chart grouped by the *least* informative column.** `_pick_category` preferred the **fewest** distinct values →
it charted "by Region" (2 near-equal bars), which reads as uninformative. **Fix:** prefer the **richest** breakdown
(most distinct in 2–12, still < rows), so it charts by e.g. Rep/Product (varied bars). Also raised bar contrast (solid
accent on a faint neutral track). `app/pipeline.py` (`_pick_category`), `_chart_result.html`.

**2 — Contract review memo false-blocked a short contract.** The required "Overview" over-synthesized on a 3-sentence
MSA and failed to ground → "Nothing drafted" (same class as DEC 016). **Fix:** steered the Overview query to state
what the agreement is and who the parties are **using the document's own wording** (factual, not interpretive) → it
grounds on a short doc. Optional sections still omit gracefully. `app/_engines/draft/template.py`. Live-verified on
Trevor's exact short MSA (Overview + Key Terms grounded, no block).

**3 — Copy button (Trevor's ask).** Added a one-click **⧉ Copy** to the **reply** box and the **draft memo** (inline
clipboard; the memo copies its clean assembled markdown via a hidden textarea). `_reply_result.html`,
`_draft_result.html`.

**4 — DEMO.md corrections.** The Data sections used inconsistent tables (§11 was 5-row where Gadget wins; the rest
6-row where **Gizmo 15,750** wins) — unified to the 6-row table + fixed the expected values (that was the §5 "why did
it say Gadget?" confusion — my table error). Updated §13 (richer grouping) and §V-c (drafts on short contracts; a
fuller contract surfaces Points to Review).

**Status.** Accepted. Tests updated (chart now groups by the richer column; reply/draft carry a copy button) — **150
tests** green. **Backlogged (Trevor's future notes):** an app-wide **UI/branding polish** pass (unique look), and the
one still-withheld Byzantine fact (~0.40 support — safe/transparent). Still **12 tools · 3 platforms.**

### DEC 030 — Ask across your documents (13th tool; first N-document tool; map-don't-blend)
**Context.** Every tool so far works on one document (Compare on two). But every vertical is a **set** — a lawyer's
contract library, an HR policy set, a claims batch — and the natural question is asked *of the whole set*: "which of
these auto-renew?", "what's the governing law of each?". This is the corpus gap, and the highest-value next capability.

**The contract grew one field.** A `Tool.needs_many` flag + a `ToolInput.many` list ([(filename, bytes), …]); the
route accepts `files: list[UploadFile]`; the shell renders **one multi-file drop zone** (native `<input multiple>`,
with a running file-count/name list + "clear all"). Still no prompt — a *set* of inputs and a plain question. Sixth
proof the shell generalizes (a *question* → `query`; two *picks* → `choice`; a *second document* → `data2`; a
*conversation* → `session`; now a *set* → `many`). Documents grows 6 → **7**; hub tally adds "· ask across".

**The design decision that matters: map, don't blend.** The first cut pooled passages from *all* documents and asked
the model once. Live-verified on a 3-contract corpus — and it produced a **confident WRONG answer**: asked "the
monthly fee under the Acme agreement," the model answered *"there are no fees,"* stitching "no fees" from a **different
document** (an NDA) onto the Acme question — classic cross-document contamination. That violates the product's core
principle (*never a confident fabrication*). **Redesigned to answer the question strictly *within each document***
(reusing the proven, tested single-doc `_answer_over_spans`), then present each document's own cited answer. This
makes contamination **impossible by construction** (every answer grounds in exactly one document's passages) and
gives perfect attribution — "which contracts auto-renew?" becomes N clearly-labelled answers, not one lossy blend. A
document that must stay local is **skipped** (named), never searched. Deterministic summary line ("2 of 3 documents
address your question — each grounded in that document alone"); no model reduce (that's where contamination lived).

**Two follow-on fixes the re-verify surfaced (`_ANSWER_PROMPT_ACROSS`).** The same question is asked of each doc, so a
doc's passages may **not** be the one the question names. (a) An NDA answered *"the governing law of the Globex
subscription is Delaware"* — grounded in its *own* Delaware clause but **echoing the question's entity** onto a
different doc (misleading). (b) A stripped `[S#]` marker left a *"Per, the Agreement…"* fragment. A cross-doc-only
prompt variant fixes both: **state facts about *this* document only, never attribute to a company/product named in
the question; don't cite section numbers.** Re-verified: Globex → *"The governing law is the State of California,"*
NDA → *"…the State of Delaware"* — each neutral, correct, attributed by its doc pill (both cite 100%). Off-topic
questions abstain everywhere. The `across` flag threads `_answer_over_spans → draft_answer → _anthropic_answer`;
Copilot/Converse unchanged.

**Known limitation (documented, safe).** Retrieval is the shared lexical `support`, so recall is **conservative** on
synonym/compound questions ("auto-renew" ≉ "automatically renews", "fee" ≉ "shall pay") → a genuinely-present fact can
abstain ("— not addressed"). This is the **safe** direction (abstention over hallucination, the product principle);
chasing recall risks re-introducing weak-passage wrong answers. → BACKLOG (semantic retrieval, later).

**Known limitation (documented, safe).** Retrieval is the shared lexical `support`, so recall is **conservative** on
synonym/compound questions ("auto-renew" ≉ "automatically renews", "fee" ≉ "shall pay") → a genuinely-present fact can
abstain ("— not addressed"). This is the **safe** direction (abstention over hallucination, the product principle);
chasing recall risks re-introducing weak-passage wrong answers. → BACKLOG (semantic retrieval, later). *(Partly
addressed same-week — see DEC 031.)*

**Status.** Accepted. **161 tests** green (+11: per-doc answer, no-contamination, per-doc attribution, abstain,
safe-text-across-the-corpus spy, handled-count, paste-as-one-doc, reproducible, + 3 contract/route). Live-verified on
`anthropic` with a 3-contract corpus (PII planted → tokenized before the model on every doc). New tool
`app/tools/ask_across.py` + `_ask_across_result.html` (per-document rows). **13 tools · 3 platforms.**

### DEC 031 — Stemmed retrieval: recall without loosening the trust gate (from Trevor's 08-09 §7½ demo-verify)
**Context.** Trevor Demo-verified Ask-across (`DEMO.md` §7½) live. The trust proof **passed** (no cross-document
contamination — the NDA's "no fees" never leaked). But **Step C surfaced the documented recall gap at its most
visible:** asked *"What is the monthly fee?"*, the **Acme** contract — which literally says *"$12,000 per month"* —
returned "— not addressed." Root cause: retrieval ranks by exact content-token overlap, and the query token
**"monthly"** doesn't equal the passage's **"month"**, nor **"fee"** the passage's **"fees"** → the fee span never
cleared the relevance floor → abstain. (Globex only answered because it says "fee" verbatim.)

**The fix — stem retrieval only, never grounding.** Added a deliberately tiny, conservative morphological normalizer
(`_stem`: plural `-s`/`-ies` and adverb `-ly`, guarded against short words and `-ss`) + `retrieval_support`
(`content_tokens_stemmed`) in `summarize/ground.py`, and pointed `_retrieve` at it. So "monthly"→"month",
"fees"→"fee", "laws"→"law" match their variants when **ranking candidate passages**. ⭐ **The grounding math is left
exactly as-is** — the model's answer is still verified by the unchanged, exact-token `support` gate before anything
shows. Retrieval is *generous* (more candidates surface); grounding stays *strict* (still guards precision) — so
recall improves with **zero** loosening of the trust guarantee. Shared by Copilot/Converse/Ask-across (all benefit).

**Re-verified live (`anthropic`, the §7½ corpus).** *"What is the monthly fee?"* → **Acme now answers "$12,000 …";
the NDA's "no fees" stays in the NDA's own row (correct, grounded there), never on Acme — contamination still
impossible.** *"What is the governing law?"* → now **3 of 3** (Acme "State of New York" surfaces — "law" now matches
"laws"). "Initial term" unchanged. No test regressed.

**Status.** Accepted. **162 tests** (+1: stemmed-retrieval recall + a contamination guard). Also committed the §7½
demo corpus (`data/samples/ask-across-demo/`, synthetic) so the walkthrough travels with the repo. `_stem` is a
retrieval heuristic, not a linguistics engine — a semantic-retrieval upgrade remains the real ceiling-raiser (BACKLOG).
**13 tools · 3 platforms.**

### DEC 032 — Semantic-recall retrieval via model-assisted query expansion (Trevor's 08-10 pick)
**Context.** Even with DEC 031 stemming, retrieval ranks by token overlap, so a passage that STATES the answer in
different words is missed: *"What compensation is owed each month?"* shares no tokens with *"$12,000 per month"* → the
fee span never surfaces → honest abstention. The real recall ceiling-raiser is **semantic** matching. Trevor picked
this as the highest-leverage solo lap.

**The approach — and a vendor decision deliberately NOT taken.** "Semantic retrieval" has two implementations: (a)
**true dense embeddings**, which need *either* a heavy local model (torch, ~GB — breaks the lean/dependency-free
principle) *or* a **new external vendor** (Voyage/OpenAI: a new key, a new **egress destination** for user text,
per-span cost — and a second vendor complicates a product whose pitch is "safe by construction via *one* governed
model"); or (b) **model-assisted query expansion within the current stack**. Chose (b): the external-embeddings path is
a security/cost/trust-story decision for Trevor, not one to take unilaterally (flagged as a future fork). Model-assisted
expansion delivers the recall win *inside* the existing trust boundary — no new vendor, no new dependency, offline stub
preserved.

**How it works.** New `expand_query(safe_query, provider)` (`provider.py`): the model expands the **sanitized**
question into a few short alternative phrasings/terms a document might use to state the answer (e.g. "monthly fee" →
"per month", "monthly payment", "compensation"; "auto-renew" → "automatically renews", "evergreen clause"). `_retrieve`
becomes **hybrid**: a passage is ranked by its **best** `retrieval_support` over `[question] + expansions`, so a
synonym/paraphrase surfaces. Expansion runs **once per question** (a `_phrasings` helper threaded through
`_answer_over_spans`; for Ask-across it's computed once for the whole set, **not** per document). ⭐ **The grounding
gate is untouched** — expansion widens what's RETRIEVED; the exact-token `support` still VERIFIES the answer before
anything shows (the DEC 031 discipline). The model only ever sees the **safe** query and returns generic search terms
(no user data). Shared by **Copilot · Converse · Ask-across**. Config: `RETRIEVAL_EXPAND` (default on),
`RETRIEVAL_MAX_EXPANSIONS` (6). **Stub returns `[]`** → `_phrasings` degrades to the literal question → today's exact
behavior offline (so the whole suite stays deterministic).

**Live-verified (`anthropic`, the §7½ corpus).** *"What compensation is owed each month?"* (zero lexical overlap) →
**Acme now answers "$12,000 per month"** (would have abstained before). *"Does the contract renew automatically?"* →
**3 of 3** (Acme + Globex + Initech, the last correctly stating it does *not* renew) — the exact question that in the
DEC 030 live test found only 1 of 2. *"What is the governing law?"* still 3/3. **Off-topic → all abstain** (precision
held — expansion caused no false positives), and **no cross-document contamination** (each answer grounded in its own
doc).

**Status.** Accepted. **166 tests** (+4: stub-returns-no-expansion/behavior-unchanged · phrasings-widen-retrieval ·
grounding-gate-unaffected · Ask-across-expands-once-per-question-not-per-doc). Recall up on synonym/paraphrase across
all three retrieval tools, trust guarantee unchanged. **Backlogged (Trevor's decision):** true dense embeddings via an
external vendor (new key · new egress · per-span cost) — a bigger ceiling-raiser, but a vendor/security call. **13 tools
· 3 platforms.**

### DEC 033 — Trust & Quality Eval harness: measure the core claim, don't just assert it
**Context.** The product's whole differentiator is *never a confident fabrication* — but that had only been shown
**anecdotally** (demos, one-off live checks). A buyer's first question is "how do we know it won't hallucinate?", and
we had no number. With the product feature-complete + demo-verified, the highest-leverage solo lap was to **measure**
the guarantee.

**What it is.** A labeled evaluation (`eval/`): `cases.py` — 20 self-contained cases across four categories that map to
the promises (**answerable** → recall · **unanswerable** → abstention/anti-hallucination · **adversarial** →
no-fabrication + cross-document non-contamination · **sensitive** → PII-handled-before-the-model); `run.py` — runs each
case through the real pipeline (Copilot for one doc, Ask-across for a set), scores it with **deterministic substring/
flag checks** (no model scores the model), and writes a **scorecard** (`eval/SCORECARD.md`). One-doc cases use
`answer_question`; multi-doc use `ask_across` so per-document attribution is exercised. Run deliberately against the
real model (`python -m eval.run`); a **stub-mode smoke test** (`tests/test_eval_harness.py`) covers the plumbing offline
so CI needs no key.

**The number (real model, `anthropic`).** **20/20 (100%)** — Recall 6/6 · Abstention 5/5 · No-fabrication/
non-contamination 5/5 · PII-handled 4/4; **0 hallucination incidents, 0 fabrication/contamination incidents.** Notable:
`s2` — the model saw only a `[PERSON_NAME_1]` token yet the answer re-hydrated to the real name locally (the full
boundary loop, measured); `x1` — asked Acme's fee across the 3-contract set, Acme answered "$12,000" and the NDA's
"no fees" never entered Acme's row (contamination guard, measured).

**A finding the eval surfaced about itself.** The first run flagged `x4` as a "fabrication" — but the model was
**correct** ("this year's budget is $300,000, down from $500,000 last year"); the doc states both figures, so mentioning
last year's as context is grounded, not invented. My `forbid "$500,000"` check was a bad proxy — an eval is only as good
as its checks. Fixed the check to the true intent (`expect_answer="300,000"` — a wrong answer would surface 500,000 and
miss 300,000) → 20/20. Lesson banked: **calibrate the eval's checks, not just the model.**

**Why this matters.** It converts the trust story into a measurable, repeatable artifact — the single most persuasive
GTM proof ("0 fabrications on 20 adversarial cases, on the real model"), a permanent **regression guard** for every
future change, and it composes the suite's eval-Harness DNA. It is deliberately a **real-model measurement** (the stub's
behavior differs from the product), run on demand, not on every CI push.

**Status.** Accepted. **169 tests** (+3 harness smoke tests; the 20 eval cases are scored by `eval/run.py`, not
pytest). `eval/SCORECARD.md` committed as the current baseline (regenerate with `python -m eval.run`). **13 tools ·
3 platforms.**

### DEC 034 — Persistence MVP: accounts + saved work (the adoption bridge; Trevor's 08-10 pick)
**Context.** The product was feature-complete but **ephemeral** — nothing saved, no accounts. That's the gap between an
impressive demo and something an org adopts: users expect to sign in, save their work, walk away, and come back. Trevor
asked for this as a **generic MVP that transfers to a real client with minimal change** — "here's how it looks for a
(made-up) client, with a clear path to adapt for a real org."

**What shipped.** A lean, **dependency-free** persistence layer (stdlib `sqlite3`): `app/store.py` — users (email +
salted `pbkdf2_hmac` password), sessions (opaque token in an `HttpOnly`/`SameSite=Lax` cookie), and saved_items (a
tool + a document + a question). Routes in `main.py`: `/login` · `/register` · `/logout` · `/workspace` (My work) ·
`/save` · `/item/{id}/delete`, plus `?item=ID` **resume** on a tool page (pre-fills the document + question, ready to
re-run). UI: a `login.html` (sign-in / create-account tabs), a `workspace.html` (saved items with Open/Delete), a
header account nav, and a **💾 Save to my work** button in the shell (signed-in only).

**Two principles held.** (1) **Anonymous use is untouched** — no tool requires an account; sign-in only *adds*
save/history (a test asserts the full anonymous run still works + protected routes redirect/401). (2) **Transferable by
design** — email+password is the only universal, zero-dependency auth (no per-client OAuth setup); it sits behind
`store.authenticate()`/`create_user()` so **Google/Microsoft social login and org-SSO (OIDC/SAML) slot in without
touching callers**. Every user carries an `org` field — the hook for per-org branding, policy, and (later) a per-org
model choice / bring-your-own-key. `CLIENT-ADAPTATION.md` is the full "make it theirs" guide (branding · the auth
ladder · per-org isolation · production hardening: encryption-at-rest, session expiry, CSRF, rate-limiting — each a
known, bounded, non-blocking lap). Auth choice + the auth ladder recommendation are Trevor's, confirmed 08-10.

**Trust posture.** The store never calls a model; sanitize-before-egress is unchanged. Saving a document stores the
user's text locally (SQLite on the server) — documented plainly, with the production hardening options in
`CLIENT-ADAPTATION.md`. The DB (`data/suver.db`) is gitignored; tests use a throwaway DB (conftest).

**Status.** Accepted. **177 tests** (+8: password-hashing · auth roundtrip + wrong-password · dup/weak rejection ·
sessions · per-user item isolation · anonymous-still-works · register/login/logout routes · save-then-resume). MVP is
demo-grade on production hardening (documented). Related: `EMBEDDINGS-PLAN.md` (the per-org model/key direction rides on
this org record). **13 tools · 3 platforms + accounts.**

### DEC 035 — Pilot-grade hardening + a deployment path + the design-partner kit (readiness, no partner yet)
**Context.** Trevor has no design partner yet and asked what we can **flesh out now so we can move the day one
appears.** The gap between the accounts MVP (DEC 034, explicitly "demo-grade") and something a **legal** firm's due
diligence accepts is (a) a few concrete security hardenings, (b) an actual way to *stand it up*, and (c) an operational
runbook. Also republished the showcase mirror (current: 13 tools, the 20/20 scorecard, accounts) at Trevor's request.

**Hardened to pilot-grade (low-risk, additive).** (1) **Server-side session expiry** — `session_user` rejects and
deletes sessions older than `SESSION_TTL_DAYS` (30), so a stolen/forgotten cookie doesn't live forever. (2) **Auth
rate-limiting** — a tiny in-memory sliding window (`AUTH_RATE_MAX`/`AUTH_RATE_WINDOW_S`, default 8 / 5 min per client
IP) on `/login` + `/register` blunts credential-stuffing (429 when exceeded). (3) **Secure cookie behind HTTPS** —
`COOKIE_SECURE` flag (on in prod); the cookie was already `HttpOnly` + `SameSite=Lax`. +3 tests (expiry rejected+
cleared · endpoints rate-limited · cookie flags) → **180 tests**. A conftest autouse fixture clears the limiter between
tests. *(CSRF tokens, password reset, audit logging, encryption-at-rest, and a shared-store rate limiter are the
remaining pre-GA items — SameSite=Lax is the current CSRF mitigation; all listed in `CLIENT-ADAPTATION.md §5` and the
kit, non-blocking for a controlled pilot.)*

**Deployment path.** A `Dockerfile` (+ `.dockerignore`): `docker build`/`run` with an env-file for the key and a named
volume for `data/` (the SQLite DB). One worker keeps the in-memory limiter/sessions coherent for a pilot; scaling out
moves those to a shared store (documented). So a partner instance can actually be stood up — previously there was no
deploy story.

**The design-partner kit** (`_LEARNING/DESIGN-PARTNER-KIT.md`). A ready-to-execute onboarding runbook: a readiness
table (what exists vs. per-partner), stand-up steps, a 2-week pilot plan (Day-0 trust proof by running the eval on
*their* sample contracts · Week-1 enablement · Week-2 usage + feedback), success metrics, the security Q&A a legal
firm will ask, the per-partner build list (branding · SSO · isolation · GA hardening · BYO-model), and the first-meeting
assets. Beachhead = legal (GO-TO-MARKET §4a).

**Status.** Accepted. **180 tests.** Nothing here needs a partner to exist — it's runway. New: `Dockerfile`,
`.dockerignore`, `DESIGN-PARTNER-KIT.md`; hardening in `store.py`/`main.py`/`config.py`. **13 tools · 3 platforms +
accounts, pilot-grade + deployable.**

### DEC 036 — Visual identity: an "OG-Apple" black/white design system (Trevor's direction, ported live)
**Context.** The default UI read generic. Trevor wanted a **unique but minimal** look. Via a design-direction artifact
(two rounds), he chose: **quiet & editorial → refined to OG-Apple black/white minimal · near-monochrome with
primary-colour pops · serif display over clean sans · sharp flat hairline surfaces.** Then: "port it to the real app."

**The system (token-driven, so it cascades to all 13 tools from `base.html`).** Kept every token *name* stable and
changed only values, so templates re-skin without rewrites. **Palette:** Apple's own system neutrals — paper `#FFFFFF`,
ink `#1D1D1F`, grey `#6E6E73`, hairline `#D2D2D7` (dark: `#000` ground · `#1C1C1E` surface · `#F5F5F7` text), no warmth.
**Colour does a job** (the tasteful way to use primaries — it's information, not decoration, mapped to Suver's own
trust vocabulary): **blue = action** (`--accent`), **green = grounded/cited** (`--good`, `--shield`; the citation rails
are now green), **amber = flagged** (`--warn`), **red = held back** (`--bad`, new). A four-colour **signature stripe**
under the masthead is the OG-Apple nod, in those colours. **Type:** serif display (`Iowan/Palatino/Georgia`, zero-CDN)
for the wordmark + `h1–h3`; Helvetica-clean system sans for body; mono for labels. **Shape:** sharp — `--radius:0`,
`--shadow:none`, 1px hairline borders (a blanket pass squared 77 corner radii across templates; the circular spinner +
status dots were preserved). Buttons are **blue-filled, square**; the wordmark is **Suver.** with a blue period.

**Scope.** `base.html` fully reworked (tokens · fonts · header/footer · `.btn`/`.panel`/`.pill`/nav · the signature
stripe); every template's rectangle radii squared; citation passages switched blue→green in the six result partials.
Anonymous + accounts UI both re-skinned. No behavioural change — pure presentation.

**Status.** Accepted. **180 tests** still green; every page + tool run renders 200; verified serif wordmark + green
citations render. Fonts are zero-dependency system stacks (a self-hosted display face remains an option). Further
per-component polish is expected during ongoing testing (Trevor: "necessary tweaks as needed"). **13 tools · 3
platforms + accounts · new visual identity.**

**Follow-on — in-app theme toggle.** The app followed the OS theme only, with no way to switch. Added a header toggle:
the CSS moved to the three-state structure (bare `:root` = light; `@media (prefers-color-scheme: dark)` guarded as
`:root:not([data-theme="light"])` so an explicit light choice beats a dark OS; `:root[data-theme="dark"]` so the toggle
wins the other way), the choice persists in `localStorage`, and a tiny pre-paint script in `<head>` applies it before
first paint (no flash). The button shows the destination (☾ go dark / ☀ go light). Purely additive; 180 tests still green.
