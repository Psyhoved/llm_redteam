"""Playwright UI tests for Phase 1 admin (optional; needs browser deps)."""

from __future__ import annotations

import subprocess
import time

import pytest
from playwright.sync_api import Page, expect

BASE_URL = "http://127.0.0.1:8080"


def _browser_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            browser.close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _browser_available(),
    reason="Chromium not available (run: playwright install chromium && playwright install-deps)",
)


@pytest.fixture(scope="module")
def admin_server():
    """Use existing admin on :8080 or start a temporary one."""
    import socket
    from pathlib import Path

    phase1_dir = Path(__file__).resolve().parents[2]

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        if sock.connect_ex(("127.0.0.1", 8080)) == 0:
            yield
            return

    proc = subprocess.Popen(
        [
            "python",
            "-m",
            "uvicorn",
            "admin.app:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8080",
            "--app-dir",
            str(phase1_dir),
        ],
        cwd=str(phase1_dir),
    )
    for _ in range(40):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            if sock.connect_ex(("127.0.0.1", 8080)) == 0:
                break
        time.sleep(0.25)
    else:
        proc.kill()
        raise RuntimeError("admin server failed to start for Playwright tests")

    yield
    proc.terminate()
    proc.wait(timeout=10)


def test_benchmark_picker_hidden_by_default(page: Page, admin_server) -> None:
    page.goto(f"{BASE_URL}/")
    picker = page.locator("#benchmark-picker")
    expect(picker).to_be_hidden()
    expect(page.locator('#benchmark-picker input[name="benchmarks"]')).to_have_count(10)


def test_benchmark_picker_shows_on_selected_mode(page: Page, admin_server) -> None:
    page.goto(f"{BASE_URL}/")
    page.get_by_label("Выбранные бенчмарки").check()
    picker = page.locator("#benchmark-picker")
    expect(picker).to_be_visible()
    expect(page.locator('#benchmark-picker input[name="benchmarks"]')).to_have_count(10)
    expect(page.get_by_text("XSTest")).to_be_visible()
