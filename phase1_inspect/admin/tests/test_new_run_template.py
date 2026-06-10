"""Template/API tests for new-run form (no browser required)."""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

from admin.app import app

client = TestClient(app)


def test_new_run_renders_benchmark_checkboxes() -> None:
    html = client.get("/").text
    checkboxes = re.findall(r'name="benchmarks"', html)
    assert len(checkboxes) == 10, f"expected 10 benchmark checkboxes, got {len(checkboxes)}"


def test_new_run_has_benchmark_picker_markup() -> None:
    html = client.get("/").text
    assert 'id="benchmark-picker"' in html
    assert "XSTest" in html
    assert "syncBenchmarkPicker" in html
