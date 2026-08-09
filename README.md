# Project Suver

**The product the suite becomes: an AI tool hub that removes the prompt.** Click a tool, give only your input, get
the output. It wraps any LLM (we manage it) and is safe by construction — the trust control plane runs underneath
every tool. Pick one tool, or a platform of them.

> Instead of a blank chat window you have to know how to *operate*, Suver is a shelf of specific, single-purpose
> tools — *summarize this document · ask questions of these files · draft this · pull the data out of this form* —
> where you bring **only your input** and get exactly the output you came for. No prompt craft required.

This repo is Suver's home: the reusable **tool-app shell**, the **hub launcher**, and the tools. The first tool —
and this repo's flagship pilot — is **Summarize**.

> **Status — a multi-platform hub: 13 tools across 3 platforms on one shell.** **Platform #1 — Documents**
> (*read · ask · write · pull data · compare · chat · ask across*): **Summarize** (→ cited summary), **Copilot**
> ("Ask this document" → a grounded, cited answer or an honest "not in your document"), **Draft** (pick a kind → a
> grounded memo, *cite-or-block*), **Extractor** (pick a field-set → a **typed table**, the uncertain **flagged**),
> **Compare** (drop **two** documents → every difference, type-aware, grounded in both — the tool never picks a
> winner), **Converse** (add a document, then **chat** — multi-turn, grounded, follow-ups and all), and **Ask across
> your documents** (add a **set** of documents + one question → one grounded, cited answer **per document** — the
> first N-document tool; answered per document so a fact from one can never contaminate another's answer).
> **Platform #2 — Communications**: **Meeting notes → actions** (drop notes/a transcript → **action items**
> — *who · what · by when* — grounded; cite-or-drop the action, owner/due only if stated), **Triage messages**
> (paste a thread → each message sorted *Needs reply · Action · FYI · Ignore*, ambiguous ones flagged Review, never
> guessed), and **Draft a reply** (paste a message + pick an intent → a grounded reply that leaves [placeholders]
> for the unknown and never invents specifics). **Platform #3 — Data & Analysis**: **Ask your spreadsheet** (add a
> CSV + a plain question → an **exact answer computed from your rows**, showing the cells it used — the model plans,
> the code computes — totals, averages, counts, value-filters, and group-by/"which X has the most Y"; unanswerable
> → honest abstention) and **Summarize a spreadsheet** (a CSV → a plain-language overview + a computed column
> profile — the model narrates, the code computes, so every figure is calculated, not invented) and **Chart your
> spreadsheet** (a CSV → bar charts, each numeric column totalled by category — computed from your rows, fully local,
> no model). 162 tests (stub-backed,
> no network); verified end-to-end on real PDFs/transcripts/CSVs with both the offline `stub` and the real `anthropic`
> model. Sensitive data is sanitized before the model and re-hydrated only in the local view — on every tool. The
> reusable **shell + hub + tool-app contract** made each tool a small add (a *question*, two *picks*, a *second
> document*, a *conversation*, a *set of documents* — and a whole **second platform** that needed no new field).
> Long docs are handled (200K window + map-reduce). Next: the accounts/persistence bridge, or packaging go-to-market.

## The first tool: Summarize
**Drop a real document → get a cited summary.** Open Summarize, drop a PDF / DOCX / TXT / MD (or paste text), and
get key points where **every claim cites a source span of your document** and anything the source doesn't support
is **withheld** — never shown as trusted. Your **sensitive data is sanitized before the model ever sees it** (and
re-hydrated locally in what you read). **Three clicks. No prompt. No config.**

Why it's better than a raw chat window: it **won't make things up** (cite-or-drop), it **won't leak** (the
Data-Boundary sanitizes before egress), and it **doesn't need you to know how to ask** — you just drop the file.

## How it's built (compose, don't rebuild)
Suver *composes* what the suite already built and tested — it doesn't fork the trust machinery:
- **Sanitize** ← `phi-pii-data-boundary` (detect + redact/tokenize sensitive data before egress)
- **Cite-or-drop** ← `summarize-brief-generator` (split into source spans; keep only claims a span supports)

The pipeline: **ingest → sanitize → split → draft (LLM) → ground (cite-or-drop) → re-hydrate → show.** The model
only ever sees sanitized text; sanitize, split, and ground are deterministic and never call a model.

## Quickstart
```bash
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt   # installs into the venv explicitly (fresh-clone-safe)

make serve                       # the hub + the Summarize tool  (http://127.0.0.1:8000)
make ingest FILE=path/to.pdf     # a real file -> extracted text
make sanitize TEXT="..."         # the safe text + "N sensitive items handled"
make summarize TEXT="..."        # a cited summary (key points + withheld) via the client
make test                        # pytest (stub-backed, deterministic, no network)
```
Real product = real model: set `PROVIDER=anthropic` + `ANTHROPIC_API_KEY` in `.env`. Everything runs on the
deterministic `stub` offline without a key.

## The product principles
The tool removes the prompt (one input · one action · one output · zero config) · consumer-grade, not demo-grade ·
**the model only ever sees Data-Boundary-safe text** · **cite-or-drop** (every claim cites a source span or is
withheld) · compose don't fork · real model with an offline stub · production posture (real files, size caps,
friendly errors) · the tool-app contract is the reusable asset. See `CLAUDE.md`.

## Layout
```
app/_engines/  vendored lean cores (boundary sanitize · summarize cite-or-drop) — re-syncable
app/           ingest · pipeline · provider · tools/ · shell/ · hub · main
data/samples/  synthetic/public sample documents
tests/         pytest — stub-backed, deterministic
```

Spec: `DESIGN.md` · contract: `CLAUDE.md` · phased build: `TODO.md` · choices: `DECISIONS.md` · product North
Star: `../_PLATFORM/VISION.md`.

---
*Project Suver — the flagship pilot of an applied-AI product. Synthetic/public sample data in-repo; the product
runs on the user's real documents, sanitized before egress.*
