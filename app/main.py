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

from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import __version__
from app.config import settings
from app.tools import ToolError, ToolInput, all_tools, get, load_builtin

BASE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE / "shell" / "templates"))

app = FastAPI(title="Project Suver", version=__version__)
load_builtin()

_static = BASE / "shell" / "static"
if _static.exists():
    app.mount("/static", StaticFiles(directory=str(_static)), name="static")


def _ctx(request: Request, **extra) -> dict:
    return {"request": request, "app_version": __version__, "provider": settings.provider, **extra}


@app.get("/", response_class=HTMLResponse)
def hub(request: Request):
    return templates.TemplateResponse(request, "hub.html", _ctx(request, tools=all_tools()))


@app.get("/t/{slug}", response_class=HTMLResponse)
def tool_page(request: Request, slug: str):
    tool = get(slug)
    if tool is None:
        return templates.TemplateResponse(request, "not_found.html", _ctx(request), status_code=404)
    return templates.TemplateResponse(request, "tool.html", _ctx(request, tool=tool))


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

    try:
        out = tool.run(ToolInput(filename=filename, data=data, paste=paste, query=query, choice=choice,
                                 filename2=filename2, data2=data2, paste2=paste2, session=session))
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


@app.get("/healthz")
def healthz():
    return {"ok": True, "version": __version__, "provider": settings.provider, "tools": [t.slug for t in all_tools()]}
