# TODO — Project Suver · the Summarize tool-app (phased build)

Build in phases. **Every phase ends demoable** (a `make` target or a page) and with `pytest` green against the
**stub** (no network). Commit at the end of each phase. Read `DESIGN.md` for the spec and `CLAUDE.md` for the
contract. Trust behavior always ships with a test — and **"the model only ever sees Data-Boundary-safe text"
always has a test.**

Legend: ☐ todo · ☑ done

---

## Phase 0 — Scaffold & docs  ☑ (committed locally)
- ☑ `DESIGN.md`, `CLAUDE.md`, `TODO.md`, `README.md`, `DECISIONS.md` (001).
- ☑ `Makefile` — **`setup` installs with the venv's Python explicitly** so a fresh clone just works;
  `requirements.txt` (minimums; exact-lock = hardening TODO), `.gitignore`, `.env.example`.
- ☑ `app/__init__.py`, `app/config.py`, `app/{_engines,tools,shell}` dirs, `tests/.gitkeep`, `data/samples/` + a
  synthetic sample doc (with a planted SSN — feeds the Phase-3 sanitize demo).
- ☐ **🔔 Manual (Trevor):** create the private repo `project-suver` + add an `ANTHROPIC_API_KEY` to `.env`
  (real product; the stub runs everything offline meanwhile). Wire the remote + push.

## Phase 2 — Document ingest (real files → text)  ☑ (8 tests, +2 skip until deps)  *(built ahead of Phase 1 — pure module, no shell needed)*
- ☑ `app/ingest.py` — `extract_text(filename, bytes|str) → IngestResult{text, kind, chars, note}` for
  `.txt/.md/.pdf/.docx` (pypdf/python-docx **lazy-imported**) + a `from_paste()` path; a **size cap**, extension
  detection, and **friendly `IngestError`s** (too big / unsupported / unreadable / empty → a clear message, never a
  crash).
- ☑ `make ingest FILE=…`. `tests/test_ingest.py` (8 + 2 skipped) — txt/md/paste extract; oversize · unsupported ·
  empty · non-UTF8 all fail friendly; pdf/docx bad-bytes fail friendly (run once `make setup` installs the libs).
- ☑ DECISIONS: DEC 003 — supported formats + the fail-friendly ingest guards.

## Phase 1 — The tool-app shell (the reusable consumer surface)  ☑ (built with Phase 5)
- ☑ `app/shell/templates/` — the shared consumer UI: one **drop/paste zone** (drag-drop + click), one **primary
  action**, one **result slot**, a **trust chip**, zero visible config. Theme-aware, responsive, calm, fast
  (modern `TemplateResponse(request, …)`; dependency-free vanilla `fetch`, no CDN). `app/tools/__init__.py` — the
  `Tool` contract `{slug, name, blurb, icon, accepts, action_label, run(ToolInput)->ToolOutput, status, tags}`.
- ☑ `app/main.py` renders the shell for a registered tool. `make serve`. `tests/test_app.py` (the shell renders;
  tools register; unknown tool → 404; a coming-soon tool shows a placeholder).
- ☑ DECISIONS: DEC 002.

## Phase 2 — Document ingest (real files → text)  ☐
- ☐ `app/ingest.py` — `extract_text(filename, bytes|str) -> IngestResult{text, kind, chars, note}` for
  `.txt/.md/.pdf/.docx` (pypdf, python-docx) + a **paste-text** path; a **size cap**, format detection, and
  **friendly errors** (too big / unsupported / unreadable → a clear message, never a crash).
- ☐ `make ingest FILE=…`. `tests/test_ingest.py` — each format extracts; oversize → a clear error; an unsupported
  type → a clear error; a malformed file degrades gracefully. (Small synthetic fixtures under `data/samples/`.)
- ☐ DECISIONS: DEC 003 — supported formats + the fail-friendly ingest guards.

## Phase 3 — Data-Boundary in the flow (sanitize before egress)  ☑ (5 tests; live-verified)
- ☑ `app/_engines/boundary/` — **vendored** `policy.py` + `detect.py` + `sanitize.py` from `phi-pii-data-boundary`
  (origin header on each; self-contained `DEFAULT_POLICY` replaces the file loaders). `app/pipeline.py` step:
  `sanitize(text, policy) → BoundaryResult`; `safe_text` for everything downstream; **token map local**; a
  `route_local`/`block` class → **blocked, not summarized, told to the user**. `rehydrate()` restores locally.
- ☑ `make sanitize TEXT=…` shows the safe text + the "N items handled" count. `tests/test_sanitize_flow.py` —
  ⭐ **the text handed the drafter never contains a planted value** (a spy asserts it); re-hydration is local;
  a never-egress class stops egress.
- ☑ DECISIONS: DEC 004.

## Phase 4 — Summarize engine wired in (cite-or-drop, real LLM)  ☑ (4 tests; live-verified with `anthropic`)
- ☑ `app/_engines/summarize/` — **vendored** `spans.py` + `ground.py` from `summarize-brief-generator` (origin
  header; `Candidate` inlined; explicit threshold). `app/provider.py` — `draft_candidates(safe_text, spans,
  provider)`: `anthropic` = a real key-points draft; `stub` = extractive sentence-length candidates (ground
  trivially, offline). `app/pipeline.py` completes: sanitize → split → draft → **ground** → re-hydrate; long docs
  drafted over the leading `MAX_DRAFT_CHARS` (noted).
- ☑ `make summarize TEXT=…`. `tests/test_pipeline.py` — a supported claim is **kept with a citation**; a
  fabricated claim is **withheld**; reproducible; stub needs no network. ⭐ **no claim shown without a source span.**
- ☑ DECISIONS: DEC 005.  *(Live: 7 cited points on the sample; a planted SSN re-hydrated in the view, never seen
  by the model.)*

## Phase 5 — The end-to-end Summarize tool-app (the flagship)  ☑ 🟩 THE WIN — live-verified (stub + real model)
- ☑ `app/tools/summarize.py` — the first `Tool`: `run(ToolInput) → SummaryResult{claims[(text, span_id, span_text,
  support)], withheld[], handled_count, …}`, wired through the full pipeline (ingest → sanitize → split → draft →
  ground → re-hydrate). The result panel renders the **cited key-points** (each with a `› source` reveal), the
  **withheld** panel, the **truncation note**, and the **🛡 trust chip**. **Drop a real document → cited summary,
  3 clicks, zero prompt/config.**
- ☑ `make serve` + `tests/test_app.py`. **Live-verified** (uvicorn): paste + file upload; a real 5.5 MB PDF →
  cited summary + truncation note; the planted SSN → sanitized before the model, re-hydrated in the view. (Real
  `anthropic` draft verified separately — 7 crisp cited points.)
- ☑ DECISIONS: DEC 006.

## Phase 6 — The hub launcher  ☑ (browse → click → open, live-verified)
- ☑ `app/main.py` `GET /` — the **hub**: lists registered `Tool`s (Summarize live; Copilot/Draft/Extractor as
  "coming soon" cards, `app/tools/coming_soon.py`) and **opens** a live tool at `/t/{slug}`. The
  **browse → click → use** path is real with one tool live.
- ☑ `tests/test_app.py` (the hub lists 1 live + 3 soon; opening Summarize renders its shell; unknown → 404).
- ☑ DECISIONS: DEC 007.

## Phase 7 — Records + product-readiness  ☐ 🟩 BUILT (target)
- ☐ **STATUS gets a product-readiness dimension** (engine-grade vs. **consumer-grade**); Summarize → consumer-grade.
  Update `VISION.md` (pilot shipped), `LEDGER.md`, `context/memory`, and the **Live Showcase** (Summarize is now a
  real app + the hub launcher exists). PATTERN-CATALOG: note the product layer.
- ☐ Root `README.md` (the suite) + `bootstrap.{sh,ps1}` add `project-suver`. Then the standard treatment:
  **Demo-verify** (Trevor drives a real document) → Explore (who uses Summarize-the-product) → a talking-track.
- ☐ Note the shift: this is **the first product piece** — the suite has an end-user surface, and the hub can launch
  it. The rails (shell + contract + hub) make the rest of the Documents platform (Copilot · Draft · Extractor) cheap.

---

### After the pilot
- ✅ **DONE 2026-08-05 — the Documents platform is COMPLETE.** Copilot ("Ask this document", DEC 008), Draft
  ("Draft from a document", DEC 009), and Extractor ("Extract fields", DEC 010) all shipped on this same shell —
  *read · ask · write · pull data*, 4 live tools, 63 tests. Plus: the product defaults to the real model (DEC 011)
  and long documents are handled via a 200K window + map-reduce (DEC 012). See `DECISIONS.md` + `../_PLATFORM/`.
- **Next (open):** a new platform, or the **Model/Prompt Gateway** (the "wrap any LLM" backbone that lets tool-apps
  call engines as real services instead of vendoring — the two-loop endgame in `VISION.md`).
