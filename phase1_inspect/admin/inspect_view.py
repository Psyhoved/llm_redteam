"""Inspect AI View health check and dashboard URLs."""

from __future__ import annotations

import socket
import urllib.error
import urllib.request
from pathlib import Path

from admin.config import INSPECT_VIEW_PORT, INSPECT_VIEW_URL, PHASE1_DIR


def is_inspect_view_running(timeout: float = 1.0) -> bool:
    """Return True if Inspect View responds on the configured URL."""
    base = INSPECT_VIEW_URL.rstrip("/")
    try:
        req = urllib.request.Request(f"{base}/api/log-files", method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except (urllib.error.URLError, TimeoutError, ValueError):
        pass

    host = "127.0.0.1"
    port = INSPECT_VIEW_PORT
    if "://" in base:
        from urllib.parse import urlparse

        parsed = urlparse(base)
        host = parsed.hostname or host
        port = parsed.port or port
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def inspect_dashboard_url(eval_log: str | None = None) -> str:
    """Build URL to open Inspect View (optionally hint log path in hash)."""
    base = INSPECT_VIEW_URL.rstrip("/")
    if not eval_log:
        return base

    log_path = Path(eval_log)
    try:
        rel = log_path.resolve().relative_to(PHASE1_DIR.resolve())
        segment = rel.as_posix()
    except ValueError:
        segment = log_path.name

    return f"{base}/#/logs/{segment}"


def start_command() -> str:
    return (
        f"cd {PHASE1_DIR} && source .venv/bin/activate && "
        f"python -m inspect_ai view start --host 0.0.0.0 --port {INSPECT_VIEW_PORT} "
        f"--log-dir . --recursive"
    )
