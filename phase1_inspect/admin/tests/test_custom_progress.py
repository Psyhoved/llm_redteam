"""Regression tests for custom benchmark progress lookup."""

from __future__ import annotations

from pathlib import Path

import admin.app as app_module
from scripts.phase1_inspect_status import find_eval_log
from scripts.phase1_progress import eval_name_candidates, find_newest_eval_log


def test_custom_eval_name_candidates_include_inspect_hyphenated_task_name() -> None:
    assert "custom-privy-test-small" in eval_name_candidates("custom_privy-test-small")


def test_find_newest_eval_log_matches_hyphenated_custom_log_name(tmp_path: Path) -> None:
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    expected = logs_dir / "2026-07-08T15-04-44_custom-privy-test-small_abc.eval"
    expected.write_text("placeholder", encoding="utf-8")

    assert find_newest_eval_log(tmp_path, "custom_privy-test-small") == expected


def test_find_eval_log_falls_back_to_newest_log_when_display_path_is_truncated(
    tmp_path: Path,
) -> None:
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    expected = logs_dir / "2026-07-08T15-04-44_custom-privy-test-small_abc.eval"
    expected.write_text("placeholder", encoding="utf-8")
    truncated_stdout = "Log:\nlogs/2026-07-08T15-04-44_custom-privy-test-small_abc.e…"

    assert find_eval_log(
        truncated_stdout,
        tmp_path,
        lab_name="custom_privy-test-small",
    ) == expected


def test_live_panel_context_recovers_missing_finished_custom_eval_log(
    monkeypatch,
    tmp_path: Path,
) -> None:
    eval_log = tmp_path / "logs" / "2026_custom-privy-test-small_abc.eval"
    eval_log.parent.mkdir()
    eval_log.write_text("placeholder", encoding="utf-8")
    lab_run = {
        "lab_name": "custom_privy-test-small",
        "started_at": "2026-07-08T15:04:38+00:00",
        "finished_at": "2026-07-08T15:05:01+00:00",
        "exit_code": 0,
        "raw_exit_code": 0,
        "status": None,
        "reason": "success",
        "eval_log": None,
        "samples_done": 0,
        "samples_total": 1,
    }
    run = {
        "id": 101,
        "finished_at": "2026-07-08T15:05:01+00:00",
        "orchestrator_exit": 0,
        "success_count": 1,
        "lab_count": 1,
        "limit_val": 1,
        "screen_session": "phase1_1783523064",
    }
    monkeypatch.setattr(
        app_module.db,
        "get_run",
        lambda run_id: {"run": {**run, "id": run_id}, "lab_runs": [lab_run]},
    )
    monkeypatch.setattr(
        app_module.db,
        "get_run_progress",
        lambda run_id: {
            "run_id": run_id,
            "status": "ok",
            "base_status": "ok",
            "current_benchmark": None,
            "samples_done": 0,
            "samples_total": 1,
            "lab_runs": [lab_run],
        },
    )
    monkeypatch.setattr(
        app_module.phase1_progress,
        "find_newest_eval_log",
        lambda _base_dir, _lab_name: eval_log,
    )
    monkeypatch.setattr(
        app_module.phase1_progress,
        "count_samples",
        lambda _eval_log, _limit: (1, 1),
    )

    ctx = app_module._live_panel_context(101)

    assert ctx["progress"]["samples_done"] == 1
    assert ctx["progress"]["samples_total"] == 1
    assert ctx["lab_runs"][0]["eval_log"] == str(eval_log)
