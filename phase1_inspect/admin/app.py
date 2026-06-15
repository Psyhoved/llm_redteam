"""FastAPI application for Phase 1 benchmark admin."""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import asyncio

from admin import config, datasets, db, inspect_view, runner

APP_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))

app = FastAPI(title="Phase 1 Admin", version="0.1.0")
app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")


def _parse_benchmarks(mode: str, selected: list[str] | None) -> list[str] | None:
    if mode == "all":
        return None
    if not selected:
        raise HTTPException(status_code=400, detail="select at least one benchmark")
    return selected


def _live_panel_context(run_id: int) -> dict[str, Any]:
    try:
        payload = db.get_run(run_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    run = payload["run"]
    progress: dict[str, Any] = {}
    try:
        progress = db.get_run_progress(run_id)
    except RuntimeError:
        progress = {}
    effective_status = runner.resolve_run_status({**run, **progress})
    stale = effective_status == "stale" or bool(progress.get("stale"))
    run = {**run, "status": effective_status, "stale": stale}
    return {
        "run": run,
        "lab_runs": progress.get("lab_runs") or payload["lab_runs"],
        "progress": progress,
        "stale": stale,
        "effective_status": effective_status,
    }


def _resolve_eval_log_path(eval_log: str) -> Path:
    path = Path(eval_log)
    if not path.is_file():
        alt = config.PHASE1_DIR / eval_log
        if alt.is_file():
            return alt
    return path


def _current_eval_log(progress: dict[str, Any]) -> str | None:
    lab_runs = progress.get("lab_runs") or []
    for lr in reversed(lab_runs):
        eval_log = lr.get("eval_log")
        if eval_log:
            return str(_resolve_eval_log_path(str(eval_log)))
    benchmark = progress.get("current_benchmark")
    if not benchmark:
        return None
    from scripts.phase1_progress import find_newest_eval_log

    found = find_newest_eval_log(config.PHASE1_DIR, str(benchmark))
    return str(found) if found else None


def _fetch_live_samples_sync(eval_log: str, limit: int = 20) -> tuple[list[dict[str, Any]], str]:
    from scripts.phase1_live_samples import collect_samples

    path = _resolve_eval_log_path(eval_log)
    if not path.is_file():
        return [], f"eval log not found: {path}"
    try:
        return list(collect_samples(path, limit=limit)), ""
    except Exception as ex:  # noqa: BLE001
        return [], f"{type(ex).__name__}: {ex}"


async def _fetch_live_samples(eval_log: str, limit: int = 20) -> tuple[list[dict[str, Any]], str]:
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_fetch_live_samples_sync, eval_log, limit),
            timeout=30.0,
        )
    except asyncio.TimeoutError:
        return [], "таймаут чтения .eval (файл ещё пишется?)"


def _samples_live_context(progress: dict[str, Any]) -> dict[str, Any]:
    eval_log = _current_eval_log(progress)
    samples_error = ""
    if eval_log:
        samples_error = ""
    elif progress.get("current_benchmark"):
        samples_error = "ожидание .eval файла…"
    else:
        samples_error = "нет активного бенчмарка"
    return {
        "samples": [],
        "samples_error": samples_error,
        "eval_log": eval_log,
        "samples_loading": bool(eval_log),
    }


async def _samples_live_context_loaded(progress: dict[str, Any]) -> dict[str, Any]:
    ctx = _samples_live_context(progress)
    if ctx["eval_log"]:
        samples, err = await _fetch_live_samples(str(ctx["eval_log"]))
        ctx["samples"] = samples
        if err:
            ctx["samples_error"] = err
        ctx["samples_loading"] = False
    return ctx


def _inspect_context(progress: dict[str, Any], effective_status: str) -> dict[str, Any]:
    eval_log = _current_eval_log(progress)
    online = inspect_view.is_inspect_view_running()
    dashboard_url = inspect_view.inspect_dashboard_url(eval_log)
    show_iframe = online and (
        effective_status == "running" or bool(eval_log)
    )
    return {
        "inspect_view_online": online,
        "inspect_view_url": config.INSPECT_VIEW_URL,
        "inspect_dashboard_url": dashboard_url,
        "inspect_start_command": inspect_view.start_command(),
        "inspect_view_port": config.INSPECT_VIEW_PORT,
        "show_inspect_iframe": show_iframe,
        "current_eval_log": eval_log,
    }


def _resolve_run_context(run_id: int) -> dict[str, Any]:
    try:
        payload = db.get_run(run_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    run = payload["run"]
    progress: dict[str, Any] = {}
    try:
        progress = db.get_run_progress(run_id)
    except RuntimeError:
        progress = {}
    effective_status = runner.resolve_run_status({**run, **progress})
    stale = effective_status == "stale" or bool(progress.get("stale"))
    run = {**run, "status": effective_status, "stale": stale}
    if progress.get("samples_done") is not None:
        run["samples_done"] = progress["samples_done"]
    if progress.get("samples_total") is not None:
        run["samples_total"] = progress["samples_total"]
    if progress.get("current_benchmark"):
        run["current_benchmark"] = progress["current_benchmark"]
    meta = runner.find_launch_meta_by_run_id(run_id)
    screen_log = None
    if meta and meta.get("screen_log"):
        screen_log = meta["screen_log"]
    elif run.get("screen_session"):
        found = runner.find_screen_log(run["screen_session"])
        screen_log = str(found) if found else None
    metrics_report = config.METRICS_DIR / f"run_{run_id}" / "report.html"
    ctx = {
        "run": run,
        "lab_runs": progress.get("lab_runs") or payload["lab_runs"],
        "meta": meta,
        "screen_log": screen_log,
        "metrics_report_exists": metrics_report.is_file(),
        "metrics_report_path": str(metrics_report),
        "progress": progress,
        "stale": stale,
        "effective_status": effective_status,
    }
    ctx.update(_inspect_context(progress, effective_status))
    return ctx


@app.get("/", response_class=HTMLResponse)
async def new_run_form(request: Request) -> HTMLResponse:
    env_defaults = config.read_env_defaults()
    return templates.TemplateResponse(
        request,
        "new_run.html",
        {
            "benchmarks": config.all_benchmarks(),
            "limit_presets": config.LIMIT_PRESETS,
            "default_limit": config.DEFAULT_LIMIT,
            "default_session": runner.default_session_name(),
            "env_defaults": env_defaults,
        },
    )


@app.get("/datasets", response_class=HTMLResponse)
async def datasets_list(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "datasets.html",
        {"datasets": datasets.list_datasets()},
    )


@app.get("/datasets/{dataset_id:path}", response_class=HTMLResponse)
async def dataset_detail(request: Request, dataset_id: str) -> HTMLResponse:
    try:
        record = datasets.get_dataset(dataset_id)
        preview = datasets.preview_dataset(dataset_id, limit=50)
    except datasets.DatasetError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return templates.TemplateResponse(
        request,
        "dataset_detail.html",
        {"dataset": record, "preview": preview},
    )


@app.get("/api/datasets/{dataset_id:path}/preview", response_model=None)
async def api_dataset_preview(request: Request, dataset_id: str, limit: int = 50):
    try:
        preview = datasets.preview_dataset(dataset_id, limit=limit)
    except datasets.DatasetError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if request.headers.get("accept", "").startswith("application/json"):
        return JSONResponse(
            {
                "dataset_id": preview.dataset_id,
                "columns": preview.columns,
                "rows": preview.rows,
                "row_count": preview.row_count,
                "limit": preview.limit,
            }
        )
    return templates.TemplateResponse(
        request,
        "partials/dataset_preview_table.html",
        {"preview": preview},
    )


@app.post("/api/datasets/inspect-upload", response_model=None)
async def api_inspect_dataset_upload(
    request: Request,
    dataset_file: UploadFile = File(...),
):
    content = await dataset_file.read()
    filename = dataset_file.filename or "upload.csv"
    try:
        inspect_result = datasets.inspect_upload(content, filename)
    except datasets.DatasetError as exc:
        if request.headers.get("HX-Request"):
            return HTMLResponse(
                f'<p class="banner banner-warn">{html.escape(str(exc))}</p>',
                status_code=400,
            )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return templates.TemplateResponse(
        request,
        "partials/dataset_upload_mapping.html",
        {"inspect": inspect_result},
    )


@app.post("/api/datasets")
async def api_create_dataset(
    upload_token: str = Form(...),
    title: str = Form(...),
    slug: str = Form(...),
    description: str = Form(""),
    map_input: str = Form(...),
    map_target: str = Form(""),
    map_metadata: str = Form(""),
) -> RedirectResponse:
    try:
        content, filename = datasets.consume_staged_upload(upload_token)
    except datasets.DatasetError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    column_mapping: dict[str, str] = {"input": map_input.strip()}
    if map_target.strip():
        column_mapping["target"] = map_target.strip()

    try:
        record = datasets.save_custom_dataset(
            content,
            filename,
            title=title,
            description=description,
            slug=slug,
            column_mapping=column_mapping,
            metadata_csv=map_metadata,
        )
    except datasets.DatasetConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except datasets.DatasetError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return RedirectResponse(url=f"/datasets/{record.id}", status_code=303)


@app.post("/api/datasets/{dataset_id:path}/delete")
async def api_delete_dataset(dataset_id: str) -> RedirectResponse:
    try:
        datasets.delete_custom_dataset(dataset_id)
    except datasets.DatasetForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except datasets.DatasetError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return RedirectResponse(url="/datasets", status_code=303)


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
    ctx.update(await _samples_live_context_loaded(ctx["progress"]))
    return templates.TemplateResponse(request, "run_detail.html", ctx)


@app.get("/api/runs")
async def api_list_runs(limit: int = 50) -> JSONResponse:
    return JSONResponse(db.list_runs(limit=limit))


@app.get("/api/runs/table", response_model=None)
async def api_runs_table(request: Request) -> HTMLResponse:
    runs = db.list_runs(limit=100)
    return templates.TemplateResponse(
        request,
        "partials/runs_table_body.html",
        {"runs": runs},
    )


@app.get("/api/runs/{run_id}")
async def api_get_run(run_id: int) -> JSONResponse:
    try:
        return JSONResponse(db.get_run(run_id))
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/runs/{run_id}/live-panel", response_model=None)
async def api_run_live_panel(request: Request, run_id: int):
    ctx = _live_panel_context(run_id)
    if request.headers.get("accept", "").startswith("application/json"):
        return JSONResponse(ctx)
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(
            request,
            "partials/run_live_panel.html",
            ctx,
        )
    return JSONResponse(ctx)


@app.get("/api/runs/{run_id}/samples-live", response_model=None)
async def api_run_samples_live(request: Request, run_id: int):
    ctx = _live_panel_context(run_id)
    template_ctx = await _samples_live_context_loaded(ctx["progress"])
    if request.headers.get("accept", "").startswith("application/json"):
        return JSONResponse(template_ctx)
    return templates.TemplateResponse(
        request,
        "partials/run_samples_live.html",
        template_ctx,
    )


@app.get("/api/runs/{run_id}/progress", response_model=None)
async def api_run_progress(request: Request, run_id: int):
    try:
        progress = db.get_run_progress(run_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    run_payload = db.get_run(run_id)["run"]
    effective_status = runner.resolve_run_status({**run_payload, **progress})
    progress["status"] = effective_status
    progress["stale"] = effective_status == "stale" or bool(progress.get("stale"))
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(
            request,
            "partials/run_progress.html",
            {"progress": progress, "run_id": run_id},
        )
    return JSONResponse(progress)


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
    benchmarks: list[str] | None = Form(None),
    labs: list[str] | None = Form(None),
    at_moscow: str = Form(""),
    screen_session: str = Form(...),
    target_model: str = Form(""),
    grader_model: str = Form(""),
    max_connections: str = Form(""),
) -> RedirectResponse:
    try:
        selected = benchmarks if benchmarks else labs
        selected_benchmarks = _parse_benchmarks(mode, selected)
        max_conn = int(max_connections) if max_connections.strip() else None
        req = runner.LaunchRequest(
            limit=limit,
            benchmarks=selected_benchmarks,
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
