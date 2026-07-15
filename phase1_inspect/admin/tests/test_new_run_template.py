"""Template/API tests for new-run form (no browser required)."""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

from admin import config
from admin.app import app

client = TestClient(app)


def test_new_run_renders_benchmark_checkboxes() -> None:
    html = client.get("/").text
    checkbox_values = re.findall(r'name="benchmarks" value="([^"]+)"', html)
    expected_keys = [bench.key for bench in config.all_benchmarks()]
    assert checkbox_values == expected_keys


def test_new_run_has_benchmark_picker_markup() -> None:
    html = client.get("/").text
    assert 'id="benchmark-picker"' in html
    assert "XSTest" in html
    assert "syncBenchmarkPicker" in html
