"""SQLite run log access via phase1_log.py CLI."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from admin.config import DEFAULT_LOG_DB, PYTHON_BIN


def _python() -> str:
    if PYTHON_BIN.is_file():
        return str(PYTHON_BIN)
    return "python3"


def _log_script() -> Path:
    return Path(__file__).resolve().parent.parent / "scripts" / "phase1_log.py"


def _run_cli(*args: str, db: Path | None = None) -> str:
    db_path = db or DEFAULT_LOG_DB
    cmd = [_python(), str(_log_script()), *args, "--db", str(db_path)]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "phase1_log failed")
    return result.stdout


def list_runs(limit: int = 50, db: Path | None = None) -> list[dict[str, Any]]:
    out = _run_cli("list-runs", "--limit", str(limit), db=db)
    return json.loads(out)


def get_run(run_id: int, db: Path | None = None) -> dict[str, Any]:
    out = _run_cli("get-run", "--run-id", str(run_id), db=db)
    return json.loads(out)


def find_run_by_session(screen_session: str, db: Path | None = None) -> int | None:
    out = _run_cli(
        "find-run-by-session",
        "--screen-session",
        screen_session,
        db=db,
    ).strip()
    return int(out) if out else None


def get_run_progress(run_id: int, db: Path | None = None) -> dict[str, Any]:
    out = _run_cli("get-run-progress", "--run-id", str(run_id), db=db)
    return json.loads(out)
