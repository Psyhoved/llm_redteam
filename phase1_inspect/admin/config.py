"""Admin configuration and benchmark registry."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PHASE1_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = PHASE1_DIR.parent
ENV_FILE = REPO_ROOT / ".env"
DEFAULT_LOG_DB = PHASE1_DIR / "logs" / "phase1_runs.sqlite"
LOGS_DIR = PHASE1_DIR / "logs"
LAUNCH_META_DIR = LOGS_DIR / "admin_launches"
METRICS_DIR = PHASE1_DIR / "reports" / "phase1_metrics"
PYTHON_BIN = PHASE1_DIR / ".venv" / "bin" / "python"
ADMIN_PORT = int(os.environ.get("PHASE1_ADMIN_PORT", "8080"))
INSPECT_VIEW_PORT = int(os.environ.get("PHASE1_INSPECT_VIEW_PORT", "7575"))
INSPECT_VIEW_URL = os.environ.get(
    "PHASE1_INSPECT_VIEW_URL", f"http://127.0.0.1:{INSPECT_VIEW_PORT}"
)

LIMIT_PRESETS = [
    ("Smoke", 1),
    ("Quick", 10),
    ("Dev", 50),
    ("Full", 800),
]

DEFAULT_LIMIT = 800


@dataclass(frozen=True)
class BenchmarkSpec:
    key: str
    title: str
    description: str


BENCHMARK_REGISTRY: list[BenchmarkSpec] = [
    BenchmarkSpec("advbench", "AdvBench", "Генерация вредоносного контента"),
    BenchmarkSpec("xstest", "XSTest", "Избыточный отказ на безопасных промптах"),
    BenchmarkSpec("toxicchat", "ToxicChat", "Полный train + test: toxic/jailbreak и benign"),
    BenchmarkSpec("wildjailbreak", "WildJailbreak", "Harmful vs benign jailbreak (eval)"),
    BenchmarkSpec("do_not_answer", "Do-Not-Answer", "Таксономия вреда по категориям"),
    BenchmarkSpec("aya_en", "Aya Redteaming (en)", "Многоязычные атаки — английский"),
    BenchmarkSpec("aya_ru", "Aya Redteaming (ru)", "Многоязычные атаки — русский"),
    BenchmarkSpec("ukrf", "UKRF", "Русскоязычные вредные запросы"),
    BenchmarkSpec("fin_oil", "Fin-Oil FP", "Легитимные доменные промпты — over-refusal"),
    BenchmarkSpec("pii_bench", "PII-Bench", "Тексты с/без ПДн — отказ при наличии PII"),
]

VALID_BENCHMARK_KEYS = {bench.key for bench in BENCHMARK_REGISTRY}


def custom_benchmark_specs() -> list[BenchmarkSpec]:
    """Load user-uploaded datasets as runnable custom benchmarks."""
    try:
        from admin import datasets as datasets_mod

        return [
            BenchmarkSpec(
                key=record.benchmark_key or f"custom_{record.slug}",
                title=record.title,
                description=f"{record.description} (пользовательский датасет)",
            )
            for record in datasets_mod.list_datasets()
            if record.kind == "custom" and record.on_disk and record.benchmark_key
        ]
    except Exception:
        return []


def all_benchmarks() -> list[BenchmarkSpec]:
    return [*BENCHMARK_REGISTRY, *custom_benchmark_specs()]


def valid_benchmark_keys() -> set[str]:
    keys = set(VALID_BENCHMARK_KEYS)
    try:
        from admin import datasets as datasets_mod

        keys.update(datasets_mod.custom_benchmark_keys())
    except Exception:
        pass
    return keys


def read_env_defaults() -> dict[str, str]:
    """Read non-secret Phase 1 defaults from .env for form placeholders."""
    keys = ("TARGET_MODEL", "GRADER_MODEL", "PHASE1_MAX_CONNECTIONS")
    defaults: dict[str, str] = {}
    if not ENV_FILE.is_file():
        return defaults
    for line in ENV_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        name = name.strip()
        value = value.strip().strip('"').strip("'")
        if name in keys and value:
            defaults[name] = value
    return defaults
