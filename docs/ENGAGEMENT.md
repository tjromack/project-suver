# Suver as an engagement — a worked delivery example

> A forward-deployed engagement is more than a repo: it is discovery, a translation of that discovery into
> requirements, an integration that fits the customer's constraints, evidence the thing works, a way to operate it, and
> a path from a first demo to a hardened deployment. This document walks Suver through that shape for a **realistic but
> entirely fictional customer** — *Cascade Regional Health Plan*. **No real organisation, data, systems, or people.**
> Every capability referenced is real and in this repo; the customer and the deployment around it are invented to show
> the delivery motion.

---

## 1. Discovery notes

**The customer.** Cascade is a mid-size regional health plan. The document work sits in four in-house teams: utilization
management (reads medical policies against submitted clinical notes), appeals & grievances (drafts and reviews appeal
determinations against policy), provider relations (compares provider contracts and fee schedules), and member services
(triages inbound member messages and drafts responses).

**What they said, in their words.**
- *"Our reviewers spend half their day reading policy PDFs to find the one paragraph that governs a case."*
- *"We tried a chatbot pilot. It made up a policy citation once and that ended the conversation with compliance."*
- *"Nothing with a member's name or ID can leave our boundary to a model we don't control."*
- *"Leadership wants AI, but nobody can tell me whether it's actually right — 'it seemed good in the demo' isn't an answer."*

**What the notes actually contain.** Three constraints and one non-negotiable, in priority order:
1. **A wrong answer is worse than no answer.** A fabricated policy citation is a compliance event, not a bad UX.
2. **PHI cannot reach an uncontrolled model.** Member identifiers must never leave the boundary in the clear.
3. **"Is it right?" has to be answerable with a number**, not a demo impression.
4. The workflows are **document-shaped and repetitive** — read a policy, find a clause, extract fields, compare two
   documents, draft a grounded letter, triage a message — not open-ended chat.

## 2. Requirements translation

Discovery translates to requirements the system either already meets or is configured to meet:

| From discovery | Requirement | How Suver meets it |
|---|---|---|
| A wrong citation is a compliance event | Every answer is grounded to a span of the source, or the tool declines | **cite-or-abstain** on answers; **cite-or-block** on drafts — a section that can't be grounded is withheld, not invented |
| PHI cannot reach the model | Identifiers are removed before egress, locally | **sanitize-before-egress**: SSN, credit-card, MRN, email, phone, DOB, person-name, US address are detected and tokenised *before* any model call, re-hydrated only in the user's view |
| "Is it right?" needs a number | A measured, reproducible accuracy result on the customer's own material | The **labelled Trust & Quality eval** (`eval/`) — 20/20 on the real model, 0 hallucination, 0 fabrication — re-runnable on Cascade's own sample documents |
| Document-shaped, repetitive work | One tool per job, no prompt to write | The tool hub: Ask a document · Summarize · Extract fields · Compare two documents · Draft (with a contract-memo kind) · Triage · Reply · Ask across a set |
| In-house teams, per-team needs | Per-org branding, policy, and model key without forking | The adaptation seam (`CLIENT-ADAPTATION.md`): an `org` field per user, a 2-function auth seam for SSO, and a policy/field-set config point |

The non-goal is stated with the requirements: Suver **assembles cited output for a human reviewer; it does not make the
coverage or medical-necessity determination.** Human-in-the-loop, no auto-decision.

## 3. Integration design

- **Boundary placement.** Suver runs inside Cascade's boundary as a container (`Dockerfile`, `DEPLOY.md`). The
  sanitisation step is *upstream* of the model call and is deterministic — so the model, wherever it runs, only ever
  sees tokenised text. The `org` field carries the tenant so branding, policy, and (later) a Cascade-supplied model key
  are per-tenant.
- **The tools that map to the four teams.** UM → *Ask this document* / *Summarize* over the governing policy; Appeals →
  *Draft* (contract-memo kind, cite-or-block) and *Compare two documents* (determination vs policy); Provider relations
  → *Compare* (two contracts, type-aware) and *Extract fields* (fee-schedule figures); Member services → *Triage*
  (sort inbound by what it needs) and *Reply* (a grounded draft that leaves `[placeholders]` for anything it doesn't
  know and never invents a specific).
- **Cost and abuse control.** Per-user daily quotas and free/pro tiers, plus a global daily cap, bound spend regardless
  of traffic (`LAUNCH-READINESS.md`) — the public demo runs behind exactly this.
- **What is deliberately not integrated in the pilot.** No write-back to the claims system, no auto-submission, no
  connection to a system of record. Suver produces cited output a reviewer acts on; the systems of record stay untouched.

## 4. Evaluation evidence

The trust claim is a measurement, not an assertion, and the eval is designed to run on Cascade's own material.

- **The clean set** (`eval/`, `SCORECARD.md`): a labelled set scored on the real model across recall (answerable),
  abstention (unanswerable), no-fabrication / non-contamination (adversarial), and PII-handled (sensitive) —
  **20/20, 0 hallucination incidents, 0 fabrication incidents.**
- **The hard set** (`eval/run_hard.py`, `FINDINGS-HARD.md`): deliberately messy documents — superseded facts, OCR
  noise, tables, near-duplicate documents, paraphrase gaps — that push the system until something fails (~7/9), with the
  error analysis published: where it bends, why, and what changed. The headline holds on both sets — every miss is
  over-caution, never a fabrication.
- **Day-0 trust proof.** The first thing run in the pilot is the 20/20 eval against a handful of *Cascade's own* sample
  policies and letters (synthetic or de-identified), so "is it right?" is answered on their material before any reviewer
  relies on it.

## 5. Runbook & audit log

- **Stand it up.** `docker build` + a `.env` with the tenant's model key; `DEPLOY.md` carries the steps and the
  cost-cap settings. Detection and grounding are deterministic and need no key; only the model call does.
- **Operate it.** Anonymous use needs no account; signing in adds saved work. A 👍/👎/⚑ **review queue** captures
  feedback with no document content stored — only the tool, the verdict, and a sanitised question — so the team can see
  what to improve without a privacy exposure.
- **What's auditable.** Every answer names the span it came from; every draft either cites its source or blocks the
  section. The boundary decision (what was detected and tokenised) is shown on each result. Nothing sensitive is logged
  in the clear.
- **When it declines.** An abstention is the designed behaviour, not an error: the tool shows *"not in your document"*
  with the reason, and the reviewer supplies the missing source or escalates. The live demo makes this triggerable on
  purpose (DEC 048).

## 6. Day 1 → Day 30

- **Day 1 — demo.** A reviewer drops a real (synthetic) policy into *Ask this document*, gets a cited answer, then asks
  something the policy doesn't cover and watches it decline with a reason. The compliance concern from the failed
  chatbot pilot is addressed in the first five minutes.
- **Week 1 — the trust proof.** The 20/20 eval runs against Cascade's own sample documents; the number, and the hard-set
  error analysis, go to the reviewer who has to sign off. The conversation moves from "it seemed good" to "here is the
  measured result and here is where it bends."
- **Weeks 2–3 — the two-week pilot.** The four teams use the mapped tools on real (de-identified) work. Per-org policy
  and field-sets are tuned as configuration, not code. The review-queue feedback names the misses; retrieval is improved
  without loosening the grounding gate.
- **Day 30 — hardened.** Quotas and the global cost cap are set to the tenant's budget; SSO slots into the auth seam;
  the boundary scope and the "does not determine coverage" limit are documented exactly for compliance. The pre-GA items
  (CSRF, reset, audit retention, encryption-at-rest) from `CLIENT-ADAPTATION.md §5` are the remaining checklist.

---

## What this shows

Anyone can demo a document Q&A tool. The engagement is the rest of it: hearing that a fabricated citation is a
compliance event and answering it with cite-or-abstain; hearing that PHI can't leave and answering it with a
deterministic boundary; hearing "is it right?" and answering it with a measured number on the customer's own documents —
and being able to say precisely what the system does *not* do. That translation, from a discovery note to a hardened,
measured, governed deployment, is the work.

*Companion evidence in this repo: `eval/SCORECARD.md` (the 20/20), `eval/FINDINGS-HARD.md` (the error analysis),
`DEPLOY.md` and `CLIENT-ADAPTATION.md` (the make-it-theirs guide), `LAUNCH-READINESS.md` (tiers, caps, GA checklist).*
