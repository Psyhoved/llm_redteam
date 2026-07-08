from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest


RUN_PATH = (
    Path(__file__).resolve().parents[1]
    / "labs"
    / "lab1_owasp_top10"
    / "run.py"
)


def load_run_module(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=object))
    monkeypatch.setitem(
        sys.modules,
        "dotenv",
        types.SimpleNamespace(load_dotenv=lambda *_args, **_kwargs: False),
    )
    monkeypatch.setitem(
        sys.modules,
        "deepteam",
        types.SimpleNamespace(red_team=lambda **_kwargs: None),
    )
    monkeypatch.setitem(
        sys.modules,
        "deepteam.frameworks",
        types.SimpleNamespace(OWASPTop10=object),
    )
    monkeypatch.setitem(
        sys.modules,
        "deepeval.models",
        types.SimpleNamespace(DeepEvalBaseLLM=object),
    )
    monkeypatch.setitem(
        sys.modules,
        "deepteam.vulnerabilities",
        types.SimpleNamespace(PromptLeakage=object),
    )

    spec = importlib.util.spec_from_file_location("owasp_lab_run", RUN_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_openrouter_base_url_env_sets_role_endpoint_defaults(monkeypatch):
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://router.example/v1")
    module = load_run_module(monkeypatch)

    args = module.build_arg_parser().parse_args([])

    assert args.target_base_url == "https://router.example/v1"
    assert args.attacker_base_url == "https://router.example/v1"
    assert args.judge_base_url == "https://router.example/v1"


def test_missing_base_urls_fail_without_hardcoded_openrouter_fallback(monkeypatch):
    for name in (
        "OPENROUTER_BASE_URL",
        "TARGET_BASE_URL",
        "ATTACKER_BASE_URL",
        "JUDGE_BASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    module = load_run_module(monkeypatch)

    args = module.build_arg_parser().parse_args([])

    with pytest.raises(SystemExit, match="OPENROUTER_BASE_URL"):
        module.validate_base_urls(args)
