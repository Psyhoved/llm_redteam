"""Tests for dataset catalog, preview, and upload."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from admin import config, datasets
from admin.app import app
from admin.runner import LaunchRequest, validate_launch

client = TestClient(app)
FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def isolated_custom_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    custom_dir = tmp_path / "custom"
    custom_dir.mkdir()
    registry = custom_dir / "registry.json"
    registry.write_text("{}", encoding="utf-8")
    upload_tmp = custom_dir / ".uploads"
    upload_tmp.mkdir()

    monkeypatch.setattr(datasets, "CUSTOM_DIR", custom_dir)
    monkeypatch.setattr(datasets, "REGISTRY_PATH", registry)
    monkeypatch.setattr(datasets, "UPLOAD_TMP_DIR", upload_tmp)
    return custom_dir


def test_preview_builtin_advbench() -> None:
    try:
        preview = datasets.preview_dataset("advbench", limit=3)
    except datasets.DatasetError:
        pytest.skip("advbench dataset not on disk")
    assert preview.kind == "builtin"
    assert "goal" in preview.columns
    assert len(preview.rows) <= 3
    assert preview.row_count and preview.row_count > 0


def test_upload_csv_creates_registry_and_data(isolated_custom_dir: Path) -> None:
    content = (FIXTURES / "sample.csv").read_bytes()
    inspect_result = datasets.inspect_upload(content, "sample.csv")
    assert inspect_result["upload_token"]
    assert "prompt" in inspect_result["columns"]

    staged = datasets.consume_staged_upload(inspect_result["upload_token"])
    assert staged[1] == "sample.csv"

    # Re-stage because consume removes token
    token = datasets.stage_upload(content, "sample.csv")
    content2, filename = datasets.consume_staged_upload(token)

    record = datasets.save_custom_dataset(
        content2,
        filename,
        title="Sample CSV",
        description="Test upload",
        slug="sample-csv",
        column_mapping={"input": "prompt"},
        metadata_csv="category",
    )
    assert record.kind == "custom"
    assert record.benchmark_key == "custom_sample-csv"
    assert (isolated_custom_dir / "sample-csv" / "data.csv").is_file()
    registry = json.loads((isolated_custom_dir / "registry.json").read_text(encoding="utf-8"))
    assert "sample-csv" in registry


def test_upload_jsonl(isolated_custom_dir: Path) -> None:
    content = (FIXTURES / "sample.jsonl").read_bytes()
    record = datasets.save_custom_dataset(
        content,
        "sample.jsonl",
        title="JSONL set",
        description="",
        slug="jsonl-set",
        column_mapping={"input": "prompt"},
        metadata_csv="label",
    )
    assert record.row_count == 2
    preview = datasets.preview_dataset(record.id, limit=10)
    assert len(preview.rows) == 2


def test_duplicate_slug_conflict(isolated_custom_dir: Path) -> None:
    content = (FIXTURES / "sample.csv").read_bytes()
    datasets.save_custom_dataset(
        content,
        "sample.csv",
        title="One",
        description="",
        slug="dup",
        column_mapping={"input": "prompt"},
    )
    with pytest.raises(datasets.DatasetConflictError):
        datasets.save_custom_dataset(
            content,
            "sample.csv",
            title="Two",
            description="",
            slug="dup",
            column_mapping={"input": "prompt"},
        )


def test_all_benchmarks_includes_custom(isolated_custom_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    content = (FIXTURES / "sample.csv").read_bytes()
    datasets.save_custom_dataset(
        content,
        "sample.csv",
        title="Bench",
        description="",
        slug="bench-one",
        column_mapping={"input": "prompt"},
    )

    def _custom_specs():
        return [
            config.BenchmarkSpec(
                key=record.benchmark_key or "custom_bench-one",
                title=record.title,
                description=record.description,
            )
            for record in datasets.list_datasets()
            if record.kind == "custom" and record.on_disk
        ]

    monkeypatch.setattr(config, "custom_benchmark_specs", _custom_specs)
    keys = {b.key for b in config.all_benchmarks()}
    assert "custom_bench-one" in keys


def test_runner_accepts_custom_benchmark(isolated_custom_dir: Path) -> None:
    content = (FIXTURES / "sample.csv").read_bytes()
    datasets.save_custom_dataset(
        content,
        "sample.csv",
        title="Bench",
        description="",
        slug="runner-bench",
        column_mapping={"input": "prompt"},
    )
    req = LaunchRequest(
        limit=5,
        benchmarks=["custom_runner-bench"],
        at_moscow=None,
        screen_session="test_session",
        target_model=None,
        grader_model=None,
        max_connections=None,
    )
    validate_launch(req)


def test_datasets_page_renders() -> None:
    response = client.get("/datasets")
    assert response.status_code == 200
    assert "Датасеты" in response.text
    assert "AdvBench" in response.text


def test_dataset_detail_page_builtin() -> None:
    try:
        datasets.preview_dataset("advbench", limit=1)
    except datasets.DatasetError:
        pytest.skip("advbench dataset not on disk")
    response = client.get("/datasets/advbench")
    assert response.status_code == 200
    assert "Предпросмотр" in response.text


def test_inspect_upload_endpoint(isolated_custom_dir: Path) -> None:
    with open(FIXTURES / "sample.csv", "rb") as fh:
        response = client.post(
            "/api/datasets/inspect-upload",
            files={"dataset_file": ("sample.csv", fh, "text/csv")},
            headers={"HX-Request": "true"},
        )
    assert response.status_code == 200
    assert "Маппинг колонок" in response.text
    assert "upload_token" in response.text


def test_delete_custom_dataset(isolated_custom_dir: Path) -> None:
    content = (FIXTURES / "sample.csv").read_bytes()
    record = datasets.save_custom_dataset(
        content,
        "sample.csv",
        title="To delete",
        description="",
        slug="to-delete",
        column_mapping={"input": "prompt"},
    )
    assert (isolated_custom_dir / "to-delete" / "data.csv").is_file()

    datasets.delete_custom_dataset(record.id)
    assert not (isolated_custom_dir / "to-delete").exists()
    registry = json.loads((isolated_custom_dir / "registry.json").read_text(encoding="utf-8"))
    assert "to-delete" not in registry


def test_delete_builtin_forbidden() -> None:
    with pytest.raises(datasets.DatasetForbiddenError):
        datasets.delete_custom_dataset("advbench")


def test_delete_custom_via_api(isolated_custom_dir: Path) -> None:
    content = (FIXTURES / "sample.csv").read_bytes()
    record = datasets.save_custom_dataset(
        content,
        "sample.csv",
        title="API delete",
        description="",
        slug="api-delete",
        column_mapping={"input": "prompt"},
    )
    response = client.post(f"/api/datasets/{record.id}/delete", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/datasets"
    assert not (isolated_custom_dir / "api-delete").exists()


def test_delete_builtin_via_api_returns_403() -> None:
    response = client.post("/api/datasets/advbench/delete", follow_redirects=False)
    assert response.status_code == 403
