# Launch Readiness — the path from "great demo" to "anyone can pay to use it"

> The concrete checklist between the current state (a pilot-ready product with accounts, a measured 20/20 trust
> scorecard, and a distinct visual identity) and a **public, self-serve, paid** product. Written so the one remaining
> **cost decision (billing)** is a small, well-scoped flip — not a rewrite. Everything here except billing is
> already-zero-cost or done. Cost-bearing items are marked 💲 and deliberately deferred.

## Where we are (done)
- ✅ **13 tools, 3 platforms**, one shell — no prompt, no config; every result cited or an honest abstention.
- ✅ **Trust, measured** — `python -m eval.run` → **20/20** (0 hallucination, 0 fabrication), re-runnable on any corpus.
- ✅ **Accounts + saved work** (DEC 034) — sign in, save, resume; anonymous use untouched.
- ✅ **Pilot-grade hardening** (DEC 035) — session expiry · auth rate-limit · Secure/HttpOnly/SameSite cookies · a `Dockerfile`.
- ✅ **Usage quotas + plan tiers** (DEC 037) — a stranger **cannot** run up the API bill; free/pro caps enforced before
  every model call (Chart is local, exempt). **This is the guardrail that makes public exposure safe.**
- ✅ **Friction-free demo** (DEC 037) — "Try an example" on every single-input tool → a real cited result in one click.

## The tiers (defined now; billing plugs in later)
| Tier | Who | Daily model-runs (default) | Set by |
|---|---|:--:|---|
| **Anonymous** | no account | `QUOTA_ANON` = 15 / IP | automatic |
| **Free** | signed in | `QUOTA_FREE` = 75 / user | on registration |
| **Pro** | paid (later) | `QUOTA_PRO` = 100000 / user | `store.set_plan(id, "pro")` — **billing flips this** |
- All caps are env-configurable; tune per real traffic. The `plan` column already exists on every user.

## The ONE remaining cost decision — 💲 billing (deferred)
When Trevor is ready to accept the cost, **billing is a contained add** — the seam is already built:
1. Add a payment provider (Stripe is the obvious pick) — a checkout link + a webhook. *(💲 the only new vendor/cost.)*
2. On "payment succeeded" → `store.set_plan(user_id, "pro")`. On cancel/lapse → back to `"free"`. **That's the whole
   integration point** — the quota system already reads `plan`.
3. A `/pricing` page + an "Upgrade" button (the `_limit.html` partial already nudges toward it).
4. *(Optional)* metered/overage billing later reads the same `usage` table.
Estimate: ~1 focused session once the cost is greenlit. Until then, "pro" is granted manually (comps, design partners).

## Before flipping it public — the GA checklist (mostly zero-cost)
**Security / abuse (zero-cost unless noted):**
- [ ] **CSRF tokens** on state-changing POSTs (`/save`, `/logout`, `/register`, `/login`) — `SameSite=Lax` is today's
      mitigation; a token is the GA belt-and-suspenders.
- [ ] **Password reset** — 💲 needs an email sender (SES/Postmark/etc.) — small cost, deferrable until real signups.
- [ ] **Audit log** of sign-ins + admin actions (zero-cost; a table).
- [ ] Move the **rate limiter** from in-memory to the DB/shared store if running >1 instance (zero-cost).
- [ ] **Encryption at rest** for saved documents (or store references / don't persist raw docs for sensitive users).
- [ ] A real **`SECRET`** + config management on deploy.

**Product / trust:**
- [ ] A **Terms + Privacy** page (what's stored, that sanitized text goes to the model, data handling). *(Writing, zero-cost.)*
- [ ] A clear **"what happens to my data"** explainer on the hub (the boundary story is the selling point — say it plainly).
- [ ] Decide **anonymous access policy** for public launch (keep the low anon quota, or require sign-in to run at all).

**Ops (💲 hosting — deferred):**
- [ ] A **hosted instance** behind HTTPS (any container host; `Dockerfile` is ready). Set `COOKIE_SECURE=1`. *(💲 hosting cost.)*
- [ ] **Backups** of the SQLite DB (or move to managed Postgres — swap is isolated to `app/store.py`).
- [ ] Basic **uptime/error monitoring**.

## Two launch shapes (both supported by what exists)
1. **Show-it-off / demo link (now, ~$0 beyond API):** deploy one instance, keep anonymous + the low quota, hand the
   URL to employers/partners. "Try an example" makes it self-selling; the eval scorecard is the credibility.
2. **Public paid (when billing is greenlit):** the same instance + Stripe + a `/pricing` page + the GA checklist above.
The gap between the two is **only billing + the GA hardening** — no product rebuild.
