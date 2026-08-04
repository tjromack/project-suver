# CLAUDE.md — Operating Contract

Guidance for any agent (or human) working in this repo. This is **Project Suver** — the *product* the 17-project
suite becomes: an AI **tool hub that removes the prompt.** This repo is Suver's home (the reusable tool-app shell,
the hub launcher, and the tools). The first tool is **Summarize** — the flagship pilot. Read `DESIGN.md` first —
it is the specification; this file is the *how we work* contract. Product North Star: `../_PLATFORM/VISION.md`.

## What this is
A **consumer-grade tool-app**: open **Summarize** → **drop a real document** (PDF/DOCX/TXT/MD or paste) → get a
**cited summary** (every claim cites a source span; unsupported claims withheld), with sensitive data **sanitized
before the LLM** and re-hydrated locally — **3 clicks, no prompt, no config.** It **composes** built engines: the
`phi-pii-data-boundary` sanitize core + the `summarize-brief-generator` cite-or-drop grounding core. It also fixes
the **tool-app contract** (`input → [sanitize] → engine → output` + one shared shell) that every future Suver tool
reuses.

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
  _engines/        vendored lean cores: boundary (policy/detect/sanitize) + summarize (spans/ground) + origin headers
  ingest.py        file/paste -> plain text (.txt/.md/.pdf/.docx), size-capped, friendly errors
  pipeline.py      the tool pipeline: ingest -> sanitize -> split -> draft(LLM) -> ground(cite-or-drop) -> re-hydrate
  provider.py      anthropic | stub (the drafting call only)
  tools/           one module per tool; `summarize.py` = the first Tool {slug,name,blurb,accepts,run}
  shell/           the reusable consumer UI shell (templates + result-panel partials)
  hub.py           the launcher (lists registered tools, opens them)
  main.py          FastAPI app: the shell + the Summarize tool + the hub
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
