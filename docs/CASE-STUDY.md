<!--
Suver — case study draft for tjromack.com/work/suver.
Written to match the site's existing standard (cf. /work/mcp-suite): metadata block, then
Overview · The Problem · Constraints · Architecture · Key Decisions · How It's Verified ·
What I'd Do Differently · Limits · Closing. Mixed first/third person, past tense, terse.
Every number here is reproducible from the repo — see eval/SCORECARD.md and eval/FINDINGS-HARD.md.
-->

# Suver — a governed AI tool hub that removes the prompt

**Shipped:** Aug 2026 · hardened Sep 2026
**Demonstrates:** Grounded generation with cite-or-abstain — verified on a labelled trust set, and on a harder set whose misses are published
**Lenses:** Applied AI (primary), Product & delivery
**Stack:** python · fastapi · jinja · htmx · sqlite · anthropic-api · docker

> Sixteen tools on one shell that removes the prompt: bring a document, a spreadsheet or a message, and get a cited
> answer — or an honest "not in your document." Sensitive data is tokenised before any model sees it. Measured 20/20 on
> a labelled trust set: zero hallucinations, zero fabrications.

## Overview

Suver is a consumer-grade hub of sixteen AI tools across four platforms — Documents, Communications, Data & Analysis,
and Learning — sharing one no-prompt shell. Each tool does one job: you bring only your input, and the tool returns the
output. There is no chat box, no system prompt, nothing to configure. What every tool shares is a trust contract:
every claim it makes is grounded to a span of *your* source and cited, or it is withheld — and any PII/PHI is detected
and tokenised locally, before a single character reaches a model.

I did not build sixteen applications. I built one reusable tool-app shell over five vendored engine cores (a
sanitisation boundary, a summariser, a template drafter, a typed extractor, a two-source comparator) and proved the same
contract holds as the shell scaled from one tool to sixteen and from one platform to four. A new vertical — legal,
finance, HR — is a configuration (a field-set, a draft kind, a policy), not a new engine and not a fork.

## The Problem

Most AI tools hand a user a blank box and hope they know how to prompt it — and hope the model does not invent an answer.
For anyone working with documents that matter, both halves of that are the problem. A summary that quietly includes a
clause the contract never contained is worse than no summary. An answer that cites the wrong section is worse than an
honest "I don't know." And a tool that ships a customer's medical record or SSN to a third-party model to do its job is
a non-starter before the quality question is even asked.

The work, then, is not access to a model. It is making the model's output *checkable* — grounded to the source, honest
when the source is silent, and safe on data that can never leave the building.

## Constraints

- **Synthetic and public data only.** Every document in the repository is invented or public. No real client data,
  ever — the design has to be demonstrable without touching any.
- **The model may only ever see sanitised text.** PII/PHI is tokenised *before* egress and re-hydrated only in the
  user's view; the boundary is not a feature the model can choose to skip.
- **Grounding is enforced in code, not asked of the model.** "Cite your sources" in a prompt is a request; the guarantee
  had to be a deterministic gate the model cannot talk its way past.
- **New verticals are configuration, not forks.** The shell had to generalise, or every domain would become a rewrite.
- **It has to run without a key.** The whole suite and its test set run offline on a deterministic stub, so CI is free
  and a reviewer can clone and run it in one command; the real model is a config flip.

## Architecture

Every tool runs the same pipeline: **ingest → sanitise → retrieve/split → draft (LLM) → ground (cite-or-abstain) →
re-hydrate → show.** The three steps that carry the trust guarantee — sanitisation, splitting, and grounding — are
deterministic and never call a model. The model only ever sees text the boundary has already tokenised.

Sanitisation runs eight detectors (SSN, credit-card-like numbers, MRN, email, phone, dates/DOB, person names, US
addresses), recall-first: it over-redacts rather than under-redacts, because for a trust boundary a false positive is
cheap and a miss is not. Retrieval is lexical — stemmed token overlap — widened by model-assisted query expansion (the
model paraphrases the sanitised question so differently-worded facts still match), with an optional additive re-ranker
that can only reorder, never drop, a lexical hit. The grounding gate then keeps only claims whose content tokens are
actually present in their best retrieved span; anything below the support threshold is dropped or the tool abstains.

For a set of documents, the rule is *map, don't blend*: the question is answered strictly within each document and
attributed per document, so a fact from one can never contaminate another's answer. The discipline across the whole
system is one line: **improve retrieval, never loosen the grounding gate.**

## Key Decisions

1. **Abstain over answer.** Every tool would rather return nothing than return an ungrounded claim — cite-or-abstain on
   answers, cite-or-block on drafts (a section that cannot be grounded is withheld, never faked). The benefit is a
   product that never fabricates confidently; the tradeoff is over-caution on messy inputs, where recall drops rather
   than risk being wrong.
2. **Sanitise before egress, in code.** The boundary tokenises PII locally before any model call, because a policy the
   model enforces is a policy the model can violate. The tradeoff is a recall-first heuristic that sometimes over-redacts
   — a long order number can be tokenised as a card — which I accepted deliberately.
3. **Compose engine cores; don't fork.** The tools vendor five lean engine cores behind one shell, so a fifth platform
   (Learning) needed no new contract field at all. The tradeoff is that the vendored cores have to be kept in sync with
   their sources.
4. **Make grounding a deterministic gate, not a model self-report.** Support is measured by token presence in the cited
   span, so the guarantee is code, not a prompt. The tradeoff is that exact-token grounding can reject a correct
   paraphrase and abstain — which is the safe direction, but a real recall cost.
5. **Ship the re-ranker off by default.** On clean documents, query expansion already reaches the fact, so the extra
   model call earned nothing and risked a regression. The tradeoff is a documented retrieval-depth miss on harder
   documents, where the re-ranker *would* help — a trade I chose to name rather than pay everywhere.

## How It's Verified

A labelled evaluation scores the product on the real model across four categories — answerable (recall), unanswerable
(abstention), adversarial (no fabrication, no cross-document contamination), and sensitive (PII handled end to end).
Every check is a deterministic assertion over the pipeline's own output; no model call scores the model.

| Check | Result |
|---|---|
| Overall, labelled trust set (`python -m eval.run`, real model) | **20 / 20** |
| Recall — answerable cases surfaced the fact | 6 / 6 |
| Abstention — unanswerable cases refused | 5 / 5 |
| No-fabrication / non-contamination — adversarial cases | 5 / 5 |
| PII handled — sensitive items tokenised before the model | 4 / 4 |
| Hallucination incidents · fabrication incidents | **0 · 0** |
| Hard set — deliberately messy documents (`python -m eval.run_hard`) | ~7 / 9, misses published |
| Automated suite (offline stub, gates every tool + failure modes) | 225 tests |

The hard set is the honest half. I grew the eval with the documents that break grounded retrieval in the field —
superseded facts, OCR noise, tables, distractor-dense unanswerables, near-duplicate documents, paraphrase gaps — and
published the error analysis (`eval/FINDINGS-HARD.md`). The result that matters: across both sets, every miss is
over-caution or over-generalisation — **zero fabrications, zero confident wrong citations.**

## What I'd Do Differently

- **Two of the hard set's "failures" were my checks, not the model.** One counted an *abstention* as a fabrication (the
  metric flagged any failed adversarial case, not one that actually emitted a lure); another demanded the word "twelve"
  when the model correctly answered "12." Both were the classic eval trap — a red number that was a measurement bug — and
  I would build the graders to assert the actual behaviour, not its surface form, from the start.
- **Retrieval over near-duplicate documents over-abstains.** Two near-identical contracts confuse lexical retrieval
  enough that the system withholds rather than risk contamination — the safe direction, but a real recall miss. Lexical
  plus expansion is not enough there; a dense-embedding retrieval seam is the honest fix, deferred on cost and
  new-vendor grounds and named as a limit rather than hidden.

## Limits

- Suver assembles cited, grounded output; it is **not** a legal, clinical, or financial adviser and makes no
  determination. A human reads and decides.
- The repository contains synthetic and public data only. The 20/20 is a measurement on a labelled set, not a
  certification; reproduce it on your own documents before trusting it on them.
- The sanitisation boundary is recall-first and heuristic — names outside its gazetteer, non-US addresses, and
  identifier types it does not model (passport, driver's licence, bank/routing, IP) can pass. It over-redacts by design;
  it is not NER-complete.

## Closing

The repository is linked at the top of this page, and it runs in one command — offline, on a deterministic stub, no key
required. Inside it, `eval/SCORECARD.md` carries the 20/20, and `eval/FINDINGS-HARD.md` carries the hard-set error
analysis: every miss, its root cause, and what changed. A cost-capped live demo runs the real model at
[suver-demo.onrender.com](https://suver-demo.onrender.com) — open any tool, and when the answer isn't in your document,
watch it say so.
