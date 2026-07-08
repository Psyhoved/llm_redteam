"""Launch Hugging Face dataset import jobs inside detached screen sessions."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from admin import datasets
from admin.config import LOGS_DIR, PHASE1_DIR


@dataclass
class HfImportLaunchResult:
    job_id: str
    screen_session: str
    screen_log: str | None


class HfImportLaunchError(Exception):
    pass


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sanitize_session(name: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_.-]", "_", name.strip())
    if not cleaned:
        raise HfImportLaunchError("screen session name is empty after sanitization")
    return cleaned[:64]


def default_hf_import_session(job_id: str) -> str:
    return _sanitize_session(f"hf_import_{job_id[:8]}")


def screen_session_exists(name: str) -> bool:
    if not shutil.which("screen"):
        raise HfImportLaunchError("screen is not installed")
    result = subprocess.run(
        ["screen", "-ls", name],
        capture_output=True,
        text=True,
        check=False,
    )
    combined = f"{result.stdout}\n{result.stderr}"
    return f".{name}\t" in combined or f".{name} (" in combined


def screen_session_alive(session: str | None) -> bool | None:
    if not session:
        return None
    if not shutil.which("screen"):
        return None
    return screen_session_exists(session)


def find_screen_log(session: str) -> Path | None:
    matches = sorted(LOGS_DIR.glob(f"hf_import_screen_{session}_*.log"))
    return matches[-1] if matches else None


def tail_import_log(job_id: str, max_lines: int = 200) -> str:
    path = datasets.IMPORT_JOBS_DIR / f"{job_id}.log"
    if not path.is_file():
        return ""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(lines[-max_lines:])


def launch_hf_import(job_id: str, screen_session: str | None = None) -> HfImportLaunchResult:
    job = datasets.load_import_job(job_id)
    session = _sanitize_session(screen_session or default_hf_import_session(job_id))
    if screen_session_exists(session):
        raise HfImportLaunchError(f"screen session already exists: {session}")

    screen_script = PHASE1_DIR / "run_hf_import_in_screen.sh"
    if not screen_script.is_file():
        raise HfImportLaunchError(f"missing launcher script: {screen_script}")

    cmd = [str(screen_script), "-S", session, "--", job_id]
    result = subprocess.run(
        cmd,
        cwd=str(PHASE1_DIR),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise HfImportLaunchError(detail or "failed to start screen session")

    screen_log_path: Path | None = None
    for _ in range(20):
        screen_log_path = find_screen_log(session)
        if screen_log_path is not None:
            break
        time.sleep(0.25)

    datasets.update_import_job(
        job_id,
        screen_session=session,
        screen_log=str(screen_log_path) if screen_log_path else None,
        status="downloading",
    )
    datasets.append_import_job_log(job_id, f"started screen session {session}")

    return HfImportLaunchResult(
        job_id=job_id,
        screen_session=session,
        screen_log=str(screen_log_path) if screen_log_path else None,
    )


def save_import_job_meta(job_id: str, payload: dict[str, Any]) -> Path:
    datasets.IMPORT_JOBS_DIR.mkdir(parents=True, exist_ok=True)
    path = datasets.IMPORT_JOBS_DIR / f"{job_id}.launch.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
