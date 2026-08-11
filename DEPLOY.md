# Deploy — a free, cost-safe live demo (Render)

> Goal: a public URL you can put on a résumé / hand to an interviewer, at **$0 hosting** and with the API bill
> protected by the built-in usage quotas (DEC 037). Render's free Web Service tier is the simplest path; Fly.io /
> Railway / Hugging Face Spaces work the same way (Docker + env vars).

## Before public exposure — what protects the API bill
- **Per-subject daily quota** (DEC 037): anonymous visitors are capped at `QUOTA_ANON` model-runs/day **per IP**
  (default 15; set it lower for a public demo, e.g. 10). Chart is local (no model, no cost).
- **Before broadcasting the link widely** (e.g., posting on LinkedIn), add a **global daily cap** as a backstop — a
  small follow-up. For sharing with specific people, the per-IP quota is plenty.

## Render — step by step (≈ 10 min, mostly waiting on the build)
1. **Sign up** at https://render.com — use **"Sign in with GitHub"** (auto-connects your repos).
2. **New + → Web Service.**
3. **Connect the `project-suver` repo** (grant Render access if prompted). Public or private both work.
4. Render detects the **Dockerfile** → *Runtime: Docker*. Set:
   - **Name:** `suver-demo` (→ URL becomes `https://suver-demo.onrender.com`)
   - **Branch:** `main` · **Region:** closest to you · **Instance type: Free**
5. **Environment variables** (Advanced → Add Environment Variable):
   | Key | Value | Note |
   |---|---|---|
   | `ANTHROPIC_API_KEY` | *your key* | mark **Secret** |
   | `PROVIDER` | `anthropic` | use the real model |
   | `COOKIE_SECURE` | `1` | Render serves HTTPS |
   | `QUOTA_ANON` | `10` | tighter cap for a public demo *(optional)* |
   | `ORG_NAME` | `Suver` | *(optional — hides the "Northwind Legal (demo)" default)* |
6. *(Optional)* **Health Check Path:** `/healthz`.
7. **Create Web Service** → it builds the image + deploys (~3–5 min). When it's live, open the URL and click
   **✨ Try an example** on any tool to confirm.

## Caveats on the free tier (fine for a demo — just know them)
- **Cold start:** free services spin down after ~15 min idle; the next request takes ~30–60s to wake. Click the link
  to warm it before a scheduled demo, or just mention "give it a few seconds."
- **Ephemeral disk:** the SQLite DB (accounts · saved work · usage counts) **resets on each deploy/restart.** The
  anonymous **Try-an-example** path — your main showcase — is unaffected. Persistent accounts need a paid disk (defer).
- **Cost:** hosting is $0; the only spend is the API key, capped by the quota above.

## Updating the deployed demo
Push to `main` → Render auto-redeploys (if auto-deploy is on). Or hit **Manual Deploy → Deploy latest commit**.

## Local run (unchanged)
`PYTHONUTF8=1 .venv/Scripts/python.exe -m uvicorn app.main:app --port 8000` → http://127.0.0.1:8000
