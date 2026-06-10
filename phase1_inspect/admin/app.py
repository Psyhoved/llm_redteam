"""FastAPI application for Phase 1 benchmark admin."""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from admin import config, db, runner

APP_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))

app = FastAPI(title="Phase 1 Admin", version="0.1.0")
app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")


def _parse_labs(mode: str, selected: list[str] | None) -> list[str] | None:
    if mode == "all":
        return None
    if not selected:
        raise HTTPException(status_code=400, detail="select at least one lab")
    return selected


def _resolve_run_context(run_id: int) -> dict[str, Any]:
    try:
        payload = db.get_run(run_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    run = payload["run"]
    meta = runner.find_launch_meta_by_run_id(run_id)
    screen_log = None
    if meta and meta.get("screen_log"):
        screen_log = meta["screen_log"]
    elif run.get("screen_session"):
        found = runner.find_screen_log(run["screen_session"])
        screen_log = str(found) if found else None
    metrics_report = config.METRICS_DIR / f"run_{run_id}" / "report.html"
    return {
        "run": run,
        "lab_runs": payload["lab_runs"],
        "meta": meta,
        "screen_log": screen_log,
        "metrics_report_exists": metrics_report.is_file(),
        "metrics_report_path": str(metrics_report),
        "inspect_view_port": config.INSPECT_VIEW_PORT,
    }


@app.get("/", response_class=HTMLResponse)
async def new_run_form(request: Request) -> HTMLResponse:
    env_defaults = config.read_env_defaults()
    return templates.TemplateResponse(
        request,
        "new_run.html",
        {
            "labs": config.LAB_REGISTRY,
            "limit_presets": config.LIMIT_PRESETS,
            "default_limit": config.DEFAULT_LIMIT,
            "default_session": runner.default_session_name(),
            "env_defaults": env_defaults,
        },
    )


@app.get("/runs", response_class=HTMLResponse)
async def runs_list(request: Request) -> HTMLResponse:
    runs = db.list_runs(limit=100)
    return templates.TemplateResponse(request, "runs.html", {"runs": runs})


@app.get("/runs/pending/{screen_session}", response_class=HTMLResponse)
async def run_pending(request: Request, screen_session: str) -> HTMLResponse:
    run_id = db.find_run_by_session(screen_session)
    if run_id is not None:
        runner.attach_run_id_to_session(screen_session, run_id)
        return RedirectResponse(url=f"/runs/{run_id}", status_code=303)
    meta = runner.load_launch_meta(screen_session)
    return templates.TemplateResponse(
        request,
        "run_pending.html",
        {
            "screen_session": screen_session,
            "meta": meta,
            "screen_log": meta.get("screen_log") if meta else None,
        },
    )


@app.get("/runs/{run_id}", response_class=HTMLResponse)
async def run_detail(request: Request, run_id: int) -> HTMLResponse:
    ctx = _resolve_run_context(run_id)
    return templates.TemplateResponse(request, "run_detail.html", ctx)


@app.get("/api/runs")
async def api_list_runs(limit: int = 50) -> JSONResponse:
    return JSONResponse(db.list_runs(limit=limit))


@app.get("/api/runs/{run_id}")
async def api_get_run(run_id: int) -> JSONResponse:
    try:
        return JSONResponse(db.get_run(run_id))
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/runs/{run_id}/screen-log")
async def api_screen_log(run_id: int) -> HTMLResponse:
    ctx = _resolve_run_context(run_id)
    log_path = ctx.get("screen_log")
    content = ""
    if log_path:
        content = runner.tail_file(Path(log_path))
    if not content:
        content = "(log not available yet)"
    return HTMLResponse(f'<pre class="log-tail">{html.escape(content)}</pre>')


@app.get("/api/pending/{screen_session}/screen-log")
async def api_pending_screen_log(screen_session: str) -> HTMLResponse:
    meta = runner.load_launch_meta(screen_session)
    log_path = meta.get("screen_log") if meta else None
    if not log_path:
        found = runner.find_screen_log(screen_session)
        log_path = str(found) if found else None
    content = runner.tail_file(Path(log_path)) if log_path else "(waiting for log file...)"
    return HTMLResponse(f'<pre class="log-tail">{html.escape(content)}</pre>')


@app.get("/api/pending/{screen_session}/status")
async def api_pending_status(screen_session: str) -> JSONResponse:
    run_id = db.find_run_by_session(screen_session)
    if run_id is not None:
        runner.attach_run_id_to_session(screen_session, run_id)
    return JSONResponse({"run_id": run_id, "ready": run_id is not None})


@app.post("/api/runs")
async def api_create_run(
    limit: int = Form(...),
    mode: str = Form("all"),
    labs: list[str] | None = Form(None),
    at_moscow: str = Form(""),
    screen_session: str = Form(...),
    target_model: str = Form(""),
    grader_model: str = Form(""),
    max_connections: str = Form(""),
) -> RedirectResponse:
    try:
        selected_labs = _parse_labs(mode, labs)
        max_conn = int(max_connections) if max_connections.strip() else None
        req = runner.LaunchRequest(
            limit=limit,
            labs=selected_labs,
            at_moscow=at_moscow.strip() or None,
            screen_session=screen_session.strip() or runner.default_session_name(),
            target_model=target_model.strip() or None,
            grader_model=grader_model.strip() or None,
            max_connections=max_conn,
        )
        result = runner.launch(req)
    except (runner.LaunchError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return RedirectResponse(
        url=f"/runs/pending/{result.screen_session}",
        status_code=303,
    )


@app.post("/api/runs/{run_id}/metrics")
async def api_build_metrics(run_id: int) -> RedirectResponse:
    try:
        runner.build_metrics(run_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return RedirectResponse(url=f"/runs/{run_id}", status_code=303)
