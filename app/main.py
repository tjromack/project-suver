"""Project Suver — the app: the hub launcher + the tool-app shell + the Summarize tool.

Routes (the whole product surface):
  GET  /                 the hub — browse tools, click to open
  GET  /t/{slug}         the tool-app shell (one drop/paste zone, one action, one result slot, zero config)
  POST /t/{slug}/run     run the tool on the user's input → the result partial (HTMX swaps it into #result)
  GET  /healthz          liveness

The shell + hub are generic over the `Tool` contract (app/tools). Sanitize-before-egress and cite-or-drop live in
the pipeline the tool calls, so every tool inherits them. Modern `TemplateResponse(request, …)` throughout.
"""

from __future__ import annotations

import time
from collections import deque
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import __version__
from app import store
from app.config import settings
from app.ingest import IngestError, extract_text, from_paste
from app.store import AccountError, User
from app.tools import ToolError, ToolInput, all_tools, by_platform, get, load_builtin

BASE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE / "shell" / "templates"))

app = FastAPI(title="Project Suver", version=__version__)
load_builtin()
store.init_db()

_static = BASE / "shell" / "static"
if _static.exists():
    app.mount("/static", StaticFiles(directory=str(_static)), name="static")


def _current_user(request: Request) -> User | None:
    """The signed-in user for this request, or None. Anonymous is fully supported — no tool requires an account."""
    return store.session_user(request.cookies.get(settings.session_cookie))


def _ctx(request: Request, **extra) -> dict:
    # `user` is always present (None when anonymous) so the nav/templates render login state everywhere.
    base = {"request": request, "app_version": __version__, "provider": settings.provider,
            "org_name": settings.org_name}
    base.setdefault("user", _current_user(request))
    return {**base, **extra}


@app.get("/", response_class=HTMLResponse)
def hub(request: Request):
    return templates.TemplateResponse(request, "hub.html",
                                      _ctx(request, tools=all_tools(), platforms=by_platform()))


@app.get("/t/{slug}", response_class=HTMLResponse)
def tool_page(request: Request, slug: str, item: int | None = None):
    tool = get(slug)
    if tool is None:
        return templates.TemplateResponse(request, "not_found.html", _ctx(request), status_code=404)
    prefill = None  # resume a saved item: pre-fill the paste box + question, ready to re-run
    if item is not None:
        user = _current_user(request)
        if user is not None:
            saved = store.get_item(user.id, item)
            if saved is not None and saved.tool_slug == slug:
                prefill = saved
    return templates.TemplateResponse(request, "tool.html", _ctx(request, tool=tool, prefill=prefill))


@app.post("/t/{slug}/run", response_class=HTMLResponse)
async def tool_run(
    request: Request,
    slug: str,
    file: UploadFile | None = File(None),
    paste: str = Form(""),
    query: str = Form(""),
    choice: str = Form(""),
    file2: UploadFile | None = File(None),
    paste2: str = Form(""),
    session: str = Form(""),
    files: list[UploadFile] = File([]),
):
    tool = get(slug)
    if tool is None or not tool.is_live:
        return templates.TemplateResponse(
            request, "_error.html", _ctx(request, message="That tool isn't available yet."), status_code=404
        )

    filename = data = None
    if file is not None and file.filename:
        data = await file.read()
        filename = file.filename
    filename2 = data2 = None
    if file2 is not None and file2.filename:
        data2 = await file2.read()
        filename2 = file2.filename

    many: list = []  # several documents at once (Ask across documents): [(filename, bytes), …]
    for f in files or []:
        if f is not None and f.filename:
            many.append((f.filename, await f.read()))

    try:
        out = tool.run(ToolInput(filename=filename, data=data, paste=paste, query=query, choice=choice,
                                 filename2=filename2, data2=data2, paste2=paste2, session=session, many=many))
    except ToolError as e:  # friendly, user-facing
        return templates.TemplateResponse(request, "_error.html", _ctx(request, message=str(e)))
    except Exception:  # defensive — never leak a stack trace to a consumer
        return templates.TemplateResponse(
            request,
            "_error.html",
            _ctx(request, message="Something went wrong reading that. Try another file or paste the text."),
            status_code=500,
        )

    return templates.TemplateResponse(request, out.template, _ctx(request, tool=tool, r=out.result))


# --- Accounts & saved work (persistence MVP, DEC 034) — anonymous use is untouched; sign-in ADDS save/history ----

def _set_session(resp: RedirectResponse, token: str) -> RedirectResponse:
    resp.set_cookie(settings.session_cookie, token, httponly=True, samesite="lax",
                    secure=settings.cookie_secure, max_age=86400 * settings.session_ttl_days)
    return resp


# A tiny in-memory rate limiter for the auth endpoints — blunts credential-stuffing/brute-force. Single-process MVP
# (documented in CLIENT-ADAPTATION.md / DESIGN-PARTNER-KIT.md; a multi-instance deploy moves this to a shared store).
_auth_hits: dict[str, deque] = {}


def _rate_limited(request: Request) -> bool:
    ip = request.client.host if request.client else "?"
    now = time.time()
    window, cap = settings.auth_rate_window_s, settings.auth_rate_max
    hits = _auth_hits.setdefault(ip, deque())
    while hits and now - hits[0] > window:
        hits.popleft()
    if len(hits) >= cap:
        return True
    hits.append(now)
    return False


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = "/"):
    if _current_user(request) is not None:
        return RedirectResponse("/workspace", status_code=303)
    return templates.TemplateResponse(request, "login.html", _ctx(request, next=next, error=None))


@app.post("/register", response_class=HTMLResponse)
def register(request: Request, email: str = Form(""), password: str = Form(""), org: str = Form(""),
             next: str = Form("/")):
    if _rate_limited(request):
        return templates.TemplateResponse(request, "login.html",
                                          _ctx(request, next=next, mode="register",
                                               error="Too many attempts — wait a minute and try again."),
                                          status_code=429)
    try:
        user = store.create_user(email, password, org)
    except AccountError as e:
        return templates.TemplateResponse(request, "login.html",
                                          _ctx(request, next=next, error=str(e), mode="register"), status_code=400)
    return _set_session(RedirectResponse(next or "/", status_code=303), store.create_session(user.id))


@app.post("/login", response_class=HTMLResponse)
def login(request: Request, email: str = Form(""), password: str = Form(""), next: str = Form("/")):
    if _rate_limited(request):
        return templates.TemplateResponse(request, "login.html",
                                          _ctx(request, next=next, mode="login",
                                               error="Too many attempts — wait a minute and try again."),
                                          status_code=429)
    try:
        user = store.authenticate(email, password)
    except AccountError as e:
        return templates.TemplateResponse(request, "login.html",
                                          _ctx(request, next=next, error=str(e), mode="login"), status_code=400)
    return _set_session(RedirectResponse(next or "/", status_code=303), store.create_session(user.id))


@app.post("/logout")
def logout(request: Request):
    store.end_session(request.cookies.get(settings.session_cookie))
    resp = RedirectResponse("/", status_code=303)
    resp.delete_cookie(settings.session_cookie)
    return resp


@app.get("/workspace", response_class=HTMLResponse)
def workspace(request: Request):
    user = _current_user(request)
    if user is None:
        return RedirectResponse("/login?next=/workspace", status_code=303)
    items = store.list_items(user.id)
    return templates.TemplateResponse(request, "workspace.html",
                                      _ctx(request, items=items, tool_of=get))


@app.post("/save")
async def save(request: Request, tool_slug: str = Form(""), title: str = Form(""),
               file: UploadFile | None = File(None), paste: str = Form(""), query: str = Form("")):
    user = _current_user(request)
    if user is None:
        return HTMLResponse("sign-in-required", status_code=401)
    text = ""
    name = ""
    try:
        if file is not None and file.filename:
            name = file.filename
            text = extract_text(file.filename, await file.read()).text
        elif paste and paste.strip():
            text = from_paste(paste).text
    except IngestError:
        text = paste or ""
    if not (text.strip() or query.strip()):
        return HTMLResponse("nothing-to-save", status_code=400)
    title = (title.strip() or name or (query.strip()[:60]) or (text.strip()[:60]) or "Saved item")
    item = store.save_item(user.id, tool_slug or "copilot", title, text=text, query=query)
    return HTMLResponse(f'Saved ✓ — <a href="/workspace">My work</a> (#{item.id})')


@app.post("/item/{item_id}/delete")
def delete_item(request: Request, item_id: int):
    user = _current_user(request)
    if user is not None:
        store.delete_item(user.id, item_id)
    return RedirectResponse("/workspace", status_code=303)


@app.get("/healthz")
def healthz():
    return {"ok": True, "version": __version__, "provider": settings.provider, "tools": [t.slug for t in all_tools()]}
