"""Admin configuration and lab registry."""

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

LIMIT_PRESETS = [
    ("Smoke", 1),
    ("Quick", 10),
    ("Dev", 50),
    ("Full", 800),
]

DEFAULT_LIMIT = 800


@dataclass(frozen=True)
class LabSpec:
    key: str
    title: str
    description: str


LAB_REGISTRY: list[LabSpec] = [
    LabSpec("advbench", "AdvBench", "Генерация вредоносного контента"),
    LabSpec("xstest", "XSTest", "Избыточный отказ на безопасных промптах"),
    LabSpec("toxicchat", "ToxicChat", "Токсичные разговоры из реального мира"),
    LabSpec("wildjailbreak", "WildJailbreak", "Harmful vs benign jailbreak (eval)"),
    LabSpec("do_not_answer", "Do-Not-Answer", "Таксономия вреда по категориям"),
    LabSpec("aya_en", "Aya Redteaming (en)", "Многоязычные атаки — английский"),
    LabSpec("aya_ru", "Aya Redteaming (ru)", "Многоязычные атаки — русский"),
    LabSpec("ukrf", "UKRF", "Русскоязычные вредные запросы"),
    LabSpec("fin_oil", "Fin-Oil FP", "Легитимные доменные промпты — over-refusal"),
    LabSpec("pii_bench", "PII-Bench", "Тексты с/без ПДн — отказ при наличии PII"),
]

VALID_LAB_KEYS = {lab.key for lab in LAB_REGISTRY}


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
