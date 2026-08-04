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

## Phase 1 — The tool-app shell (the reusable consumer surface)  ☐
- ☐ `app/shell/` templates — the shared consumer UI: one **drop/paste zone**, one **primary action**, one **result
  panel**, a **trust chip** slot, zero visible config. Theme-aware, responsive, calm, fast (modern
  `TemplateResponse(request, …)`). `app/tools/__init__.py` — the `Tool` registration `{slug, name, blurb, icon,
  accepts, run(input)->Result}`.
- ☐ `app/main.py` renders the shell for a registered tool (Summarize stubbed to echo for now). `make serve`.
  `tests/test_shell.py` (the shell renders; a `Tool` registers; the result panel renders a placeholder result).
- ☐ DECISIONS: DEC 002 — the tool-app contract (`input → [sanitize] → engine → output`, one shell, zero config).

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

## Phase 5 — The end-to-end Summarize tool-app (the flagship)  ☐ 🟩 the win
- ☐ `app/tools/summarize.py` — the first `Tool`: `run(input) → SummaryResult{claims[(text, span)], withheld[],
  handled_count}`, wired through the full pipeline (ingest → sanitize → split → draft → ground → re-hydrate). The
  result panel renders the **cited key-points** (each with a "› source" reveal), the **withheld** panel, and the
  **🛡 trust chip**. **Drop a real document → cited summary, 3 clicks, zero prompt/config.**
- ☐ `make serve` + `tests/test_summarize_tool.py` (the tool runs end-to-end on a sample doc; safe-text invariant
  holds; a withheld claim shows in its panel). **Live-verify** (uvicorn: drop a real PDF → cited summary; with a
  planted SSN → sanitized before the model, re-hydrated in the view). *(Real-LLM verify needs the key; stub verify
  works without.)*
- ☐ DECISIONS: DEC 006 — the Summarize tool-app; the 3-click, no-config product surface.

## Phase 6 — The hub launcher  ☐
- ☐ `app/hub.py` + `main.py` — a **launcher**: the hub lists registered `Tool`s (Summarize live; others as
  "coming soon" cards) and **opens** a tool. Even with one tool live, the **browse → click → use** path is real.
  Reuse `_LEARNING/showcase.html`'s look where it helps, but this is the *app*, not the catalog.
- ☐ `tests/test_hub.py` (the hub lists tools; opening Summarize renders its shell). Live-verify the browse→open flow.
- ☐ DECISIONS: DEC 007 — the hub launches anything implementing the tool-app contract.

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
- Complete the **Documents platform** (Copilot/Converse · Draft · Extractor as tool-apps on the same shell).
- Then the engine loop in parallel (the **Model/Prompt Gateway** service — the "wrap any LLM" backbone that lets
  tool-apps call engines as real services instead of vendoring).
