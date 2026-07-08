"""Dataset catalog, preview, and custom upload for Phase 1 admin."""

from __future__ import annotations

import json
import os
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
IMPORT_JOBS_DIR = CUSTOM_DIR / ".import_jobs"
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_HF_IMPORT_BYTES = 8 * 1024 * 1024 * 1024
HF_SYNC_IMPORT_BYTES = int(os.environ.get("PHASE1_HF_SYNC_LIMIT_MB", "500")) * 1024 * 1024
PREVIEW_CELL_MAX = 500
_HF_URL_RE = re.compile(
    r"^(?:https?://)?(?:www\.)?huggingface\.co/datasets/([^?\s#]+)|^([a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+)$"
)
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
        "Токсичные и безопасные разговоры из train + test",
        "hf_disk",
        DATASETS_DIR / "toxicchat",
        preview_split="train+test",
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


def _resolve_hf_preview_splits(dataset_dict: Any, preferred: str | None) -> list[tuple[str, Any]]:
    column_names = getattr(dataset_dict, "column_names", None)
    if column_names is not None and not isinstance(column_names, dict):
        return [("default", dataset_dict)]
    if preferred and "+" in preferred:
        names = [name.strip() for name in preferred.split("+") if name.strip()]
        selected = [(name, dataset_dict[name]) for name in names if name in dataset_dict]
        if selected:
            return selected
    if preferred and preferred in dataset_dict:
        return [(preferred, dataset_dict[preferred])]
    for key in ("train", "eval", "test", "english"):
        if key in dataset_dict:
            return [(key, dataset_dict[key])]
    first = next(iter(dataset_dict.keys()))
    return [(first, dataset_dict[first])]


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


def _custom_dataset_on_disk(slug: str) -> bool:
    custom_dir = CUSTOM_DIR / slug
    return (custom_dir / "data.csv").is_file() and (custom_dir / "meta.json").is_file()


def custom_benchmark_keys() -> list[str]:
    registry = _load_registry()
    return [
        entry["benchmark_key"]
        for slug, entry in registry.items()
        if entry.get("benchmark_key") and _custom_dataset_on_disk(slug)
    ]


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
        meta_path = CUSTOM_DIR / slug / "meta.json"
        on_disk = _custom_dataset_on_disk(slug)
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
    splits = _resolve_hf_preview_splits(ds, spec.preview_split)
    columns = list(splits[0][1].column_names)
    row_count = sum(len(split) for _, split in splits)
    rows = []
    for _, split in splits:
        remaining = limit - len(rows)
        if remaining <= 0:
            break
        for i in range(min(remaining, len(split))):
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


def hf_token() -> str | None:
    return os.environ.get("HF_TOKEN") or None


def parse_hf_url(url: str) -> str:
    cleaned = url.strip().rstrip("/")
    if not cleaned:
        raise DatasetError("Hugging Face URL is required")
    match = _HF_URL_RE.match(cleaned)
    if match:
        return (match.group(1) or match.group(2)).strip("/")
    raise DatasetError(f"invalid Hugging Face dataset URL: {url}")


def _format_bytes(num: int | None) -> str:
    if num is None:
        return "неизвестно"
    if num < 1024:
        return f"{num} B"
    if num < 1024 * 1024:
        return f"{num / 1024:.1f} KB"
    if num < 1024 * 1024 * 1024:
        return f"{num / (1024 * 1024):.1f} MB"
    return f"{num / (1024 * 1024 * 1024):.2f} GB"


def should_use_background_import(estimated_bytes: int | None, *, hf_hub: bool = False) -> bool:
    if hf_hub:
        return True
    if estimated_bytes is None:
        return True
    return estimated_bytes > HF_SYNC_IMPORT_BYTES


def list_hf_configs(repo_id: str) -> list[str]:
    from datasets import get_dataset_config_names

    try:
        return list(get_dataset_config_names(repo_id, token=hf_token()))
    except Exception as exc:
        raise DatasetError(f"failed to list configs for {repo_id}: {exc}") from exc


def list_hf_splits(repo_id: str, config: str | None) -> list[str]:
    from datasets import get_dataset_split_names

    try:
        token = hf_token()
        if config:
            return list(get_dataset_split_names(repo_id, config, token=token))
        return list(get_dataset_split_names(repo_id, token=token))
    except Exception as exc:
        raise DatasetError(f"failed to list splits for {repo_id}: {exc}") from exc


def _resolve_hf_config(configs: list[str], requested: str | None) -> tuple[str | None, bool]:
    """Pick dataset config; returns (config, auto_selected)."""
    clean = (requested or "").strip()
    if clean:
        if clean in configs:
            return clean, False
        lowered = clean.lower()
        for name in configs:
            if name.lower() == lowered or name.lower().endswith(lowered):
                return name, False
        available = ", ".join(configs) if configs else "(none)"
        raise DatasetError(f"config {clean!r} not found. Available: {available}")
    if len(configs) == 1:
        return configs[0], False
    if len(configs) > 1:
        return configs[0], True
    return None, False


def _resolve_hf_split_name(splits: list[str]) -> str:
    for key in ("train", "eval", "test", "english", "small"):
        if key in splits:
            return key
    if not splits:
        raise DatasetError("dataset has no splits")
    return splits[0]


def estimate_hf_import_size(repo_id: str, config: str | None, split: str) -> int | None:
    try:
        from datasets import load_dataset_builder

        kwargs: dict[str, Any] = {"path": repo_id, "token": hf_token()}
        if config:
            kwargs["name"] = config
        builder = load_dataset_builder(**kwargs)
        if split in builder.info.splits:
            return builder.info.splits[split].num_bytes
        total = sum(
            s.num_bytes for s in builder.info.splits.values() if s.num_bytes is not None
        )
        return total or None
    except Exception:
        return None


def _records_to_dataframe(records: list[dict[str, Any]]) -> pd.DataFrame:
    if not records:
        raise DatasetError("dataset preview is empty")
    return _normalize_dataframe_for_csv(pd.DataFrame(records))


def _normalize_dataframe_for_csv(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in out.columns:
        out[col] = out[col].map(_serialize_cell)
    return out


def _serialize_cell(value: Any) -> Any:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return value
    if hasattr(value, "item") and not isinstance(value, (str, bytes, dict, list)):
        try:
            return value.item()
        except (ValueError, AttributeError):
            pass
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return value


def _check_disk_space(required_bytes: int) -> None:
    CUSTOM_DIR.mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(CUSTOM_DIR)
    buffer = max(required_bytes, 512 * 1024 * 1024)
    if usage.free < buffer * 2:
        raise DatasetError(
            f"insufficient disk space: need ~{_format_bytes(buffer * 2)}, "
            f"free {_format_bytes(usage.free)}"
        )


def _check_hf_size_limit(estimated_bytes: int | None) -> None:
    if estimated_bytes is not None and estimated_bytes > MAX_HF_IMPORT_BYTES:
        raise DatasetError(
            f"dataset exceeds {MAX_HF_IMPORT_BYTES // (1024**3)} GB limit "
            f"(estimated {_format_bytes(estimated_bytes)})"
        )


def stage_hf_import(
    repo_id: str,
    config: str | None,
    split: str,
    estimated_bytes: int | None,
) -> str:
    UPLOAD_TMP_DIR.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(16)
    token_dir = UPLOAD_TMP_DIR / token
    token_dir.mkdir(parents=True, exist_ok=False)
    (token_dir / "hf_meta.json").write_text(
        json.dumps(
            {
                "repo_id": repo_id,
                "config": config or "",
                "split": split,
                "estimated_bytes": estimated_bytes,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return token


def load_staged_hf_meta(token: str) -> dict[str, Any]:
    token = (token or "").strip()
    if not token or "/" in token or ".." in token:
        raise DatasetError("invalid HF staging token")
    meta_path = UPLOAD_TMP_DIR / token / "hf_meta.json"
    if not meta_path.is_file():
        raise DatasetError("HF import session expired or not found; re-inspect the dataset")
    data = json.loads(meta_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise DatasetError("invalid HF staging metadata")
    return data


def _parse_estimated_bytes(raw: str) -> int | None:
    value = (raw or "").strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def resolve_hf_import_meta(
    *,
    hf_staging_token: str = "",
    hf_repo_id: str = "",
    hf_config: str = "",
    hf_split: str = "",
    hf_estimated_bytes: str = "",
) -> dict[str, Any]:
    """Resolve HF import params from form fields, with optional staging token fallback."""
    token = (hf_staging_token or "").strip()
    if token:
        try:
            return load_staged_hf_meta(token)
        except DatasetError:
            pass

    repo_id = (hf_repo_id or "").strip()
    split = (hf_split or "").strip()
    if not repo_id or not split:
        raise DatasetError(
            "HF import parameters missing; open /datasets and run preview again"
        )
    return {
        "repo_id": repo_id,
        "config": (hf_config or "").strip(),
        "split": split,
        "estimated_bytes": _parse_estimated_bytes(hf_estimated_bytes),
    }


def clear_staged_hf(token: str | None) -> None:
    if not token:
        return
    token_dir = UPLOAD_TMP_DIR / token
    if token_dir.is_dir():
        shutil.rmtree(token_dir, ignore_errors=True)


def _load_hf_dataframe(repo_id: str, config: str | None, split: str) -> pd.DataFrame:
    from datasets import load_dataset

    token = hf_token()
    if config:
        ds = load_dataset(repo_id, config, split=split, token=token)
    else:
        ds = load_dataset(repo_id, split=split, token=token)
    if hasattr(ds, "to_pandas"):
        df = ds.to_pandas()
    else:
        df = pd.DataFrame(list(ds))
    if df.empty:
        raise DatasetError("Hugging Face dataset split is empty")
    return _normalize_dataframe_for_csv(df)


def inspect_hf_source(
    url: str,
    config: str | None = None,
    split: str | None = None,
    sample_limit: int = 5,
) -> dict[str, Any]:
    from datasets import load_dataset

    repo_id = parse_hf_url(url)
    token = hf_token()
    configs = list_hf_configs(repo_id)
    chosen_config, config_auto_selected = _resolve_hf_config(configs, config)

    splits = list_hf_splits(repo_id, chosen_config)
    chosen_split = (split or "").strip() or _resolve_hf_split_name(splits)

    try:
        if chosen_config:
            stream = load_dataset(
                repo_id,
                chosen_config,
                split=chosen_split,
                streaming=True,
                token=token,
            )
        else:
            stream = load_dataset(
                repo_id,
                split=chosen_split,
                streaming=True,
                token=token,
            )
        rows_raw = list(stream.take(sample_limit))
    except Exception as exc:
        message = str(exc).lower()
        if "gated" in message or "authenticated" in message:
            raise DatasetError(
                "gated dataset: set HF_TOKEN in the environment or run huggingface-cli login"
            ) from exc
        raise DatasetError(f"failed to preview {repo_id}: {exc}") from exc

    df = _records_to_dataframe(rows_raw)
    estimated_bytes = estimate_hf_import_size(repo_id, chosen_config, chosen_split)
    _check_hf_size_limit(estimated_bytes)
    staging_token = stage_hf_import(repo_id, chosen_config, chosen_split, estimated_bytes)
    short_name = repo_id.split("/")[-1]
    return {
        "source": "huggingface",
        "hf_repo_id": repo_id,
        "hf_config": chosen_config or "",
        "hf_split": chosen_split,
        "hf_staging_token": staging_token,
        "columns": [str(c) for c in df.columns],
        "sample_rows": _rows_from_dataframe(df, sample_limit),
        "row_count": None,
        "estimated_bytes": estimated_bytes,
        "estimated_size_human": _format_bytes(estimated_bytes),
        "background_required": should_use_background_import(estimated_bytes, hf_hub=True),
        "available_configs": configs,
        "available_splits": splits,
        "config_auto_selected": config_auto_selected,
        "suggested_slug": slugify(short_name) or "hf-dataset",
        "suggested_title": short_name.replace("_", " ").replace("-", " ").title(),
        "filename": f"{short_name}.hf",
        "source_format": "huggingface",
    }


def _import_job_path(job_id: str) -> Path:
    if not job_id or "/" in job_id or ".." in job_id:
        raise DatasetError("invalid import job id")
    return IMPORT_JOBS_DIR / f"{job_id}.json"


def _import_job_log_path(job_id: str) -> Path:
    return IMPORT_JOBS_DIR / f"{job_id}.log"


def load_import_job(job_id: str) -> dict[str, Any]:
    path = _import_job_path(job_id)
    if not path.is_file():
        raise DatasetError(f"import job not found: {job_id}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise DatasetError("invalid import job metadata")
    return data


def save_import_job(job: dict[str, Any]) -> None:
    IMPORT_JOBS_DIR.mkdir(parents=True, exist_ok=True)
    job_id = job["job_id"]
    _import_job_path(job_id).write_text(
        json.dumps(job, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def update_import_job(job_id: str, **fields: Any) -> dict[str, Any]:
    job = load_import_job(job_id)
    job.update(fields)
    job["updated_at"] = _iso_now()
    save_import_job(job)
    return job


def append_import_job_log(job_id: str, message: str) -> None:
    IMPORT_JOBS_DIR.mkdir(parents=True, exist_ok=True)
    line = f"[{_iso_now()}] {message}\n"
    with _import_job_log_path(job_id).open("a", encoding="utf-8") as fh:
        fh.write(line)


def resolve_import_job_status(job: dict[str, Any]) -> str:
    status = str(job.get("status") or "pending")
    if status in ("done", "failed"):
        return status
    session = job.get("screen_session")
    if session:
        from admin.hf_runner import screen_session_alive

        alive = screen_session_alive(session)
        if alive is False and status in ("pending", "downloading", "converting"):
            return "stale"
    return status


def enqueue_hf_import_job(
    hf_meta: dict[str, Any],
    *,
    hf_staging_token: str | None = None,
    title: str,
    description: str,
    slug: str,
    column_mapping: dict[str, Any],
    metadata_csv: str = "",
) -> str:
    estimated_bytes = hf_meta.get("estimated_bytes")
    _check_hf_size_limit(estimated_bytes)
    if estimated_bytes:
        _check_disk_space(int(estimated_bytes))

    clean_slug = slugify(slug) or slugify(hf_meta["repo_id"].split("/")[-1]) or "hf-dataset"
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", clean_slug):
        raise DatasetError("slug must contain only lowercase letters, digits, _ and -")
    registry = _load_registry()
    if clean_slug in registry:
        raise DatasetConflictError(f"dataset slug already exists: {clean_slug}")

    mapping = _parse_column_mapping(column_mapping, metadata_csv=metadata_csv)
    job_id = secrets.token_urlsafe(12)
    job = {
        "job_id": job_id,
        "status": "pending",
        "hf_staging_token": hf_staging_token,
        "repo_id": hf_meta["repo_id"],
        "hf_config": hf_meta.get("config") or "",
        "hf_split": hf_meta["split"],
        "estimated_bytes": estimated_bytes,
        "title": title.strip() or clean_slug,
        "description": description.strip(),
        "slug": clean_slug,
        "column_mapping": mapping,
        "screen_session": None,
        "screen_log": None,
        "dataset_id": None,
        "error": "",
        "created_at": _iso_now(),
        "updated_at": _iso_now(),
    }
    save_import_job(job)
    append_import_job_log(job_id, f"queued import for {hf_meta['repo_id']} split={hf_meta['split']}")
    return job_id


def run_hf_import_job(job_id: str) -> None:
    job = load_import_job(job_id)
    slug = job["slug"]
    try:
        update_import_job(job_id, status="downloading")
        append_import_job_log(job_id, "downloading from Hugging Face Hub")
        config = job.get("hf_config") or None
        df = _load_hf_dataframe(job["repo_id"], config, job["hf_split"])
        update_import_job(job_id, status="converting", row_count=len(df))
        append_import_job_log(job_id, f"converting {len(df)} rows to CSV")
        mapping = job.get("column_mapping") or {}
        _validate_mapping_columns(mapping, [str(c) for c in df.columns])
        hf_meta = {
            "source": "huggingface",
            "hf_repo_id": job["repo_id"],
            "hf_config": job.get("hf_config") or "",
            "hf_split": job["hf_split"],
        }
        record = _persist_custom_dataset(
            df,
            slug=slug,
            title=job["title"],
            description=job["description"],
            column_mapping=mapping,
            source_format="huggingface",
            source_filename=f"{job['repo_id']}.hf",
            extra_meta=hf_meta,
        )
        clear_staged_hf(job.get("hf_staging_token"))
        update_import_job(
            job_id,
            status="done",
            dataset_id=record.id,
            row_count=len(df),
            error="",
        )
        append_import_job_log(job_id, f"done: {record.id}")
    except Exception as exc:
        update_import_job(job_id, status="failed", error=str(exc))
        append_import_job_log(job_id, f"failed: {exc}")
        dataset_dir = CUSTOM_DIR / slug
        if dataset_dir.is_dir() and slug not in _load_registry():
            shutil.rmtree(dataset_dir, ignore_errors=True)
        raise


def save_custom_dataset_from_hf_sync(
    hf_meta: dict[str, Any],
    *,
    hf_staging_token: str | None = None,
    title: str,
    description: str,
    slug: str,
    column_mapping: dict[str, Any],
    metadata_csv: str = "",
) -> DatasetRecord:
    estimated_bytes = hf_meta.get("estimated_bytes")
    _check_hf_size_limit(estimated_bytes)
    if should_use_background_import(estimated_bytes):
        raise DatasetError(
            f"dataset is too large for synchronous import ({_format_bytes(estimated_bytes)}); "
            "use background import"
        )
    if estimated_bytes:
        _check_disk_space(int(estimated_bytes))

    config_name = hf_meta.get("config") or None
    if config_name == "":
        config_name = None
    df = _load_hf_dataframe(hf_meta["repo_id"], config_name, hf_meta["split"])
    mapping = _parse_column_mapping(column_mapping, metadata_csv=metadata_csv)
    columns = [str(c) for c in df.columns]
    _validate_mapping_columns(mapping, columns)
    clean_slug = slugify(slug) or slugify(hf_meta["repo_id"].split("/")[-1]) or "hf-dataset"
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", clean_slug):
        raise DatasetError("slug must contain only lowercase letters, digits, _ and -")
    registry = _load_registry()
    if clean_slug in registry:
        raise DatasetConflictError(f"dataset slug already exists: {clean_slug}")

    extra_meta = {
        "source": "huggingface",
        "hf_repo_id": hf_meta["repo_id"],
        "hf_config": hf_meta.get("config") or "",
        "hf_split": hf_meta["split"],
    }
    try:
        record = _persist_custom_dataset(
            df,
            slug=clean_slug,
            title=title.strip() or clean_slug,
            description=description.strip(),
            column_mapping=mapping,
            source_format="huggingface",
            source_filename=f"{hf_meta['repo_id']}.hf",
            extra_meta=extra_meta,
        )
    finally:
        clear_staged_hf(hf_staging_token)
    return record


def _persist_custom_dataset(
    df: pd.DataFrame,
    *,
    slug: str,
    title: str,
    description: str,
    column_mapping: dict[str, Any],
    source_format: str,
    source_filename: str,
    extra_meta: dict[str, Any] | None = None,
) -> DatasetRecord:
    if df.empty:
        raise DatasetError("dataset has no rows")
    columns = [str(c) for c in df.columns]
    dataset_dir = CUSTOM_DIR / slug
    dataset_dir.mkdir(parents=True, exist_ok=False)
    data_csv = dataset_dir / "data.csv"
    meta_path = dataset_dir / "meta.json"
    benchmark_key = f"custom_{slug}"

    try:
        df.to_csv(data_csv, index=False, encoding="utf-8")
        meta: dict[str, Any] = {
            "slug": slug,
            "title": title,
            "description": description,
            "source_format": source_format,
            "source_filename": source_filename,
            "column_mapping": column_mapping,
            "columns": columns,
            "row_count": len(df),
            "benchmark_key": benchmark_key,
            "created_at": _iso_now(),
        }
        if extra_meta:
            meta.update(extra_meta)
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        registry = _load_registry()
        registry[slug] = {
            "title": meta["title"],
            "description": meta["description"],
            "path": slug,
            "benchmark_key": benchmark_key,
            "row_count": len(df),
            "columns": columns,
            "source_format": source_format,
            "column_mapping": column_mapping,
        }
        _save_registry(registry)
    except Exception:
        if dataset_dir.is_dir():
            shutil.rmtree(dataset_dir, ignore_errors=True)
        raise

    return get_dataset(f"custom:{slug}")


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

    return _persist_custom_dataset(
        df,
        slug=clean_slug,
        title=title.strip() or clean_slug,
        description=description.strip(),
        column_mapping=mapping,
        source_format=fmt,
        source_filename=filename,
    )


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
