# CLAUDE.md — Operating Contract

Guidance for any agent (or human) working in this repo. This is **Project Suver** — the *product* the 17-project
suite becomes: an AI **tool hub that removes the prompt.** This repo is Suver's home (the reusable tool-app shell,
the hub launcher, and the tools). `DESIGN.md` holds the original spec (written when Summarize was the pilot); this
file is the *how we work* contract. Product North Star: `../_PLATFORM/VISION.md`.

## What this is  *(status: a multi-platform hub — 9 live tools across 2 platforms, 2026-08-06)*
A **consumer-grade tool hub** on one shell — each tool: bring only your input (one or two documents; at most a plain
**question** or a **pick**), get the output; **no prompt, no config**; sensitive data **sanitized before the model**
and re-hydrated locally. **Platform #1 — Documents** (*read · ask · write · pull data · compare · chat*):
- **Summarize** — drop a document → a **cited** summary (every claim cites a source span; unsupported ones withheld).
- **Copilot ("Ask this document")** — ask a plain question → a grounded, **cited** answer, or an honest "not in
  your document" (**abstention** over hallucination).
- **Draft ("Draft from a document")** — pick a kind (memo · explainer · action-items) → a **grounded memo**, every
  section cited or omitted; a required section that can't ground **blocks** (**cite-or-block**, never fabricates).
- **Extractor ("Extract fields")** — pick a field-set (facts · dates · people · amounts) → a **typed table**, the
  uncertain **flagged** (**confidence = min(validation, model)**), never guessed.
- **Compare ("Compare two documents")** — drop two docs, pick a field-set → every difference, **type-aware** (money
  tolerance · dates normalized · fuzzy strings), grounded in both; the tool **never picks a winner** (first two-document tool).
- **Converse ("Chat with a document")** — add a document, then **ask questions in a conversation** (follow-ups and all);
  grounded or an honest "not in your document" (the Documents platform's first **multi-turn** tool — conversation state).

**Platform #2 — Communications** (the hub is not one Documents app):
- **Meeting notes → actions** — drop meeting notes or a transcript → a list of **action items** (*who · what · by
  when*), grounded in the notes; **cite-or-drop the action** (never invented) and an **owner or due only if the notes
  state it** (never guessed).
- **Triage messages** — paste your messages or a thread → each **sorted by what it needs** (*Needs reply · Action ·
  FYI · Can ignore*) with a grounded one-line reason; anything ambiguous is shown as **Review**, never forced into a
  confident wrong bucket (**honest uncertainty**).
- **Draft a reply** — paste a received message, pick an intent (acknowledge · answer · decline · ask · follow up) →
  a grounded draft reply that uses only the message's facts, leaves clearly-labeled **[placeholders]** for anything
  it doesn't know, and **flags any invented specific** — it never makes something up on your behalf.

It **composes built engines** (vendored lean cores, not forks): `phi-pii-data-boundary` (sanitize, under every
tool) · `summarize-brief-generator` (split + cite-or-drop) · `draft-template-responder` (template + cite-or-block)
· `document-structured-extractor` (type parsers + confidence gate) · `two-source-comparator` (type-aware compare
rules + the "explain, never decide" coherence guard). It also fixes the **tool-app contract**
(`input → [sanitize] → engine → output` + one shared shell + hub) that every tool reuses — proven ×7 (a *question* → `query`; two *picks* → `choice`; a *second document* → `data2`; a *conversation* → `session`/`is_chat`; and a **second platform** that needed **no new field at all** — Meeting-actions is one document + the shared extract/ground machinery). The hub groups tools by `platform` (`by_platform()`). Long
docs are handled (200K single-call window + map-reduce). Provider `anthropic | stub`; the **product defaults to
the real model** when a key is present.

## The product principles (non-negotiable)
1. **The tool removes the prompt; the user brings only their input.** No prompt box, no "how would you like…?",
   no config. One input, one action, one output. If a knob would re-introduce prompt craft, it doesn't ship.
2. **Consumer-grade, not demo-grade.** This is the *product* face — calm, fast, polished, obvious. Demo UIs got us
   here; they don't ship as the product.
3. **The model only ever sees Data-Boundary-safe text.** Sanitize before egress, always, on real data. Reversible
   tokens re-hydrate **locally**. Never send unsanitized text out. **This always has a test.**
4. **Cite-or-drop.** Every claim in the summary cites a source span of the user's document, or it is **withheld** —
   never shown as trusted. The grounding is deterministic; the model drafts candidates, it doesn't self-certify.
5. **Compose, don't fork.** Vendor the lean engine cores (with an origin header); don't reimplement the trust
   machinery. Keep vendored modules re-syncable.
6. **Real product, real model — with an offline stub.** `anthropic | stub`. The stub runs the whole flow
   deterministically (extractive candidates that ground trivially) so tests/dev need no key/network. Only the
   *drafting* of candidate claims is a model call; sanitize + split + ground never call a model.
7. **Production posture.** Real documents, size caps, friendly errors, no crashes on a malformed file. Treat it
   like something a stranger will use.
8. **The tool-app contract is the reusable asset.** Build Summarize so the *shell*, the *result panel*, and the
   `Tool` registration generalize — the next tool is a small add, and the hub launches anything that fits.

## Stack & conventions
- Python 3.11+, FastAPI + Uvicorn, HTMX + Jinja2, `pypdf` + `python-docx` (ingest), `pytest`.
- **UI routes use the modern `templates.TemplateResponse(request, "name.html", {ctx})`** (the suite lesson —
  Starlette ≥1.3 removed the legacy form).
- **Makefile `setup` installs deps with the venv's Python explicitly** (`.venv/Scripts/python -m pip install …`
  *after* creating the venv) so a fresh clone just works — do NOT rely on the parse-time `PY:=` for the first
  install. **Pin dependencies** in `requirements.txt` (the fresh-install lessons, baked in from day one).
- `truststore.inject_into_ssl()` on any live Anthropic call. `.env` gitignored. `PYTHONUTF8=1`.
- Vendored cores live under `app/_engines/` with a header noting their source repo + module, so they can re-sync.

## Repo layout (target)
```
app/
  _engines/        vendored lean cores (origin-headered): boundary · summarize · draft · extract
  ingest.py        file/paste -> plain text (.txt/.md/.pdf/.docx), size-capped, friendly errors
  pipeline.py      the tool pipeline: ingest -> sanitize -> split -> draft(LLM) -> ground(cite-or-drop) -> re-hydrate
  provider.py      anthropic | stub (the drafting call only)
  tools/           one module per tool: summarize · copilot · draft · extractor (each a Tool{slug,name,run,…})
  shell/           the reusable consumer UI shell (templates + per-tool result partials)
  main.py          FastAPI app: the hub (/) + the shell (/t/{slug}) + run (/t/{slug}/run)
data/samples/      synthetic/public sample documents for demos + tests
tests/             pytest — stub-backed, deterministic, no network
DESIGN.md CLAUDE.md TODO.md README.md DECISIONS.md
Makefile .env.example requirements.txt .gitignore
```

## Definition of done for a change
- A `pytest` covers it against the **stub** (no network).
- If it touches trust behavior (sanitize-before-egress, cite-or-drop grounding, re-hydration, the ingest guards),
  a test covers it — and **"the model only sees sanitized text" always has a test.**
- The 3-click / no-config / no-prompt promise is preserved (a change that adds a knob needs a reason).
- `DECISIONS.md` updated on any real choice. Docs stay consistent — this reads as the first piece of the product.
