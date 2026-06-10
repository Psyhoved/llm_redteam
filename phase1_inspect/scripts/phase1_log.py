#!/usr/bin/env python3
"""Minimal SQLite logging for phase1_inspect full-run orchestrator (MVP)."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS runs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          started_at TEXT NOT NULL,
          finished_at TEXT,
          hostname TEXT,
          limit_val INTEGER NOT NULL,
          at_moscow TEXT,
          sleep_before_sec INTEGER,
          argv TEXT,
          orchestrator_exit INTEGER,
          screen_session TEXT
        );
        CREATE TABLE IF NOT EXISTS lab_runs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          run_id INTEGER NOT NULL,
          lab_name TEXT NOT NULL,
          started_at TEXT NOT NULL,
          finished_at TEXT NOT NULL,
          exit_code INTEGER NOT NULL,
          raw_exit_code INTEGER,
          status TEXT,
          reason TEXT,
          eval_log TEXT,
          stdout TEXT NOT NULL,
          stderr TEXT NOT NULL,
          FOREIGN KEY(run_id) REFERENCES runs(id)
        );
        CREATE INDEX IF NOT EXISTS idx_lab_runs_run_id ON lab_runs(run_id);
        """
    )
    ensure_lab_run_columns(conn)


def ensure_lab_run_columns(conn: sqlite3.Connection) -> None:
    existing = {row[1] for row in conn.execute("PRAGMA table_info(lab_runs)")}
    columns = {
        "raw_exit_code": "INTEGER",
        "status": "TEXT",
        "reason": "TEXT",
        "eval_log": "TEXT",
        "samples_done": "INTEGER",
        "samples_total": "INTEGER",
    }
    for name, sql_type in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE lab_runs ADD COLUMN {name} {sql_type}")


def lab_run_row_dict(row: tuple) -> dict:
    return {
        "lab_name": row[0],
        "started_at": row[1],
        "finished_at": row[2],
        "exit_code": row[3],
        "raw_exit_code": row[4],
        "status": row[5],
        "reason": row[6],
        "eval_log": row[7],
        "samples_done": row[8],
        "samples_total": row[9],
    }


def is_lab_running(exit_code: int | None, status: str | None) -> bool:
    return exit_code == -1 or status == "running"


def screen_session_alive(session: str | None) -> bool | None:
    if not session:
        return None
    import shutil
    import subprocess

    if not shutil.which("screen"):
        return None
    result = subprocess.run(
        ["screen", "-ls", session],
        capture_output=True,
        text=True,
        check=False,
    )
    combined = f"{result.stdout}\n{result.stderr}"
    return f".{session}\t" in combined or f".{session} (" in combined


def cmd_start_run(args: argparse.Namespace) -> None:
    conn = connect(Path(args.db))
    ensure_schema(conn)
    at_msk = args.at_moscow if args.at_moscow else None
    sleep_sec = args.sleep_before_sec if args.sleep_before_sec is not None else None
    scr = args.screen_session if args.screen_session else None
    argv_s = args.argv_json if args.argv_json else "[]"
    try:
        json.loads(argv_s)
    except json.JSONDecodeError as e:
        print(f"Error: argv-json is not valid JSON: {e}", file=sys.stderr)
        sys.exit(1)
    cur = conn.execute(
        """
        INSERT INTO runs (
          started_at, hostname, limit_val, at_moscow, sleep_before_sec,
          argv, screen_session
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            iso_now(),
            args.hostname,
            args.limit_val,
            at_msk,
            sleep_sec,
            argv_s,
            scr,
        ),
    )
    conn.commit()
    print(cur.lastrowid)
    conn.close()


def cmd_finish_run(args: argparse.Namespace) -> None:
    conn = connect(Path(args.db))
    ensure_schema(conn)
    conn.execute(
        "UPDATE runs SET finished_at = ?, orchestrator_exit = ? WHERE id = ?",
        (iso_now(), args.exit_code, args.run_id),
    )
    conn.commit()
    conn.close()


def run_status_label(
    finished_at: str | None, orchestrator_exit: int | None, lab_count: int, success_count: int
) -> str:
    if finished_at is None:
        return "running"
    if orchestrator_exit == 0:
        return "ok"
    if success_count > 0:
        return "partial_fail"
    return "failed"


def cmd_list_runs(args: argparse.Namespace) -> None:
    conn = connect(Path(args.db))
    ensure_schema(conn)
    limit = args.limit if args.limit is not None else 50
    rows = conn.execute(
        """
        SELECT
          r.id,
          r.started_at,
          r.finished_at,
          r.limit_val,
          r.orchestrator_exit,
          r.screen_session,
          r.hostname,
          r.at_moscow,
          COUNT(l.id) AS lab_count,
          SUM(CASE WHEN l.exit_code = 0 THEN 1 ELSE 0 END) AS success_count
        FROM runs r
        LEFT JOIN lab_runs l ON l.run_id = r.id
        GROUP BY r.id
        ORDER BY r.id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    payload = []
    for row in rows:
        (
            run_id,
            started_at,
            finished_at,
            limit_val,
            orchestrator_exit,
            screen_session,
            hostname,
            at_moscow,
            lab_count,
            success_count,
        ) = row
        status = run_status_label(
            finished_at, orchestrator_exit, lab_count or 0, success_count or 0
        )
        progress_rows = conn.execute(
            """
            SELECT samples_done, samples_total
            FROM lab_runs WHERE run_id = ?
            """,
            (run_id,),
        ).fetchall()
        samples_done = 0
        samples_total = 0
        has_progress = False
        for done, total in progress_rows:
            if done is not None:
                samples_done += done
                has_progress = True
            if total is not None:
                samples_total += total
                has_progress = True
        current_row = conn.execute(
            """
            SELECT lab_name FROM lab_runs
            WHERE run_id = ? AND (exit_code = -1 OR status = 'running')
            ORDER BY id DESC LIMIT 1
            """,
            (run_id,),
        ).fetchone()
        current_benchmark = current_row[0] if current_row else None
        stale = False
        if status == "running" and screen_session:
            alive = screen_session_alive(screen_session)
            if alive is False:
                stale = True
        effective_status = "stale" if stale else status
        payload.append(
            {
                "id": run_id,
                "started_at": started_at,
                "finished_at": finished_at,
                "limit_val": limit_val,
                "orchestrator_exit": orchestrator_exit,
                "screen_session": screen_session,
                "hostname": hostname,
                "at_moscow": at_moscow,
                "lab_count": lab_count or 0,
                "success_count": success_count or 0,
                "status": effective_status,
                "samples_done": samples_done if has_progress else None,
                "samples_total": samples_total if has_progress else None,
                "current_benchmark": current_benchmark,
                "stale": stale,
            }
        )
    conn.close()
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def cmd_get_run(args: argparse.Namespace) -> None:
    conn = connect(Path(args.db))
    ensure_schema(conn)
    row = conn.execute(
        """
        SELECT
          id, started_at, finished_at, hostname, limit_val, at_moscow,
          sleep_before_sec, argv, orchestrator_exit, screen_session
        FROM runs WHERE id = ?
        """,
        (args.run_id,),
    ).fetchone()
    if row is None:
        print(json.dumps({"error": f"run_id {args.run_id} not found"}), file=sys.stderr)
        conn.close()
        sys.exit(1)

    (
        run_id,
        started_at,
        finished_at,
        hostname,
        limit_val,
        at_moscow,
        sleep_before_sec,
        argv,
        orchestrator_exit,
        screen_session,
    ) = row

    lab_rows = conn.execute(
        """
        SELECT
          lab_name, started_at, finished_at, exit_code, raw_exit_code,
          status, reason, eval_log, samples_done, samples_total
        FROM lab_runs
        WHERE run_id = ?
        ORDER BY id
        """,
        (run_id,),
    ).fetchall()
    conn.close()

    lab_runs = [lab_run_row_dict(lr) for lr in lab_rows]
    success_count = sum(1 for lr in lab_runs if lr["exit_code"] == 0)
    payload = {
        "run": {
            "id": run_id,
            "started_at": started_at,
            "finished_at": finished_at,
            "hostname": hostname,
            "limit_val": limit_val,
            "at_moscow": at_moscow,
            "sleep_before_sec": sleep_before_sec,
            "argv": json.loads(argv) if argv else [],
            "orchestrator_exit": orchestrator_exit,
            "screen_session": screen_session,
            "lab_count": len(lab_runs),
            "success_count": success_count,
            "status": run_status_label(
                finished_at, orchestrator_exit, len(lab_runs), success_count
            ),
        },
        "lab_runs": lab_runs,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def cmd_find_run_by_session(args: argparse.Namespace) -> None:
    conn = connect(Path(args.db))
    ensure_schema(conn)
    row = conn.execute(
        """
        SELECT id FROM runs
        WHERE screen_session = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (args.screen_session,),
    ).fetchone()
    conn.close()
    if row is None:
        print("")
    else:
        print(row[0])


def cmd_start_benchmark(args: argparse.Namespace) -> None:
    conn = connect(Path(args.db))
    ensure_schema(conn)
    started = iso_now()
    conn.execute(
        """
        INSERT INTO lab_runs (
          run_id, lab_name, started_at, finished_at, exit_code,
          raw_exit_code, status, reason, eval_log, stdout, stderr,
          samples_done, samples_total
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            args.run_id,
            args.lab_name,
            started,
            started,
            -1,
            None,
            "running",
            None,
            None,
            "",
            "",
            0,
            args.samples_total if args.samples_total is not None else None,
        ),
    )
    conn.commit()
    conn.close()


def cmd_update_benchmark_progress(args: argparse.Namespace) -> None:
    conn = connect(Path(args.db))
    ensure_schema(conn)
    row = conn.execute(
        """
        SELECT id FROM lab_runs
        WHERE run_id = ? AND lab_name = ?
          AND (exit_code = -1 OR status = 'running')
        ORDER BY id DESC
        LIMIT 1
        """,
        (args.run_id, args.lab_name),
    ).fetchone()
    if row is None:
        conn.close()
        print(json.dumps({"error": "no running benchmark row found"}), file=sys.stderr)
        sys.exit(1)
    conn.execute(
        """
        UPDATE lab_runs
        SET samples_done = ?, samples_total = ?
        WHERE id = ?
        """,
        (args.samples_done, args.samples_total, row[0]),
    )
    conn.commit()
    conn.close()


def cmd_finish_benchmark(args: argparse.Namespace) -> None:
    conn = connect(Path(args.db))
    ensure_schema(conn)
    stdout = Path(args.stdout_file).read_text(encoding="utf-8", errors="replace")
    stderr = Path(args.stderr_file).read_text(encoding="utf-8", errors="replace")
    row = conn.execute(
        """
        SELECT id FROM lab_runs
        WHERE run_id = ? AND lab_name = ?
          AND (exit_code = -1 OR status = 'running')
        ORDER BY id DESC
        LIMIT 1
        """,
        (args.run_id, args.lab_name),
    ).fetchone()
    if row is None:
        conn.close()
        print(json.dumps({"error": "no running benchmark row found"}), file=sys.stderr)
        sys.exit(1)
    conn.execute(
        """
        UPDATE lab_runs
        SET finished_at = ?, exit_code = ?, raw_exit_code = ?,
            status = ?, reason = ?, eval_log = ?,
            stdout = ?, stderr = ?,
            samples_done = COALESCE(?, samples_done),
            samples_total = COALESCE(?, samples_total)
        WHERE id = ?
        """,
        (
            args.finished_at,
            args.exit_code,
            args.raw_exit_code,
            args.status or None,
            args.reason or None,
            args.eval_log or None,
            stdout,
            stderr,
            args.samples_done,
            args.samples_total,
            row[0],
        ),
    )
    conn.commit()
    conn.close()


def cmd_get_run_progress(args: argparse.Namespace) -> None:
    conn = connect(Path(args.db))
    ensure_schema(conn)
    row = conn.execute(
        """
        SELECT
          id, started_at, finished_at, orchestrator_exit, screen_session, limit_val
        FROM runs WHERE id = ?
        """,
        (args.run_id,),
    ).fetchone()
    if row is None:
        conn.close()
        print(json.dumps({"error": f"run_id {args.run_id} not found"}), file=sys.stderr)
        sys.exit(1)

    (
        run_id,
        started_at,
        finished_at,
        orchestrator_exit,
        screen_session,
        limit_val,
    ) = row

    lab_rows = conn.execute(
        """
        SELECT
          lab_name, started_at, finished_at, exit_code, raw_exit_code,
          status, reason, eval_log, samples_done, samples_total
        FROM lab_runs
        WHERE run_id = ?
        ORDER BY id
        """,
        (run_id,),
    ).fetchall()
    conn.close()

    lab_runs = [lab_run_row_dict(lr) for lr in lab_rows]
    success_count = sum(1 for lr in lab_runs if lr["exit_code"] == 0)
    base_status = run_status_label(
        finished_at, orchestrator_exit, len(lab_runs), success_count
    )

    current_benchmark = None
    for lr in reversed(lab_runs):
        if is_lab_running(lr["exit_code"], lr["status"]):
            current_benchmark = lr["lab_name"]
            break

    samples_done = 0
    samples_total = 0
    has_progress = False
    for lr in lab_runs:
        done = lr["samples_done"]
        total = lr["samples_total"]
        if done is not None:
            samples_done += done
            has_progress = True
        if total is not None:
            samples_total += total
            has_progress = True

    stale = False
    if base_status == "running" and screen_session:
        alive = screen_session_alive(screen_session)
        if alive is False:
            stale = True

    effective_status = "stale" if stale else base_status

    payload = {
        "run_id": run_id,
        "status": effective_status,
        "base_status": base_status,
        "stale": stale,
        "current_benchmark": current_benchmark,
        "samples_done": samples_done if has_progress else None,
        "samples_total": samples_total if has_progress else None,
        "lab_runs": lab_runs,
        "screen_session": screen_session,
        "screen_alive": screen_session_alive(screen_session),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def cmd_insert_lab(args: argparse.Namespace) -> None:
    conn = connect(Path(args.db))
    ensure_schema(conn)
    stdout = Path(args.stdout_file).read_text(encoding="utf-8", errors="replace")
    stderr = Path(args.stderr_file).read_text(encoding="utf-8", errors="replace")
    conn.execute(
        """
        INSERT INTO lab_runs (
          run_id, lab_name, started_at, finished_at, exit_code,
          raw_exit_code, status, reason, eval_log, stdout, stderr
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            args.run_id,
            args.lab_name,
            args.started_at,
            args.finished_at,
            args.exit_code,
            args.raw_exit_code,
            args.status or None,
            args.reason or None,
            args.eval_log or None,
            stdout,
            stderr,
        ),
    )
    conn.commit()
    conn.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_start = sub.add_parser("start-run", help="Insert runs row; print run id to stdout")
    p_start.add_argument("--db", required=True)
    p_start.add_argument("--hostname", required=True)
    p_start.add_argument("--limit-val", type=int, required=True)
    p_start.add_argument("--at-moscow", default="")
    p_start.add_argument("--sleep-before-sec", type=int, default=None)
    p_start.add_argument("--argv-json", default="[]")
    p_start.add_argument("--screen-session", default="")
    p_start.set_defaults(func=cmd_start_run)

    p_fin = sub.add_parser("finish-run", help="Set finished_at and orchestrator_exit")
    p_fin.add_argument("--db", required=True)
    p_fin.add_argument("--run-id", type=int, required=True)
    p_fin.add_argument("--exit-code", type=int, required=True)
    p_fin.set_defaults(func=cmd_finish_run)

    p_lab = sub.add_parser("insert-lab", help="Append one lab stdout/stderr block")
    p_lab.add_argument("--db", required=True)
    p_lab.add_argument("--run-id", type=int, required=True)
    p_lab.add_argument("--lab-name", required=True)
    p_lab.add_argument("--started-at", required=True)
    p_lab.add_argument("--finished-at", required=True)
    p_lab.add_argument("--exit-code", type=int, required=True)
    p_lab.add_argument("--raw-exit-code", type=int, default=None)
    p_lab.add_argument("--status", default="")
    p_lab.add_argument("--reason", default="")
    p_lab.add_argument("--eval-log", default="")
    p_lab.add_argument("--stdout-file", required=True)
    p_lab.add_argument("--stderr-file", required=True)
    p_lab.set_defaults(func=cmd_insert_lab)

    p_list = sub.add_parser("list-runs", help="List runs as JSON")
    p_list.add_argument("--db", required=True)
    p_list.add_argument("--limit", type=int, default=50)
    p_list.set_defaults(func=cmd_list_runs)

    p_get = sub.add_parser("get-run", help="Get one run with lab_runs as JSON")
    p_get.add_argument("--db", required=True)
    p_get.add_argument("--run-id", type=int, required=True)
    p_get.set_defaults(func=cmd_get_run)

    p_find = sub.add_parser(
        "find-run-by-session", help="Print run id for screen_session or empty"
    )
    p_find.add_argument("--db", required=True)
    p_find.add_argument("--screen-session", required=True)
    p_find.set_defaults(func=cmd_find_run_by_session)

    p_start_bench = sub.add_parser(
        "start-benchmark", help="Insert in-progress lab_runs row"
    )
    p_start_bench.add_argument("--db", required=True)
    p_start_bench.add_argument("--run-id", type=int, required=True)
    p_start_bench.add_argument("--lab-name", required=True)
    p_start_bench.add_argument("--samples-total", type=int, default=None)
    p_start_bench.set_defaults(func=cmd_start_benchmark)

    p_upd_bench = sub.add_parser(
        "update-benchmark-progress", help="Update samples_done/total for running benchmark"
    )
    p_upd_bench.add_argument("--db", required=True)
    p_upd_bench.add_argument("--run-id", type=int, required=True)
    p_upd_bench.add_argument("--lab-name", required=True)
    p_upd_bench.add_argument("--samples-done", type=int, required=True)
    p_upd_bench.add_argument("--samples-total", type=int, required=True)
    p_upd_bench.set_defaults(func=cmd_update_benchmark_progress)

    p_fin_bench = sub.add_parser(
        "finish-benchmark", help="Finalize running benchmark row"
    )
    p_fin_bench.add_argument("--db", required=True)
    p_fin_bench.add_argument("--run-id", type=int, required=True)
    p_fin_bench.add_argument("--lab-name", required=True)
    p_fin_bench.add_argument("--started-at", required=True)
    p_fin_bench.add_argument("--finished-at", required=True)
    p_fin_bench.add_argument("--exit-code", type=int, required=True)
    p_fin_bench.add_argument("--raw-exit-code", type=int, default=None)
    p_fin_bench.add_argument("--status", default="")
    p_fin_bench.add_argument("--reason", default="")
    p_fin_bench.add_argument("--eval-log", default="")
    p_fin_bench.add_argument("--stdout-file", required=True)
    p_fin_bench.add_argument("--stderr-file", required=True)
    p_fin_bench.add_argument("--samples-done", type=int, default=None)
    p_fin_bench.add_argument("--samples-total", type=int, default=None)
    p_fin_bench.set_defaults(func=cmd_finish_benchmark)

    p_progress = sub.add_parser(
        "get-run-progress", help="Run progress JSON (stale if screen dead)"
    )
    p_progress.add_argument("--db", required=True)
    p_progress.add_argument("--run-id", type=int, required=True)
    p_progress.set_defaults(func=cmd_get_run_progress)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
