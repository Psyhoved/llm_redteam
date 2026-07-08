"""Tests for dataset catalog, preview, and upload."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import ModuleType

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
    import_jobs = custom_dir / ".import_jobs"
    import_jobs.mkdir()

    monkeypatch.setattr(datasets, "CUSTOM_DIR", custom_dir)
    monkeypatch.setattr(datasets, "REGISTRY_PATH", registry)
    monkeypatch.setattr(datasets, "UPLOAD_TMP_DIR", upload_tmp)
    monkeypatch.setattr(datasets, "IMPORT_JOBS_DIR", import_jobs)
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


def test_preview_builtin_hf_train_plus_test(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class FakeSplit(list):
        column_names = ["user_input", "toxicity"]

    class FakeDatasetDict(dict):
        @property
        def column_names(self):
            return {name: ["user_input", "toxicity"] for name in self}

    fake_hf = ModuleType("datasets")
    fake_hf.load_from_disk = lambda _: FakeDatasetDict(
        {
            "train": FakeSplit(
                [
                    {"user_input": "train 1", "toxicity": 0},
                    {"user_input": "train 2", "toxicity": 1},
                ]
            ),
            "test": FakeSplit([{"user_input": "test 1", "toxicity": 0}]),
        }
    )
    monkeypatch.setitem(sys.modules, "datasets", fake_hf)

    dataset_dir = tmp_path / "toxicchat"
    dataset_dir.mkdir()
    monkeypatch.setitem(
        datasets.BUILTIN_BY_ID,
        "toxicchat_test",
        datasets.BuiltinDatasetSpec(
            "toxicchat_test",
            "ToxicChat Test",
            "Full train + test preview",
            "hf_disk",
            dataset_dir,
            preview_split="train+test",
        ),
    )

    preview = datasets.preview_dataset("toxicchat_test", limit=2)

    assert preview.row_count == 3
    assert [row["user_input"] for row in preview.rows] == ["train 1", "train 2"]
    assert preview.columns == ["user_input", "toxicity"]


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


def test_parse_hf_url_variants() -> None:
    assert datasets.parse_hf_url("piimb/privy") == "piimb/privy"
    assert (
        datasets.parse_hf_url("https://huggingface.co/datasets/piimb/privy")
        == "piimb/privy"
    )
    with pytest.raises(datasets.DatasetError):
        datasets.parse_hf_url("not-a-valid-url")


def test_should_use_background_import() -> None:
    assert datasets.should_use_background_import(None) is True
    assert datasets.should_use_background_import(100) is False
    assert datasets.should_use_background_import(datasets.HF_SYNC_IMPORT_BYTES + 1) is True
    assert datasets.should_use_background_import(100, hf_hub=True) is True


def test_resolve_hf_config() -> None:
    picked, auto = datasets._resolve_hf_config(["privy-small", "privy-large"], None)
    assert picked == "privy-small"
    assert auto is True
    picked, auto = datasets._resolve_hf_config(["privy-small", "privy-large"], "privy-large")
    assert picked == "privy-large"
    assert auto is False
    picked, auto = datasets._resolve_hf_config(["privy-small", "privy-large"], "small")
    assert picked == "privy-small"
    assert auto is False
    with pytest.raises(datasets.DatasetError):
        datasets._resolve_hf_config(["privy-small"], "nope")


def test_inspect_hf_source_mock(isolated_custom_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeStream:
        def take(self, n: int):
            return [
                {"full_text": "hello", "masked": "h***o"},
                {"full_text": "world", "masked": "w***d"},
            ][:n]

    def _fake_load_dataset(*args, **kwargs):
        assert kwargs.get("streaming") is True
        return _FakeStream()

    import sys

    fake_datasets_mod = type(sys)("datasets")
    fake_datasets_mod.load_dataset = _fake_load_dataset
    monkeypatch.setitem(sys.modules, "datasets", fake_datasets_mod)
    monkeypatch.setattr(datasets, "list_hf_configs", lambda repo_id: ["small"])
    monkeypatch.setattr(datasets, "list_hf_splits", lambda repo_id, config: ["train"])
    monkeypatch.setattr(
        datasets,
        "estimate_hf_import_size",
        lambda repo_id, config, split: datasets.HF_SYNC_IMPORT_BYTES + 1,
    )

    result = datasets.inspect_hf_source("piimb/privy", config="small", split="train")
    assert result["source"] == "huggingface"
    assert result["hf_repo_id"] == "piimb/privy"
    assert result["background_required"] is True
    assert "full_text" in result["columns"]
    assert result["hf_staging_token"]


def test_enqueue_and_run_hf_import_job_mock(
    isolated_custom_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hf_meta = {
        "repo_id": "piimb/privy",
        "config": "privy-small",
        "split": "train",
        "estimated_bytes": 5_000_000_000,
    }
    job_id = datasets.enqueue_hf_import_job(
        hf_meta,
        title="Privy",
        description="PII dataset",
        slug="privy-test",
        column_mapping={"input": "full_text"},
    )
    job = datasets.load_import_job(job_id)
    assert job["status"] == "pending"
    assert job["slug"] == "privy-test"

    sample_df = __import__("pandas").DataFrame(
        [{"full_text": "secret data", "masked": "s***t"}]
    )

    monkeypatch.setattr(datasets, "_load_hf_dataframe", lambda *args, **kwargs: sample_df)
    datasets.run_hf_import_job(job_id)
    job = datasets.load_import_job(job_id)
    assert job["status"] == "done"
    assert job["dataset_id"] == "custom:privy-test"
    assert (isolated_custom_dir / "privy-test" / "data.csv").is_file()


def test_resolve_hf_import_meta_from_form_fields() -> None:
    meta = datasets.resolve_hf_import_meta(
        hf_repo_id="piimb/privy",
        hf_config="privy-small",
        hf_split="train",
        hf_estimated_bytes="181373040",
    )
    assert meta["repo_id"] == "piimb/privy"
    assert meta["config"] == "privy-small"
    assert meta["estimated_bytes"] == 181373040


def test_save_hf_sync_small_mock(isolated_custom_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    hf_meta = {
        "repo_id": "org/tiny",
        "config": "",
        "split": "train",
        "estimated_bytes": 1024,
    }
    sample_df = __import__("pandas").DataFrame([{"prompt": "hi"}])
    monkeypatch.setattr(datasets, "_load_hf_dataframe", lambda *args, **kwargs: sample_df)
    record = datasets.save_custom_dataset_from_hf_sync(
        hf_meta,
        title="Tiny",
        description="",
        slug="tiny-hf",
        column_mapping={"input": "prompt"},
    )
    assert record.benchmark_key == "custom_tiny-hf"


def test_inspect_hf_endpoint_mock(isolated_custom_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        datasets,
        "inspect_hf_source",
        lambda url, config=None, split=None: {
            "source": "huggingface",
            "hf_repo_id": "piimb/privy",
            "hf_config": "small",
            "hf_split": "train",
            "hf_staging_token": "tok123",
            "columns": ["full_text"],
            "sample_rows": [{"full_text": "x"}],
            "row_count": None,
            "estimated_size_human": "4.5 GB",
            "background_required": True,
            "suggested_slug": "privy",
            "suggested_title": "Privy",
            "filename": "privy.hf",
            "source_format": "huggingface",
        },
    )
    response = client.post(
        "/api/datasets/inspect-hf",
        data={"hf_url": "https://huggingface.co/datasets/piimb/privy"},
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 200
    assert "Маппинг колонок" in response.text
    assert "hf_staging_token" in response.text
