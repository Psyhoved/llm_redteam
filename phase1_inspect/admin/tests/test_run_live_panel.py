"""Tests for live run panel and samples API."""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from admin.app import app
from admin import config, db

client = TestClient(app)


def _any_run_id() -> int | None:
    runs = db.list_runs(limit=5)
    return runs[0]["id"] if runs else None


def test_live_panel_endpoint_returns_benchmark_section() -> None:
    run_id = _any_run_id()
    if run_id is None:
        pytest.skip("no runs in sqlite")
    r = client.get(f"/api/runs/{run_id}/live-panel", headers={"HX-Request": "true"})
    assert r.status_code == 200
    assert "Бенчмарки" in r.text
    assert "run-status-line" in r.text or "status-" in r.text


def test_live_panel_json() -> None:
    run_id = _any_run_id()
    if run_id is None:
        pytest.skip("no runs in sqlite")
    r = client.get(f"/api/runs/{run_id}/live-panel", headers={"Accept": "application/json"})
    assert r.status_code == 200
    data = r.json()
    assert "effective_status" in data
    assert "lab_runs" in data


def test_runs_table_partial() -> None:
    r = client.get("/api/runs/table", headers={"HX-Request": "true"})
    assert r.status_code == 200
    assert "<tr>" in r.text


def test_samples_live_endpoint() -> None:
    run_id = _any_run_id()
    if run_id is None:
        pytest.skip("no runs in sqlite")
    r = client.get(f"/api/runs/{run_id}/samples-live", headers={"HX-Request": "true"})
    assert r.status_code == 200


def test_run_detail_has_live_panel_htmx() -> None:
    run_id = _any_run_id()
    if run_id is None:
        pytest.skip("no runs in sqlite")
    r = client.get(f"/runs/{run_id}")
    assert r.status_code == 200
    assert 'id="run-live-panel"' in r.text
    assert 'hx-get="/api/runs/' in r.text
    assert "samples-live" in r.text
    assert "Inspect Live" in r.text


def test_phase1_live_samples_on_eval_file() -> None:
    import json
    import subprocess

    logs = list((config.PHASE1_DIR / "logs").glob("*.eval"))
    if not logs:
        pytest.skip("no .eval files")
    eval_path = logs[0]
    python = str(config.PYTHON_BIN) if config.PYTHON_BIN.is_file() else "python3"
    script = config.PHASE1_DIR / "scripts" / "phase1_live_samples.py"
    result = subprocess.run(
        [python, str(script), "--eval-log", str(eval_path), "--limit", "3"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert "samples" in data
