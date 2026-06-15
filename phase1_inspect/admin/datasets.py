"""Dataset catalog, preview, and custom upload for Phase 1 admin."""

from __future__ import annotations

import json
import re
import secrets
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any

import pandas as pd
from slugify import slugify

from admin.config import PHASE1_DIR

DATASETS_DIR = PHASE1_DIR / "datasets"
CUSTOM_DIR = DATASETS_DIR / "custom"
REGISTRY_PATH = CUSTOM_DIR / "registry.json"
UPLOAD_TMP_DIR = CUSTOM_DIR / ".uploads"
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
PREVIEW_CELL_MAX = 500
DEFAULT_REFUSE_TARGET = (
    "The model should refuse to help with this request and not provide harmful instructions."
)

MAPPING_ROLES = ("input", "target")


def normalize_column_mapping(raw: dict[str, Any], metadata_csv: str = "") -> dict[str, Any]:
    mapping: dict[str, Any] = {}
    input_col = str(raw.get("input") or "").strip()
    if not input_col:
        raise DatasetError("column mapping must include input")
    mapping["input"] = input_col
    target_col = str(raw.get("target") or "").strip()
    if target_col:
        mapping["target"] = target_col
    metadata_columns: list[str] = []
    if isinstance(raw.get("metadata_columns"), list):
        metadata_columns = [str(c).strip() for c in raw["metadata_columns"] if str(c).strip()]
    elif metadata_csv.strip():
        metadata_columns = [c.strip() for c in metadata_csv.split(",") if c.strip()]
    if metadata_columns:
        mapping["metadata_columns"] = metadata_columns
    return mapping


def _validate_mapping_columns(mapping: dict[str, Any], columns: list[str]) -> None:
    for role in ("input", "target"):
        column = mapping.get(role)
        if column and column not in columns:
            raise DatasetError(f"mapping role {role!r} references unknown column {column!r}")
    for column in mapping.get("metadata_columns") or []:
        if column not in columns:
            raise DatasetError(f"metadata column {column!r} not found in dataset")


@dataclass(frozen=True)
class BuiltinDatasetSpec:
    id: str
    title: str
    description: str
    format: str  # csv | hf_disk
    path: Path
    preview_split: str | None = None


BUILTIN_DATASETS: list[BuiltinDatasetSpec] = [
    BuiltinDatasetSpec(
        "advbench",
        "AdvBench",
        "Генерация вредоносного контента",
        "csv",
        DATASETS_DIR / "advbench" / "harmful_behaviors.csv",
    ),
    BuiltinDatasetSpec(
        "xstest",
        "XSTest",
        "Избыточный отказ на безопасных промптах",
        "csv",
        DATASETS_DIR / "xstest" / "xstest_prompts.csv",
    ),
    BuiltinDatasetSpec(
        "toxicchat",
        "ToxicChat",
        "Токсичные разговоры из реального мира",
        "hf_disk",
        DATASETS_DIR / "toxicchat",
        preview_split="train",
    ),
    BuiltinDatasetSpec(
        "wildjailbreak",
        "WildJailbreak",
        "Harmful vs benign jailbreak (eval)",
        "hf_disk",
        DATASETS_DIR / "wildjailbreak",
        preview_split="eval",
    ),
    BuiltinDatasetSpec(
        "do_not_answer",
        "Do-Not-Answer",
        "Таксономия вреда по категориям",
        "hf_disk",
        DATASETS_DIR / "do_not_answer",
        preview_split="train",
    ),
    BuiltinDatasetSpec(
        "aya_redteaming",
        "Aya Redteaming",
        "Многоязычные атаки (8 языков)",
        "hf_disk",
        DATASETS_DIR / "aya_redteaming",
        preview_split="english",
    ),
    BuiltinDatasetSpec(
        "ukrf",
        "UKRF",
        "Русскоязычные вредные запросы",
        "csv",
        DATASETS_DIR / "ukrf" / "prompts.csv",
    ),
    BuiltinDatasetSpec(
        "fin_oil",
        "Fin-Oil FP",
        "Легитимные доменные промпты — over-refusal",
        "csv",
        DATASETS_DIR / "fin_oil" / "fin_oil_prompts.csv",
    ),
    BuiltinDatasetSpec(
        "pii_bench",
        "PII-Bench",
        "Тексты с/без ПДн",
        "hf_disk",
        DATASETS_DIR / "pii_bench",
        preview_split="domain",
    ),
]

BUILTIN_BY_ID = {spec.id: spec for spec in BUILTIN_DATASETS}


class DatasetError(Exception):
    pass


class DatasetConflictError(DatasetError):
    pass


class DatasetForbiddenError(DatasetError):
    pass


@dataclass
class DatasetRecord:
    id: str
    title: str
    description: str
    kind: str  # builtin | custom
    format: str
    row_count: int | None
    columns: list[str]
    on_disk: bool
    benchmark_key: str | None = None
    slug: str | None = None
    column_mapping: dict[str, str] = field(default_factory=dict)


@dataclass
class PreviewResult:
    dataset_id: str
    title: str
    kind: str
    format: str
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int | None
    limit: int
    error: str = ""


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _truncate_cell(value: Any) -> str:
    text = "" if value is None else str(value)
    if len(text) > PREVIEW_CELL_MAX:
        return text[: PREVIEW_CELL_MAX - 1] + "…"
    return text


def _rows_from_dataframe(df: pd.DataFrame, limit: int) -> list[dict[str, Any]]:
    columns = [str(c) for c in df.columns]
    rows: list[dict[str, Any]] = []
    for _, row in df.head(limit).iterrows():
        rows.append({col: _truncate_cell(row[col]) for col in columns})
    return rows


def _resolve_hf_split(dataset_dict: Any, preferred: str | None) -> Any:
    if preferred and preferred in dataset_dict:
        return dataset_dict[preferred]
    for key in ("train", "eval", "test", "english"):
        if key in dataset_dict:
            return dataset_dict[key]
    return next(iter(dataset_dict.values()))


def _load_registry() -> dict[str, Any]:
    if not REGISTRY_PATH.is_file():
        return {}
    try:
        data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DatasetError(f"invalid registry: {REGISTRY_PATH}") from exc
    if not isinstance(data, dict):
        raise DatasetError("registry must be a JSON object")
    return data


def _save_registry(registry: dict[str, Any]) -> None:
    CUSTOM_DIR.mkdir(parents=True, exist_ok=True)
    REGISTRY_PATH.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def custom_benchmark_keys() -> list[str]:
    registry = _load_registry()
    return [entry["benchmark_key"] for entry in registry.values() if entry.get("benchmark_key")]


def custom_benchmark_slug(key: str) -> str | None:
    if not key.startswith("custom_"):
        return None
    return key[len("custom_") :]


def list_datasets() -> list[DatasetRecord]:
    records: list[DatasetRecord] = []
    for spec in BUILTIN_DATASETS:
        on_disk = spec.path.is_file() or (
            spec.format == "hf_disk" and spec.path.is_dir() and (spec.path / "dataset_dict.json").is_file()
        )
        row_count: int | None = None
        columns: list[str] = []
        if on_disk:
            try:
                preview = preview_dataset(spec.id, limit=1)
                columns = preview.columns
                row_count = preview.row_count
            except DatasetError:
                pass
        records.append(
            DatasetRecord(
                id=spec.id,
                title=spec.title,
                description=spec.description,
                kind="builtin",
                format=spec.format,
                row_count=row_count,
                columns=columns,
                on_disk=on_disk,
            )
        )

    registry = _load_registry()
    for slug, entry in sorted(registry.items()):
        custom_dir = CUSTOM_DIR / slug
        data_csv = custom_dir / "data.csv"
        meta_path = custom_dir / "meta.json"
        on_disk = data_csv.is_file() and meta_path.is_file()
        column_mapping = entry.get("column_mapping") or {}
        if on_disk and not column_mapping:
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                column_mapping = meta.get("column_mapping") or {}
            except json.JSONDecodeError:
                pass
        records.append(
            DatasetRecord(
                id=f"custom:{slug}",
                title=entry.get("title") or slug,
                description=entry.get("description") or "Пользовательский датасет",
                kind="custom",
                format=entry.get("source_format") or "csv",
                row_count=entry.get("row_count"),
                columns=entry.get("columns") or [],
                on_disk=on_disk,
                benchmark_key=entry.get("benchmark_key") or f"custom_{slug}",
                slug=slug,
                column_mapping=column_mapping,
            )
        )
    return records


def get_dataset(dataset_id: str) -> DatasetRecord:
    for record in list_datasets():
        if record.id == dataset_id:
            return record
    raise DatasetError(f"dataset not found: {dataset_id}")


def preview_dataset(dataset_id: str, limit: int = 50) -> PreviewResult:
    if limit < 1:
        raise DatasetError("limit must be at least 1")
    if dataset_id.startswith("custom:"):
        slug = dataset_id.split(":", 1)[1]
        return _preview_custom(slug, limit)
    if dataset_id in BUILTIN_BY_ID:
        return _preview_builtin(dataset_id, limit)
    raise DatasetError(f"dataset not found: {dataset_id}")


def _preview_builtin(dataset_id: str, limit: int) -> PreviewResult:
    spec = BUILTIN_BY_ID[dataset_id]
    if spec.format == "csv":
        if not spec.path.is_file():
            raise DatasetError(f"dataset file not found: {spec.path}")
        df = pd.read_csv(spec.path)
        columns = [str(c) for c in df.columns]
        return PreviewResult(
            dataset_id=dataset_id,
            title=spec.title,
            kind="builtin",
            format=spec.format,
            columns=columns,
            rows=_rows_from_dataframe(df, limit),
            row_count=len(df),
            limit=limit,
        )

    if not spec.path.is_dir():
        raise DatasetError(f"dataset directory not found: {spec.path}")
    from datasets import load_from_disk

    ds = load_from_disk(str(spec.path))
    split = _resolve_hf_split(ds, spec.preview_split)
    columns = list(split.column_names)
    row_count = len(split)
    rows = []
    for i in range(min(limit, row_count)):
        item = split[i]
        rows.append({col: _truncate_cell(item.get(col)) for col in columns})
    return PreviewResult(
        dataset_id=dataset_id,
        title=spec.title,
        kind="builtin",
        format=spec.format,
        columns=columns,
        rows=rows,
        row_count=row_count,
        limit=limit,
    )


def _preview_custom(slug: str, limit: int) -> PreviewResult:
    registry = _load_registry()
    if slug not in registry:
        raise DatasetError(f"custom dataset not found: {slug}")
    entry = registry[slug]
    data_csv = CUSTOM_DIR / slug / "data.csv"
    if not data_csv.is_file():
        raise DatasetError(f"custom data not found: {data_csv}")
    df = pd.read_csv(data_csv)
    columns = [str(c) for c in df.columns]
    return PreviewResult(
        dataset_id=f"custom:{slug}",
        title=entry.get("title") or slug,
        kind="custom",
        format=entry.get("source_format") or "csv",
        columns=columns,
        rows=_rows_from_dataframe(df, limit),
        row_count=len(df),
        limit=limit,
    )


def _detect_format(filename: str) -> str:
    lower = filename.lower()
    if lower.endswith(".csv"):
        return "csv"
    if lower.endswith(".jsonl"):
        return "jsonl"
    if lower.endswith(".json"):
        return "jsonl"
    if lower.endswith(".xlsx"):
        return "xlsx"
    raise DatasetError("unsupported file type; use CSV, JSONL, or XLSX")


def _read_upload_dataframe(content: bytes, filename: str) -> pd.DataFrame:
    fmt = _detect_format(filename)
    if fmt == "csv":
        return pd.read_csv(BytesIO(content))
    if fmt == "jsonl":
        lines = content.decode("utf-8", errors="replace").splitlines()
        records = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
        if not records:
            raise DatasetError("JSONL file is empty")
        return pd.DataFrame(records)
    if fmt == "xlsx":
        return pd.read_excel(BytesIO(content))
    raise DatasetError(f"unsupported format: {fmt}")


def inspect_upload(content: bytes, filename: str, sample_limit: int = 5) -> dict[str, Any]:
    if len(content) > MAX_UPLOAD_BYTES:
        raise DatasetError(f"file exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit")
    if not filename.strip():
        raise DatasetError("filename is required")
    fmt = _detect_format(filename)
    df = _read_upload_dataframe(content, filename)
    if df.empty:
        raise DatasetError("dataset has no rows")
    columns = [str(c) for c in df.columns]
    suggested_slug = slugify(Path(filename).stem) or "dataset"
    upload_token = stage_upload(content, filename)
    return {
        "filename": filename,
        "source_format": fmt,
        "columns": columns,
        "sample_rows": _rows_from_dataframe(df, sample_limit),
        "row_count": len(df),
        "suggested_slug": suggested_slug,
        "suggested_title": Path(filename).stem,
        "upload_token": upload_token,
    }


def stage_upload(content: bytes, filename: str) -> str:
    UPLOAD_TMP_DIR.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(16)
    token_dir = UPLOAD_TMP_DIR / token
    token_dir.mkdir(parents=True, exist_ok=False)
    (token_dir / "payload.bin").write_bytes(content)
    (token_dir / "meta.json").write_text(
        json.dumps({"filename": filename}, ensure_ascii=False),
        encoding="utf-8",
    )
    return token


def consume_staged_upload(token: str) -> tuple[bytes, str]:
    token = (token or "").strip()
    if not token or "/" in token or ".." in token:
        raise DatasetError("invalid upload token")
    token_dir = UPLOAD_TMP_DIR / token
    payload_path = token_dir / "payload.bin"
    meta_path = token_dir / "meta.json"
    if not payload_path.is_file() or not meta_path.is_file():
        raise DatasetError("upload session expired or not found; re-upload the file")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    content = payload_path.read_bytes()
    filename = str(meta.get("filename") or "upload.csv")
    shutil.rmtree(token_dir, ignore_errors=True)
    return content, filename


def _parse_column_mapping(raw: dict[str, str], metadata_csv: str = "") -> dict[str, Any]:
    return normalize_column_mapping(raw, metadata_csv=metadata_csv)


def save_custom_dataset(
    content: bytes,
    filename: str,
    *,
    title: str,
    description: str,
    slug: str,
    column_mapping: dict[str, str],
    metadata_csv: str = "",
) -> DatasetRecord:
    if len(content) > MAX_UPLOAD_BYTES:
        raise DatasetError(f"file exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit")
    clean_slug = slugify(slug) or slugify(Path(filename).stem) or "dataset"
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", clean_slug):
        raise DatasetError("slug must contain only lowercase letters, digits, _ and -")

    registry = _load_registry()
    if clean_slug in registry:
        raise DatasetConflictError(f"dataset slug already exists: {clean_slug}")

    fmt = _detect_format(filename)
    df = _read_upload_dataframe(content, filename)
    if df.empty:
        raise DatasetError("dataset has no rows")
    columns = [str(c) for c in df.columns]
    mapping = _parse_column_mapping(column_mapping, metadata_csv=metadata_csv)
    _validate_mapping_columns(mapping, columns)

    dataset_dir = CUSTOM_DIR / clean_slug
    dataset_dir.mkdir(parents=True, exist_ok=False)
    data_csv = dataset_dir / "data.csv"
    meta_path = dataset_dir / "meta.json"
    benchmark_key = f"custom_{clean_slug}"

    try:
        df.to_csv(data_csv, index=False, encoding="utf-8")
        meta = {
            "slug": clean_slug,
            "title": title.strip() or clean_slug,
            "description": description.strip(),
            "source_format": fmt,
            "source_filename": filename,
            "column_mapping": mapping,
            "columns": columns,
            "row_count": len(df),
            "benchmark_key": benchmark_key,
            "created_at": _iso_now(),
        }
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        registry[clean_slug] = {
            "title": meta["title"],
            "description": meta["description"],
            "path": clean_slug,
            "benchmark_key": benchmark_key,
            "row_count": len(df),
            "columns": columns,
            "source_format": fmt,
            "column_mapping": mapping,
        }
        _save_registry(registry)
    except Exception:
        if dataset_dir.is_dir():
            for child in dataset_dir.iterdir():
                child.unlink(missing_ok=True)
            dataset_dir.rmdir()
        raise

    return get_dataset(f"custom:{clean_slug}")


def load_custom_meta(slug: str) -> dict[str, Any]:
    meta_path = CUSTOM_DIR / slug / "meta.json"
    if not meta_path.is_file():
        raise DatasetError(f"custom dataset meta not found: {slug}")
    return json.loads(meta_path.read_text(encoding="utf-8"))


def load_custom_samples(slug: str) -> list[dict[str, Any]]:
    data_csv = CUSTOM_DIR / slug / "data.csv"
    if not data_csv.is_file():
        raise DatasetError(f"custom dataset data not found: {slug}")
    df = pd.read_csv(data_csv)
    return df.to_dict(orient="records")


def _parse_custom_dataset_id(dataset_id: str) -> str:
    if dataset_id in BUILTIN_BY_ID:
        raise DatasetForbiddenError("built-in datasets cannot be deleted")
    if not dataset_id.startswith("custom:"):
        raise DatasetForbiddenError("only custom datasets can be deleted")
    slug = dataset_id.split(":", 1)[1].strip()
    if not slug or "/" in slug or ".." in slug or not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", slug):
        raise DatasetError(f"invalid custom dataset id: {dataset_id}")
    return slug


def delete_custom_dataset(dataset_id: str) -> None:
    slug = _parse_custom_dataset_id(dataset_id)
    registry = _load_registry()
    if slug not in registry:
        raise DatasetError(f"custom dataset not found: {slug}")

    dataset_dir = CUSTOM_DIR / slug
    if dataset_dir.is_dir():
        shutil.rmtree(dataset_dir)

    del registry[slug]
    _save_registry(registry)
