# DEMO — a manual verification pass (Project Suver · a multi-platform hub)

A walk of all **12 tools across 3 platforms** (Documents ×6 · Communications ×3 · Data & Analysis ×3) + the tuning
fixes. Everything below is **live-verified in code** already; this is the human eyeball pass. Report anything that
looks wrong, awkward, or off and it gets fixed + regression-tested.

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
Look for: hero **"Tools, not prompts."** · a 3-step **how it works** · three platform sections — **"🗂 The Documents
platform"** (6 cards), **"✉️ The Communications platform"** (3 cards: Meetings · Triage · Reply), and **"📊 The Data &
Analysis platform"** (3 cards: Ask · Overview · Chart) · a **"🛡 Governed by design"** trust band at the bottom.

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

---

# Platform #2 — Communications *(added 2026-08-06)*

The hub now has a second section, **🗣 The Communications platform** (3 cards). Same trust posture as Documents.

## 8. Meeting notes → actions  *(grounded action items — who · what · by when)*
Paste a short meeting note, e.g.:
`Weekly sync. Sarah will circulate the roadmap by Friday. Dana agreed to deliver the mockups by March 20. We debated dark mode — no decision. Everyone said the demo went well.`
→ a table of **actions** with **Owner** and **Due**. Expect *Sarah / Friday* and *Dana / March 20*; the "no decision"
and "demo went well" lines are **not** actions. Owner/due show **only when stated** (blank otherwise) — never guessed;
each action cites the line it came from.

## 9. Triage messages  *(sort by what each needs; ambiguous → Review)*
Paste a few messages separated by blank lines, e.g.:
```
Can you send me the Q2 numbers by end of day? Thanks, Priya

FLASH SALE — 40% off ends tonight! Unsubscribe here.

Please review and approve the vendor contract before Friday.

FYI — the office will be closed next Monday.
```
→ sorted into **Needs reply · Action needed · FYI · Can ignore** (important buckets first), each with a **WHY** drawn
from the message. Anything the tool isn't sure about shows as **Review** — never a confident wrong bucket.

## 10. Draft a reply  *(grounded reply; [placeholders], never invented specifics)*
Paste a message, e.g.: `Hi — could you join a 30-min call next week to walk through the Q2 forecast? Do you have the regional breakdown, or should I pull it? — Priya`
Pick an intent (**Answer** / **Ask for more detail** / **Politely decline**) → a grounded reply. Expect **[placeholders]**
for anything it doesn't know (a day/time, your name) listed under "things to fill in", and **no invented specifics**.
Try each intent — the reply changes. *(It never makes up a date/number on your behalf.)*

---

# Platform #3 — Data & Analysis *(added 2026-08-06)*

## 11. Ask your spreadsheet  *(the model plans, the code computes — exact numbers, cited rows)*
Paste a small table (or drop a `.csv`), e.g.:
```
Region,Rep,Product,Units,Revenue
West,Alice,Widget,120,4800
East,Bob,Widget,90,3600
West,Alice,Gadget,60,5400
East,Carol,Gadget,45,4050
West,Dan,Gizmo,200,9000
```
Ask **"What is the total revenue in the West region?"** → **19,200** with the **HOW** line (*Total of "Revenue" where
Region = "West"*) and the **exact rows** it used. Try **"How many units did Alice sell?"** (→ 180), **"average
revenue per row?"**, **"how many rows are there?"**. **Group-by / argmax:** ask **"Which product had the highest
revenue?"** → **Gadget (9,450)** with a grouped table; **"revenue by region?"** → West 19,200 · East 7,650. Then ask
something not in the table (**"What was the weather last Tuesday?"**) → an honest **abstention**. *(Numbers are
computed in code over your full data — the model only picked which calculation to run, and only ever saw a small
sample.)*

## 12. Summarize a spreadsheet  *(the model narrates, the code computes — every figure calculated)*
Paste the same sales table (or a `.csv`) → a plain-language **overview** ("this dataset tracks sales across N
records…") + a **computed column profile** (per column: type · numeric min/mean/max/total · top categories ·
missing). Check that a number in the overview (e.g. a total) matches its profile row — the narrative is written from
the computed profile, never invented, and the model only ever saw the profile + a small sample.

## 13. Chart your spreadsheet  *(bar charts, computed locally — no model at all)*
Paste the same sales table (or a `.csv`) → **bar charts**: "Total Units by Region" and "Total Revenue by Region",
each bar sized to its computed total (West should out-bar East). The chip reads **"Charted entirely on your device —
nothing sent to a model."** *(Zero-config; the sums are computed from your rows, so the chart is accurate by
construction.)* Try a table with no obvious category (all-numeric) → an honest "no obvious category to chart by."

---

# Re-verify the 08-06 tuning fixes *(DEC 020)*
- **Summarize** the Byzantine PDF again → the lead fact **"…the naval force of the Byzantine Empire, active from 330
  to 1453…"** should now appear as a **kept, cited** point (it used to be in the "withheld" panel). Withheld count
  should be ~1, not 2.
- **Extract → Amounts & totals** on the FSOC PDF → the large clearly-stated figures ($1 trillion, $29 trillion, $38
  trillion, etc.) should read **95% · ok** with **0 flagged** (they used to show a batch flagged at 50% · review).

## What to look for across everything
- Every result shows **"by: anthropic"** + the **🛡** trust chip.
- Answers/points **cite** the source (or honestly **abstain / omit / block / Review / [placeholder]** — never a
  confident guess).
- Nothing crashes on a real file; friendly messages on odd input.

**Report back** anything that reads wrong, looks off, or feels awkward — that's exactly the feedback that makes the
next lap. (Manual Demos have caught what a green suite couldn't every time.)
