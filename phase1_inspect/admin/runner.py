"""Launch Phase 1 orchestrator runs inside detached screen sessions."""

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

from admin.config import (
    LAUNCH_META_DIR,
    LOGS_DIR,
    PHASE1_DIR,
    valid_benchmark_keys,
)


@dataclass
class LaunchRequest:
    limit: int
    benchmarks: list[str] | None  # None = all benchmarks
    at_moscow: str | None
    screen_session: str
    target_model: str | None
    grader_model: str | None
    max_connections: int | None


@dataclass
class LaunchResult:
    screen_session: str
    screen_log: str | None
    orchestrator_args: list[str]
    meta_path: str


class LaunchError(Exception):
    pass


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sanitize_session(name: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_.-]", "_", name.strip())
    if not cleaned:
        raise LaunchError("screen session name is empty after sanitization")
    return cleaned[:64]


def default_session_name() -> str:
    return f"phase1_{int(time.time())}"


def validate_launch(req: LaunchRequest) -> None:
    if req.limit < 1:
        raise LaunchError("limit must be at least 1")
    if req.benchmarks is not None:
        if not req.benchmarks:
            raise LaunchError("select at least one benchmark")
        unknown = [k for k in req.benchmarks if k not in valid_benchmark_keys()]
        if unknown:
            raise LaunchError(f"unknown benchmark keys: {', '.join(unknown)}")
    if req.max_connections is not None and req.max_connections < 1:
        raise LaunchError("max_connections must be at least 1")
    req.screen_session = _sanitize_session(req.screen_session)


def screen_session_exists(name: str) -> bool:
    if not shutil.which("screen"):
        raise LaunchError("screen is not installed")
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


def resolve_run_status(run: dict[str, Any]) -> str:
    """Return running|stale|ok|failed|partial_fail for a run summary dict."""
    finished_at = run.get("finished_at")
    orchestrator_exit = run.get("orchestrator_exit")
    lab_count = run.get("lab_count", 0) or 0
    success_count = run.get("success_count", 0) or 0

    if finished_at is None:
        base = "running"
    elif orchestrator_exit == 0:
        base = "ok"
    elif success_count > 0:
        base = "partial_fail"
    else:
        base = "failed"

    if base == "running":
        alive = screen_session_alive(run.get("screen_session"))
        if alive is False:
            return "stale"
    if run.get("stale"):
        return "stale"
    return base


def build_orchestrator_args(req: LaunchRequest) -> list[str]:
    args = [str(req.limit)]
    if req.benchmarks is not None:
        args.extend(["--benchmarks", ",".join(req.benchmarks)])
    if req.at_moscow:
        args.extend(["-a", req.at_moscow])
    return args


def find_screen_log(session: str) -> Path | None:
    matches = sorted(LOGS_DIR.glob(f"phase1_screen_{session}_*.log"))
    return matches[-1] if matches else None


def save_launch_meta(session: str, payload: dict[str, Any]) -> Path:
    LAUNCH_META_DIR.mkdir(parents=True, exist_ok=True)
    path = LAUNCH_META_DIR / f"{session}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_launch_meta(session: str) -> dict[str, Any] | None:
    path = LAUNCH_META_DIR / f"{session}.json"
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if "benchmarks" not in data and "labs" in data:
        data["benchmarks"] = data["labs"]
    return data


def find_launch_meta_by_run_id(run_id: int) -> dict[str, Any] | None:
    if not LAUNCH_META_DIR.is_dir():
        return None
    for path in LAUNCH_META_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if data.get("run_id") == run_id:
            if "benchmarks" not in data and "labs" in data:
                data["benchmarks"] = data["labs"]
            return data
    return None


def tail_file(path: Path, max_lines: int = 200) -> str:
    if not path.is_file():
        return ""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(lines[-max_lines:])


def launch(req: LaunchRequest) -> LaunchResult:
    validate_launch(req)
    if screen_session_exists(req.screen_session):
        raise LaunchError(f"screen session already exists: {req.screen_session}")

    orch_args = build_orchestrator_args(req)
    screen_script = PHASE1_DIR / "run_phase1_in_screen.sh"
    if not screen_script.is_file():
        raise LaunchError(f"missing launcher script: {screen_script}")

    cmd = [str(screen_script), "-S", req.screen_session, *orch_args]

    env = os_environ_copy_with_overrides(req)
    result = subprocess.run(
        cmd,
        cwd=str(PHASE1_DIR),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise LaunchError(detail or "failed to start screen session")

    screen_log_path: Path | None = None
    for _ in range(20):
        screen_log_path = find_screen_log(req.screen_session)
        if screen_log_path is not None:
            break
        time.sleep(0.25)

    meta = {
        "screen_session": req.screen_session,
        "screen_log": str(screen_log_path) if screen_log_path else None,
        "started_at": _iso_now(),
        "limit": req.limit,
        "benchmarks": req.benchmarks,
        "at_moscow": req.at_moscow,
        "target_model": req.target_model,
        "grader_model": req.grader_model,
        "max_connections": req.max_connections,
        "orchestrator_args": orch_args,
        "run_id": None,
    }
    meta_path = save_launch_meta(req.screen_session, meta)

    return LaunchResult(
        screen_session=req.screen_session,
        screen_log=str(screen_log_path) if screen_log_path else None,
        orchestrator_args=orch_args,
        meta_path=str(meta_path),
    )


def os_environ_copy_with_overrides(req: LaunchRequest) -> dict[str, str]:
    import os

    env = os.environ.copy()
    if req.target_model:
        env["TARGET_MODEL"] = req.target_model
    if req.grader_model:
        env["GRADER_MODEL"] = req.grader_model
    if req.max_connections is not None:
        env["PHASE1_MAX_CONNECTIONS"] = str(req.max_connections)
    env["PHASE1_SCREEN_SESSION"] = req.screen_session
    return env


def build_metrics(run_id: int) -> Path:
    from admin.config import DEFAULT_LOG_DB, METRICS_DIR, PYTHON_BIN

    out_dir = METRICS_DIR / f"run_{run_id}"
    out_dir.mkdir(parents=True, exist_ok=True)
    python = str(PYTHON_BIN) if PYTHON_BIN.is_file() else "python3"
    metrics_script = PHASE1_DIR / "scripts" / "phase1_metrics.py"
    result = subprocess.run(
        [
            python,
            str(metrics_script),
            "--sqlite",
            str(DEFAULT_LOG_DB),
            "--run-id",
            str(run_id),
            "--base-dir",
            str(PHASE1_DIR),
            "--out-dir",
            str(out_dir),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "metrics generation failed")
    return out_dir / "report.html"


def attach_run_id_to_session(screen_session: str, run_id: int) -> None:
    meta = load_launch_meta(screen_session)
    if meta is None:
        return
    meta["run_id"] = run_id
    save_launch_meta(screen_session, meta)
