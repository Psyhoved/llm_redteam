"""FastAPI application for Phase 1 benchmark admin."""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any

from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import asyncio

from admin import config, datasets, db, hf_runner, inspect_view, runner
from scripts import phase1_progress

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
    terminal = effective_status not in {"running", "stale"}
    lab_runs = progress.get("lab_runs") or payload["lab_runs"]
    lab_runs = _enrich_lab_runs_from_eval_logs(
        lab_runs,
        limit=_run_limit(run, progress),
        count_samples=terminal,
    )
    if lab_runs:
        progress["lab_runs"] = lab_runs
    if terminal:
        _update_progress_totals(progress, lab_runs)
    run = {**run, "status": effective_status, "stale": stale}
    return {
        "run": run,
        "lab_runs": lab_runs,
        "progress": progress,
        "stale": stale,
        "effective_status": effective_status,
    }


def _run_limit(run: dict[str, Any], progress: dict[str, Any]) -> int | None:
    raw = run.get("limit_val") or progress.get("limit_val")
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def _enrich_lab_runs_from_eval_logs(
    lab_runs: list[dict[str, Any]],
    *,
    limit: int | None,
    count_samples: bool,
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for lab_run in lab_runs:
        row = dict(lab_run)
        lab_name = str(row.get("lab_name", "") or "")
        if not lab_name:
            enriched.append(row)
            continue

        eval_log = row.get("eval_log")
        eval_path = _resolve_eval_log_path(str(eval_log)) if eval_log else None
        if not eval_log and lab_name.startswith("custom_"):
            eval_path = phase1_progress.find_newest_eval_log(config.PHASE1_DIR, lab_name)
            if eval_path is not None:
                row["eval_log"] = str(eval_path)

        if count_samples and eval_path is not None and eval_path.is_file():
            done = row.get("samples_done")
            total = row.get("samples_total")
            if done in (None, 0) or total in (None, 0):
                try:
                    samples_done, samples_total = phase1_progress.count_samples(eval_path, limit)
                    row["samples_done"] = samples_done
                    row["samples_total"] = samples_total
                except Exception:
                    pass
        enriched.append(row)
    return enriched


def _update_progress_totals(progress: dict[str, Any], lab_runs: list[dict[str, Any]]) -> None:
    samples_done = 0
    samples_total = 0
    has_progress = False
    for lab_run in lab_runs:
        done = lab_run.get("samples_done")
        total = lab_run.get("samples_total")
        if done is not None:
            samples_done += int(done)
            has_progress = True
        if total is not None:
            samples_total += int(total)
            has_progress = True
    if has_progress:
        progress["samples_done"] = samples_done
        progress["samples_total"] = samples_total


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
    terminal = effective_status not in {"running", "stale"}
    lab_runs = progress.get("lab_runs") or payload["lab_runs"]
    lab_runs = _enrich_lab_runs_from_eval_logs(
        lab_runs,
        limit=_run_limit(run, progress),
        count_samples=terminal,
    )
    if lab_runs:
        progress["lab_runs"] = lab_runs
    if terminal:
        _update_progress_totals(progress, lab_runs)
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
        "lab_runs": lab_runs,
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
async def datasets_list(request: Request, upload_error: str = "") -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "datasets.html",
        {"datasets": datasets.list_datasets(), "upload_error": upload_error},
    )


@app.get("/datasets/import-jobs/{job_id}", response_class=HTMLResponse)
async def hf_import_job_page(request: Request, job_id: str) -> HTMLResponse:
    try:
        job = datasets.load_import_job(job_id)
    except datasets.DatasetError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    effective_status = datasets.resolve_import_job_status(job)
    return templates.TemplateResponse(
        request,
        "hf_import_job.html",
        {"job": job, "effective_status": effective_status},
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


def _htmx_error_response(request: Request, message: str) -> HTMLResponse:
    body = f'<p class="banner banner-warn">{html.escape(message)}</p>'
    # HTMX does not swap 4xx responses into the target by default.
    status = 200 if request.headers.get("HX-Request") else 400
    return HTMLResponse(body, status_code=status)


@app.post("/api/datasets/inspect-hf", response_model=None)
async def api_inspect_hf_dataset(
    request: Request,
    hf_url: str = Form(...),
    hf_config: str = Form(""),
    hf_split: str = Form(""),
):
    try:
        inspect_result = await asyncio.wait_for(
            asyncio.to_thread(
                datasets.inspect_hf_source,
                hf_url,
                hf_config.strip() or None,
                hf_split.strip() or None,
            ),
            timeout=120.0,
        )
    except asyncio.TimeoutError:
        return _htmx_error_response(
            request,
            "таймаут при обращении к Hugging Face (120 с). "
            "Укажите config явно (для piimb/privy: privy-small или privy-large).",
        )
    except datasets.DatasetError as exc:
        return _htmx_error_response(request, str(exc))
    return templates.TemplateResponse(
        request,
        "partials/dataset_upload_mapping.html",
        {"inspect": inspect_result},
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
        return _htmx_error_response(request, str(exc))
    return templates.TemplateResponse(
        request,
        "partials/dataset_upload_mapping.html",
        {"inspect": inspect_result},
    )


@app.post("/api/datasets")
async def api_create_dataset(
    source: str = Form("file"),
    upload_token: str = Form(""),
    hf_staging_token: str = Form(""),
    hf_repo_id: str = Form(""),
    hf_config: str = Form(""),
    hf_split: str = Form(""),
    hf_estimated_bytes: str = Form(""),
    title: str = Form(...),
    slug: str = Form(...),
    description: str = Form(""),
    map_input: str = Form(...),
    map_target: str = Form(""),
    map_metadata: str = Form(""),
) -> RedirectResponse:
    column_mapping: dict[str, str] = {"input": map_input.strip()}
    if map_target.strip():
        column_mapping["target"] = map_target.strip()

    if source == "huggingface":
        try:
            hf_meta = datasets.resolve_hf_import_meta(
                hf_staging_token=hf_staging_token,
                hf_repo_id=hf_repo_id,
                hf_config=hf_config,
                hf_split=hf_split,
                hf_estimated_bytes=hf_estimated_bytes,
            )
            estimated = hf_meta.get("estimated_bytes")
            staging_token = hf_staging_token.strip() or None
            if datasets.should_use_background_import(estimated, hf_hub=True):
                job_id = datasets.enqueue_hf_import_job(
                    hf_meta,
                    hf_staging_token=staging_token,
                    title=title,
                    description=description,
                    slug=slug,
                    column_mapping=column_mapping,
                    metadata_csv=map_metadata,
                )
                hf_runner.launch_hf_import(job_id)
            else:
                record = datasets.save_custom_dataset_from_hf_sync(
                    hf_meta,
                    hf_staging_token=staging_token,
                    title=title,
                    description=description,
                    slug=slug,
                    column_mapping=column_mapping,
                    metadata_csv=map_metadata,
                )
                return RedirectResponse(url=f"/datasets/{record.id}", status_code=303)
        except datasets.DatasetConflictError as exc:
            return RedirectResponse(
                url=f"/datasets?upload_error={quote(str(exc))}",
                status_code=303,
            )
        except (datasets.DatasetError, hf_runner.HfImportLaunchError) as exc:
            return RedirectResponse(
                url=f"/datasets?upload_error={quote(str(exc))}",
                status_code=303,
            )
        return RedirectResponse(url=f"/datasets/import-jobs/{job_id}", status_code=303)

    if not upload_token.strip():
        raise HTTPException(status_code=400, detail="upload_token is required")
    try:
        content, filename = datasets.consume_staged_upload(upload_token)
    except datasets.DatasetError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

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


@app.get("/api/datasets/import-jobs/{job_id}", response_model=None)
async def api_hf_import_job_status(request: Request, job_id: str):
    try:
        job = datasets.load_import_job(job_id)
    except datasets.DatasetError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    effective_status = datasets.resolve_import_job_status(job)
    ctx = {"job": job, "effective_status": effective_status}
    if request.headers.get("accept", "").startswith("application/json"):
        return JSONResponse({**job, "effective_status": effective_status})
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(
            request,
            "partials/hf_import_job_status.html",
            ctx,
        )
    return JSONResponse({**job, "effective_status": effective_status})


@app.get("/api/datasets/import-jobs/{job_id}/log")
async def api_hf_import_job_log(job_id: str) -> HTMLResponse:
    content = hf_runner.tail_import_log(job_id)
    if not content:
        try:
            job = datasets.load_import_job(job_id)
            log_path = job.get("screen_log")
            if log_path:
                content = runner.tail_file(Path(log_path))
        except datasets.DatasetError:
            content = ""
    if not content:
        content = "(log not available yet)"
    return HTMLResponse(f'<pre class="log-tail">{html.escape(content)}</pre>')


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
