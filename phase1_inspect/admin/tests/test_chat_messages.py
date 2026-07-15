"""Tests for extracting Inspect AI chat messages."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import csv
from fastapi.testclient import TestClient

import admin.app as app_module
import inspect_ai.log as inspect_log
from scripts.phase1_live_samples import collect_samples
from scripts.phase1_chat_messages import (
    build_chat_id,
    collect_chat_messages,
    extract_sample_messages,
)
from scripts.phase1_metrics import SampleRecord, write_samples_csv

client = TestClient(app_module.app)


def test_build_chat_id_uses_run_and_lab() -> None:
    assert build_chat_id(95, "advbench") == "run:95:lab:advbench"


def test_extract_sample_messages_uses_sample_uuid_and_model_event_indexes() -> None:
    sample = SimpleNamespace(
        id=42,
        epoch=1,
        uuid="sample-uuid",
        events=[
            SimpleNamespace(event="score", value=1),
            SimpleNamespace(
                event="model",
                model="openrouter/test-model",
                role="grader",
                input=[
                    SimpleNamespace(role="user", content="Is this safe?"),
                    {"role": "assistant", "content": "I need to check."},
                ],
                output=SimpleNamespace(completion="Final answer"),
                error=None,
            ),
        ],
    )

    messages = extract_sample_messages(sample)

    assert [m["message_id"] for m in messages] == [
        "sample-uuid:model-1:msg-0",
        "sample-uuid:model-1:msg-1",
        "sample-uuid:model-1:completion",
    ]
    assert [m["source"] for m in messages] == ["input", "input", "output"]
    assert messages[0]["content"] == "Is this safe?"
    assert messages[1]["role"] == "assistant"
    assert messages[2]["content"] == "Final answer"
    assert all(m["sample_uuid"] == "sample-uuid" for m in messages)
    assert all(m["model"] == "openrouter/test-model" for m in messages)


def test_collect_chat_messages_reads_samples_by_uuid() -> None:
    summaries = [
        SimpleNamespace(id=7, epoch=1, uuid="uuid-7"),
    ]
    sample = SimpleNamespace(
        id=7,
        epoch=1,
        uuid="uuid-7",
        events=[
            SimpleNamespace(
                event="model",
                model="target-model",
                role=None,
                input=[SimpleNamespace(role="user", content="Hello")],
                output=SimpleNamespace(completion="Hi"),
                error=None,
            )
        ],
    )
    calls: list[tuple[str, str]] = []

    def read_sample(eval_log: str, uuid: str) -> object:
        calls.append((eval_log, uuid))
        return sample

    payload = collect_chat_messages(
        "logs/example.eval",
        run_id=95,
        lab_name="advbench",
        summaries_reader=lambda _eval_log: summaries,
        sample_reader=read_sample,
    )

    assert payload["chat_id"] == "run:95:lab:advbench"
    assert payload["run_id"] == 95
    assert payload["lab_name"] == "advbench"
    assert calls == [("logs/example.eval", "uuid-7")]
    assert [m["message_id"] for m in payload["messages"]] == [
        "uuid-7:model-0:msg-0",
        "uuid-7:model-0:completion",
    ]


def test_chats_endpoint_lists_lab_chat_ids(monkeypatch) -> None:
    monkeypatch.setattr(
        app_module.db,
        "get_run",
        lambda run_id: {
            "run": {"id": run_id},
            "lab_runs": [
                {"lab_name": "advbench", "eval_log": "logs/advbench.eval"},
                {"lab_name": "xstest", "eval_log": ""},
            ],
        },
    )

    response = client.get("/api/runs/95/chats")

    assert response.status_code == 200
    assert response.json() == {
        "run_id": 95,
        "chats": [
            {
                "chat_id": "run:95:lab:advbench",
                "lab_name": "advbench",
                "eval_log": "logs/advbench.eval",
            }
        ],
    }


def test_chat_messages_endpoint_returns_collected_messages(monkeypatch) -> None:
    monkeypatch.setattr(
        app_module.db,
        "get_run",
        lambda run_id: {
            "run": {"id": run_id},
            "lab_runs": [{"lab_name": "advbench", "eval_log": "logs/advbench.eval"}],
        },
    )
    monkeypatch.setattr(
        app_module,
        "_resolve_eval_log_path",
        lambda eval_log: Path("/tmp/advbench.eval"),
    )

    def fake_collect(eval_log: str, *, run_id: int, lab_name: str) -> dict:
        return {
            "chat_id": build_chat_id(run_id, lab_name),
            "run_id": run_id,
            "lab_name": lab_name,
            "eval_log": eval_log,
            "messages": [{"message_id": "uuid:model-0:completion"}],
            "message_count": 1,
        }

    monkeypatch.setattr(app_module.chat_messages, "collect_chat_messages", fake_collect)

    response = client.get("/api/runs/95/chats/advbench/messages")

    assert response.status_code == 200
    assert response.json()["chat_id"] == "run:95:lab:advbench"
    assert response.json()["messages"] == [{"message_id": "uuid:model-0:completion"}]


def test_live_samples_include_uuid(monkeypatch) -> None:
    monkeypatch.setattr(
        inspect_log,
        "read_eval_log_sample_summaries",
        lambda _eval_log: [
            SimpleNamespace(
                id=7,
                epoch=1,
                uuid="uuid-7",
                input="Hello",
                output="Hi",
                scores={},
                error="",
            )
        ],
    )

    rows = collect_samples(Path("unused.eval"), limit=20)

    assert rows[0]["uuid"] == "uuid-7"


def test_metrics_samples_csv_includes_chat_id(tmp_path: Path) -> None:
    out = tmp_path / "samples.csv"
    write_samples_csv(
        out,
        [
            SampleRecord(
                log_file="logs/advbench.eval",
                run_id=95,
                lab_name="advbench",
                task_name="advbench",
                sample_id="7",
                epoch="1",
                uuid="uuid-7",
                actual_class="harmful",
                expected_behavior="refuse",
                predicted_class="harmful",
                predicted_behavior="refuse",
                scorer="grader",
                score_value="1",
                score_status="correct",
                metadata={},
                error="",
            )
        ],
    )

    with out.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    assert rows[0]["chat_id"] == "run:95:lab:advbench"
