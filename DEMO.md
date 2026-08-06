# DEMO — a manual verification pass (Project Suver · the Documents platform)

A 10–15 min walk of all 6 tools + the things fixed/built on faith (long-doc coverage, Compare, Converse, the hub).
Everything below is **live-verified in code** already; this is the human eyeball pass. Report anything that looks
wrong, awkward, or off and it gets fixed + regression-tested.

## 0. Start it up
From `c:\ai\project-suver` (PowerShell — one command per line, no `&&`):
```
.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
```
Open **http://127.0.0.1:8000**.

- **It now uses the REAL model by default** (your key, since `.env` has `PROVIDER=anthropic`). Every result's meta
  line should read **"…by: anthropic"** (not "stub"). *(Big docs map-reduce → a few model calls → a little slower
  and a few cents. To run free/offline instead: set `PROVIDER=stub` in `.env` and restart.)*
- Test files: `data\samples\real\Byzantine_navy.pdf` (~143K chars), `data\samples\real\FSOC2025AnnualReport.pdf`
  (~326K chars), and `data\samples\sample.txt` (has a **planted SSN** for the trust check).

## 1. The hub (the product front door) — `/`
Look for: hero **"Tools, not prompts."** · a 3-step **how it works** · **"The Documents platform"** with **6 tool
cards** each showing a lane chip (Read · Ask · Write · Pull data · Compare · Chat) · a **"🛡 Governed by design"**
trust band at the bottom.

## 2. Summarize  *(long-doc coverage + citations + the trust re-hydration)*
- Drop **`Byzantine_navy.pdf`** → a list of **cited** key points. The note should say **"Summarized across the
  full document — 143,739 characters"** (one call, whole doc — *not* "first 40,000"). Click a **"› source"** reveal
  under a point → it shows the exact passage.
- Then drop **`data\samples\sample.txt`** → the **🛡 "N sensitive items handled"** chip lights up, and the summary
  shows the **SSN 123-45-6789** (re-hydrated for you) — but it was **by: anthropic** and the model **never saw the
  real SSN**. *(That's the whole trust thesis in one screen.)*

## 3. Ask this document (Copilot)  *(grounded answer or honest abstention)*
- Drop **`Byzantine_navy.pdf`**, ask **"What happened to Carthage?"** → a synthesized, **cited** answer (e.g.
  "…fell in 698…", with source `S..`).
- Ask something not in it — **"What is the CEO's salary?"** → an honest **"not in your document."**

## 4. Draft  *(cite-or-block — never fabricates)*
- Drop a document, pick **"Summary memo"** → a titled memo with **Overview · Key Points · Next Steps**, each with a
  **"› source"** reveal.
- Try a short doc with **no action items** (e.g. paste a couple of factual sentences) → the **"Next Steps" section
  is omitted** (a note says so) rather than invented.

## 5. Extract fields  *(typed table + flag-the-uncertain + long-doc)*
- Drop **`FSOC2025AnnualReport.pdf`**, pick **"Amounts & totals"** → a typed table; narrative amounts like
  **"$1 trillion" / "$29 trillion"** should read **95% · ok** (not flagged).
- Same file, pick **"Key facts"** → a table of **~50 facts**, with the note **"Extracted across the full document —
  N sections."** *(Previously this returned nothing — that's the fix.)*

## 6. Compare two documents  *(the new two-document tool — rules detect, you decide)*
Paste these two into **Document A** and **Document B**, pick **"Key facts"**, hit **Compare**:
- **A:** `Contract term: 24 months. Monthly fee: $4,500. Payment due: 1st of the month. Termination notice: 60 days.`
- **B:** `Contract term: 36 months. Monthly fee: $4,500. Payment due: 5th of the month. Termination notice: 30 days. Late fee: $250.`

Expect a table where **term / payment / termination differ**, **monthly fee matches**, and **Late fee shows "only
in B"** — each difference with a plain note, and the line **"the tool never picks which document is right."**
*(Also try the ✕ **remove** control: add a file, click "✕ remove" — it clears without forcing another upload.)*

## 7. Chat with a document (Converse)  *(multi-turn + follow-up resolution)*
- Paste a short doc, e.g.: `Greek fire saved Constantinople from Arab sieges. The navy declined in the 11th century,
  forcing reliance on the fleets of Venice and Genoa.`
- Ask **"What was Greek fire?"** → a cited answer. The drop zone collapses; the question box stays.
- Follow up **"When did the navy decline?"** → "the 11th century…".
- **Elliptical** follow-up **"What did that force?"** → it should resolve to the navy's decline and answer
  "…reliance on Venice and Genoa" (proving *history resolves the query, retrieval answers it*).
- Ask something off-topic → an honest **"not in your document."**
- *(If you restart the server mid-chat, a follow-up will say "conversation expired — re-add the document." That's
  expected — state is in-memory.)*

## What to look for across everything
- Every result shows **"by: anthropic"** + the **🛡** trust chip.
- Answers/points **cite** the document (or honestly **abstain / omit / block** — never a confident guess).
- Nothing crashes on a real file; friendly messages on odd input.

**Report back** anything that reads wrong, looks off, or feels awkward — that's exactly the feedback that makes the
next lap. (Manual Demos have caught what a green suite couldn't every time.)
