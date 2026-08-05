# DESIGN — Project Suver · the Documents platform

> **📌 Status (2026-08-05): this document is the original spec, written when Summarize was the single pilot.** It
> still describes the tool-app contract, the pipeline, and the trust posture accurately — those held. What's grown:
> the **Documents platform is now COMPLETE — 4 live tools** (Summarize · Copilot · Draft · Extractor =
> *read · ask · write · pull data*), each a small add on this same contract; long docs are handled (200K window +
> map-reduce); the product defaults to the real model. For per-tool decisions see `DECISIONS.md` (DEC 001–012);
> for current state see `../_PLATFORM/STATUS.md`. The design below is preserved as the pilot's spec of record.

> **Project Suver** is the *product*: an AI **tool hub that removes the prompt** — click a tool, give only your
> input, get the output; it wraps any LLM (we manage it) and is safe by construction (the control plane runs
> underneath). See `_PLATFORM/VISION.md`. This repo is Suver's home: the reusable **tool-app shell**, the **hub
> launcher**, and the tools themselves. This document specifies the **first tool — Summarize** — the flagship
> pilot: *drop a real document → get a cited summary, sensitive data sanitized before the model sees it, in three
> clicks with zero prompt knowledge.* It also fixes the **tool-app contract** every future Suver tool reuses. Code
> follows the phases in `TODO.md`.

---

## 1. What it is (and what it is NOT)

**Is:** a **consumer-grade tool-app**. The user opens **Summarize**, **drops a real document** (PDF / DOCX / TXT /
MD, or pastes text), and gets a **cited summary** — key points where **every claim cites a source span in their
document, and anything the source doesn't support is withheld** (never shown as trusted). Before the text ever
reaches the LLM, the **Data-Boundary sanitizes it** (detect + redact/tokenize sensitive data); reversible tokens
are **re-hydrated locally** in the displayed summary. The whole interaction is **three clicks, no prompt craft,
no visible config** — the app removes the prompt; the user brings only their document.

**Is NOT:** a chat window, a prompt box, or a demo UI. There is no "how would you like this summarized?" field, no
settings to tune, no way to make the model hallucinate a summary — the app is opinionated and single-purpose. It
is also **not a new summarization engine**: it *composes* two things the suite already built and tested — the
`summarize-brief-generator` **cite-or-drop grounding** core and the `phi-pii-data-boundary` **sanitize** core —
into a product surface. The novelty is the **product** (the 3-click experience + the trust posture on real data +
the reusable shell), not new trust machinery.

**One-line trust mechanism:** *the user drops a real document and gets a summary whose every claim cites a span of
their own text (unsupported claims are withheld), and their sensitive data is sanitized before the model sees it —
zero prompt, zero config, re-hydrated locally.*

## 2. The design decisions — answered (the 4 openers, settled)

### D1. ⭐ Architecture — compose the engines into a single-process pilot (vendor the lean cores)
**Decision.** For the pilot, `project-suver` runs as **one app** that **vendors the lean core modules** it needs —
from `phi-pii-data-boundary`: `policy.py` + `detect.py` + `sanitize.py`; from `summarize-brief-generator`:
`spans.py` (split a document into source spans) + `ground.py` (verify each claim against the spans, cite-or-drop).
A thin drafting step asks the LLM for candidate key-points; grounding keeps only the supported ones. **No running
sibling services required** — it just runs. *(Later, once the Model/Prompt Gateway service exists, tool-apps call
engines as real services instead of vendoring; the pilot's job is a working product fast.)* Vendored modules keep
a header noting their origin so we can re-sync if the engine changes.

### D2. ⭐ The tool-app contract (the reusable shell every Suver tool uses)
**Decision.** Every Suver tool = a pipeline **`input → [sanitize] → engine → output`** behind one shared UI shell:
**one input zone** (a drag-drop / paste target), **one action button**, **one result panel**, a small **trust
indicator** ("🛡 N sensitive items handled"), and **zero visible config.** A tool declares: its name/blurb/icon,
what input it accepts, and a `run(input) → result` function. The Summarize app is the first implementation and the
reference for the contract; the hub launches anything that implements it.

### D3. ⭐ Where sanitization sits — before the LLM, re-hydrate locally (production posture)
**Decision.** The flow is **ingest → sanitize → summarize → re-hydrate → display**: extract text → the
Data-Boundary sanitizes it (redact/tokenize sensitive spans) → the **safe text** is what's split, drafted, and
grounded → the model **only ever sees sanitized text** → reversible tokens are **re-hydrated locally** in the
final summary so the user reads normal text. The user sees a quiet **"🛡 N sensitive items handled"** note. If the
policy routes-local/blocks (a never-egress class), the app says so plainly rather than sending anything out. *This
is the buyer's reason to say yes — live from click one, on real data.*

### D4. ⭐ Formats + input at launch
**Decision.** Accept **`.txt` · `.md` · `.pdf` · `.docx`** (PDF via `pypdf`, DOCX via `python-docx`), plus a
**paste-text** path, with a **size cap** and friendly errors ("that file's too big / that format isn't supported
yet"). Text extraction is best-effort and never blocks on a malformed file — it degrades to a clear message.

## 3. The pipeline (per document)

```
user ─▶ DROP a file (or paste text)
            │
            ▼  INGEST: file → plain text (.txt/.md/.pdf/.docx; size-capped; friendly errors)
            ▼  SANITIZE (Data-Boundary, deterministic, pre-LLM): detect → redact/tokenize → SAFE text (+ local token map)
            ▼        └─ route_local/block class present → tell the user, don't send out
            ▼  SPLIT: safe text → source spans
            ▼  DRAFT (LLM, real provider): candidate key-point claims from the safe text   (stub = extractive, offline)
            ▼  GROUND (deterministic, cite-or-drop): keep claims a span supports (with the citation); WITHHOLD the rest
            ▼  RE-HYDRATE (local only): restore reversible tokens in the kept claims for display
            ▼
      RESULT: a cited summary (each point → its source span) + a "withheld" panel + "🛡 N sensitive items handled"
```

**Stack:** Python 3.11+, FastAPI + Uvicorn, HTMX + Jinja2 (a genuinely consumer-grade shell, not a demo UI),
`pypdf` + `python-docx` for ingest, `pytest`. Provider abstraction `anthropic | stub`: the **real product uses
Anthropic**; the deterministic **stub** runs the whole flow offline for tests/dev (extractive candidates that
ground trivially). `truststore` for live calls; `.env` gitignored. **Sanitize + split + ground are deterministic
and never call the model**; only the *drafting* of candidate claims is a provider call, and every candidate is
independently grounded against the source before it's shown.

## 4. The tool-app shell (Phase 1 — the reusable product surface)
- One page per tool: a large **drop/paste zone**, a single **primary action**, a **result panel** that streams in,
  a **trust chip**, and nothing else. Theme-aware, responsive, calm, fast. This is the *product* face.
- A `Tool` registration: `{slug, name, blurb, icon, accepts, run(input)->Result}`. The **hub** (Phase 6) lists
  registered tools and launches them. Summarize is the first `Tool`.
- The result panel renders a **`SummaryResult`**: the cited key-points (each with a "› source" reveal of the span),
  the withheld panel, and the trust chip. Generic enough to be the template for future tools' results.

## 5. What "done" looks like (the pilot's bar)
- A person opens Summarize, **drops a real PDF, and gets a cited summary** — every point traceable to a span of
  their document, unsupported points withheld — with sensitive data sanitized before the model saw it, re-hydrated
  locally, in **three clicks and zero prompt knowledge.**
- Runs on the **real model** (Anthropic) in production and the **stub** offline; `make test` green.
- The **tool-app contract** + a minimal **hub launcher** exist, so the next tool is a small add.
- STATUS carries a **product-readiness** mark: Summarize = **consumer-grade.**

## 6. Deliberate non-goals (this pilot)
- **No prompt box, no config, no chat.** The tool removes the prompt; adding knobs re-adds it.
- **No new summarization/trust engine.** Compose the built, tested cores; don't fork them.
- **No accounts/licensing/billing yet.** The B2B2C surface (org licenses users) is later; the pilot proves the
  tool + the trust posture.
- **No multi-service orchestration yet.** Single-process, vendored cores; real-service composition comes with the
  Gateway.
- **No unsanitized egress, ever.** The model only sees Data-Boundary-safe text — the non-negotiable, on real data.
