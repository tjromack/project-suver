# Embeddings & Multi-Provider Plan — parked, ready to flip on fast

> Status: **parked (no spend)** per Trevor (2026-08-10). Retrieval today is in-stack (lexical + stemming DEC 031 +
> model-assisted query expansion DEC 032), scored **20/20** on the Trust & Quality eval. This doc is the quick-onboard
> plan for **true dense embeddings** and the larger direction Trevor surfaced: **let the org/user choose the model and
> bring their own key.**

## Why parked (and what would un-park it)
True dense embeddings need *either* a heavy local model (torch, ~GB — breaks the lean/dependency-free principle) *or*
an **external vendor** (a new key, a new **egress destination** for user text, per-token cost). The in-stack retrieval
is already strong (measured 20/20), so embeddings are a *quality ceiling-raiser*, not a gap. Un-park when: (a) a design
partner's corpus is large/paraphrase-heavy enough that recall misses show up, or (b) we want the "your model, your key"
story live for a specific buyer.

## The seam (small, so onboarding is fast)
Introduce a provider abstraction so retrieval can swap backends without touching the tools or the grounding gate:

```
app/embeddings/
  base.py        Embedder protocol: embed(texts: list[str]) -> list[vector];  is_available() -> bool
  none.py        NullEmbedder — returns nothing; retrieval falls back to lexical + expansion (TODAY, default)
  voyage.py      VoyageEmbedder — Voyage API (has a FREE tier: ~200M tokens); reads VOYAGE_API_KEY
  openai.py      OpenAIEmbedder — text-embedding-3-*; reads OPENAI_API_KEY
```

`_retrieve` gains a semantic path: when an embedder `is_available()`, rank spans by **cosine(query_vec, span_vec)**,
blended with the existing lexical/expansion score (`final = max(lexical, α·semantic)`) so it's strictly additive — it
can only *find more*, never lose the lexical hits. **The grounding gate stays exactly as-is** (DEC 031/032 discipline:
improve retrieval, never loosen grounding). Only sanitized `safe_text` is ever embedded (same trust posture as every
model call today). Span vectors are cached per document within a request; no vector DB needed for the MVP (small
corpora) — add one (sqlite-vec / a hosted store) only when corpora grow.

## The bigger direction — "your model, your key" (B2B2C fit)
Trevor's insight: clients should be able to **pick the model(s)** and optionally **bring their own API key**. This
generalizes the current `PROVIDER=anthropic|stub`:
- A **per-org model config** (which chat model, which embedder) + **per-org keys**, stored with the org record once
  accounts exist (see the persistence MVP, DEC 034). The key never leaves the server; it's used to call the org's
  chosen vendor on their behalf.
- This turns "which vendor do WE use" into "which vendor does the CLIENT want" — a selling point (data goes to *their*
  chosen, contracted vendor) and a cost model (their spend, their key).
- **Sequencing:** accounts/persistence first (DEC 034) → then per-org model config rides on the org record → then the
  embedder seam above is just one more configurable provider.

## Quick-onboard checklist (when Trevor says go)
1. Add `app/embeddings/{base,none,voyage}.py` + `EMBEDDER` setting (default `none`).
2. Wire the semantic path into `_retrieve` (additive blend; grounding untouched).
3. Add ~4 eval cases with paraphrase gaps the lexical+expansion path *still* misses; confirm the embedder closes them
   and the Trust scorecard stays ≥ today.
4. Voyage free tier for dev (no spend); document the cost model for production before enabling per-org.
5. Only then consider a vector store (corpus size dependent).

**Estimate:** ~1 focused session for the seam + Voyage backend + eval, once un-parked. No spend on the free tier.
