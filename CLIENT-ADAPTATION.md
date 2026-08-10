# Client Adaptation — turning the generic MVP into "this org's Suver"

> The persistence MVP (DEC 034) ships as a **generic, made-up client** — an org called *"Northwind Legal (demo)"* with
> email+password accounts and saved work. This is the map from that generic demo to a **real design partner** with the
> least customization possible. Nothing here is required to *run* Suver (anonymous use needs no accounts); this is the
> "make it theirs" layer.

## What the MVP already gives you
- **Accounts** — register / sign in / sign out (email + password, salted `pbkdf2_hmac`, `app/store.py`).
- **Saved work + resume** — a signed-in user clicks **💾 Save to my work** on any tool; **My work** (`/workspace`) lists
  it; **Open** re-loads the document + question into the tool, ready to re-run. Survives logout / closing the app.
- **Anonymous still works** — no tool requires an account; sign-in only *adds* save/history.
- **One SQLite file** (`data/suver.db`, gitignored) — trivial to run, back up, and hand over.
- **An `org` field on every user** — the seam for per-org branding, policy, and (later) model choice.

## Adopting for a specific client — the short list

### 1. Branding (minutes)
- Set `ORG_NAME` (env) to the client's name — it shows in the account UI. Swap the wordmark in `base.html` (`.brand`)
  and the palette tokens in `:root` (already theme-aware, light + dark). Drop a logo into `app/shell/static/`.
- *Effort: trivial — config + a few CSS tokens. No code.*

### 2. Auth — upgrade the sign-in method (the seam is already isolated)
Everything routes through `store.authenticate()` / `store.create_user()`. To add a method, implement it behind those
two functions; **callers and templates don't change**. Recommended ladder:
- **Now (MVP):** email + password — universal, zero dependency, demoable to any org.
- **Consumer friction↓:** Google / Microsoft social login (OAuth) — a `authlib`/OAuth adapter that resolves to a `User`.
- **Enterprise (the licensing endgame):** **org-SSO via OIDC/SAML** — the client's IT connects their identity provider;
  users never make a Suver password. This is what a firm expects when it *licenses* seats.
- *Effort: social ~½ day; org-SSO ~1–2 days per protocol. The data model already carries `org`.*

### 3. Per-org isolation & policy
- **Tenanting:** every `saved_items`/`sessions` row already keys to a user; add an `org_id` and scope queries by org
  for a shared multi-tenant deployment, **or** give each client their own DB file / database (simplest, strongest
  isolation — recommended for a first design partner).
- **Policy per org:** the Data-Boundary policy is already the single adaptation surface — a client with stricter rules
  (e.g. a law firm's privilege classes) gets a per-org policy without touching tools.

### 4. Per-org model choice / bring-your-own-key *(ties to `EMBEDDINGS-PLAN.md`)*
- Store the client's chosen chat model + (optionally) their **own API key** on the org record. The key stays server-side;
  Suver calls *their* contracted vendor on their behalf — a selling point (data goes to a vendor they already trust)
  and a cost model (their spend). Generalizes today's `PROVIDER=anthropic|stub`.

### 5. Production hardening (before real user data)
The MVP is demo-grade on these; each is a known, bounded lap:
- **Storage:** encrypt documents at rest (or store only references / re-fetch); consider not persisting raw docs for
  the most sensitive clients (save a pointer + re-upload). Swap SQLite → Postgres by changing `app/store.py` only.
- **Sessions:** add expiry / rotation (tokens currently don't expire); `Secure` cookie flag behind HTTPS; the cookie is
  already `HttpOnly` + `SameSite=Lax`.
- **CSRF:** add a token to the state-changing POSTs (`/save`, `/logout`, `/register`, `/login`); `SameSite=Lax` covers
  the common case but a token is the belt-and-suspenders for production.
- **Abuse:** rate-limit `/login` + `/register` (lockout / backoff); add password-reset (needs an email sender).
- **Ops:** backups of the DB; audit log of sign-ins; a real `SECRET`/deployment config.
- *None block a pilot on synthetic or low-sensitivity content; all are standard and scoped.*

## The one-line pitch to a design partner
> *"It already works anonymously. Turn on accounts and your team saves and resumes their work; put your firm's name and
> SSO on it in a day; keep every document inside your own tenant — and, if you want, running through your own model and
> key. The trust guarantees (sanitize-before-egress, cite-or-abstain, the 20/20 scorecard) don't change — they're the
> foundation, per-org config rides on top."*
