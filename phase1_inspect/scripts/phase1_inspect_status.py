#!/usr/bin/env python3
"""Determine whether an Inspect AI lab run really succeeded.

Inspect can print a traceback and still return process exit code 0 for some
interrupted evals. This helper treats the Inspect eval log status as the source
of truth when a log is available, and falls back to stderr/stdout heuristics.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


FAIL_TOKENS = (
    "Traceback (most recent call last)",
    "Task interrupted",
    "ExceptionGroup:",
    "TypeError:",
    "NotFoundError:",
    "APIStatusError:",
)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def find_eval_log(text: str, base_dir: Path, lab_name: str = "") -> Path | None:
    matches = re.findall(r"Log:\s+([^\s]+\.eval)", text)
    if matches:
        raw = matches[-1]
        path = Path(raw)
        if not path.is_absolute():
            path = base_dir / path
        return path

    if lab_name:
        try:
            try:
                from scripts.phase1_progress import find_newest_eval_log
            except ModuleNotFoundError:
                from phase1_progress import find_newest_eval_log

            return find_newest_eval_log(base_dir, lab_name)
        except Exception:  # noqa: BLE001 - status reporting must stay best-effort
            return None
    return None


def inspect_log_status(eval_log: Path) -> tuple[str | None, str | None]:
    try:
        from inspect_ai.log import read_eval_log

        log = read_eval_log(str(eval_log))
        status = getattr(log, "status", None)
        error = getattr(log, "error", None)
        message = getattr(error, "message", None) if error is not None else None
        if message is None and error is not None:
            message = str(error)
        return str(status) if status is not None else None, message
    except Exception as ex:  # noqa: BLE001 - status reporting must not crash caller
        return None, f"could not read eval log: {type(ex).__name__}: {ex}"


def write_metadata(path: Path, metadata: dict[str, Any]) -> None:
    path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lab-name", required=True)
    parser.add_argument("--stdout-file", required=True)
    parser.add_argument("--stderr-file", required=True)
    parser.add_argument("--raw-exit-code", type=int, required=True)
    parser.add_argument("--base-dir", required=True)
    parser.add_argument("--metadata-file", required=True)
    args = parser.parse_args()

    stdout = read_text(Path(args.stdout_file))
    stderr = read_text(Path(args.stderr_file))
    combined = f"{stdout}\n{stderr}"
    base_dir = Path(args.base_dir)

    eval_log = find_eval_log(combined, base_dir, lab_name=args.lab_name)
    eval_log_s = str(eval_log) if eval_log is not None else ""
    status: str | None = None
    error_message: str | None = None
    reason = ""
    effective_exit_code = 0

    if args.raw_exit_code != 0:
        effective_exit_code = args.raw_exit_code
        reason = f"process exited with code {args.raw_exit_code}"

    if eval_log is not None:
        if eval_log.exists():
            status, error_message = inspect_log_status(eval_log)
            if status != "success":
                effective_exit_code = 1
                status_part = status or "unknown"
                msg_part = f": {error_message}" if error_message else ""
                reason = f"Inspect status={status_part}{msg_part}"
        else:
            effective_exit_code = 1
            reason = f"Inspect eval log not found: {eval_log}"
    elif args.raw_exit_code == 0:
        token = next((token for token in FAIL_TOKENS if token in combined), None)
        if token:
            effective_exit_code = 1
            reason = f"output contains failure marker: {token}"

    if not reason:
        reason = "success"

    metadata = {
        "lab_name": args.lab_name,
        "raw_exit_code": args.raw_exit_code,
        "effective_exit_code": effective_exit_code,
        "status": status or "",
        "reason": reason,
        "eval_log": eval_log_s,
        "error_message": error_message or "",
    }
    write_metadata(Path(args.metadata_file), metadata)

    if effective_exit_code != 0:
        print(reason, file=sys.stderr)
    sys.exit(0 if effective_exit_code == 0 else 1)


if __name__ == "__main__":
    main()
