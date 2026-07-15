"""Tests for AIDR / OpenWebUI tracing hooks on Inspect model requests."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.solver._task_state import TaskState, set_sample_state
from inspect_ai.model import ModelName

import inspect_aidr_hooks as aidr
from inspect_aidr_hooks import AidrOpenWebuiHooks


def test_build_openwebui_extra_shape_and_values() -> None:
    payload = aidr.build_openwebui_extra(
        run_id="101",
        lab_name="advbench",
        sample_uuid="sample-uuid-abc",
    )

    assert payload == {
        "user_id": "inspect-ai",
        "username": "inspect-ai",
        "session_id": "101",
        "chat_id": "run:101:lab:advbench",
        "message_id": "sample-uuid-abc",
        "request_type": "inspect_ai",
    }


def test_merge_openwebui_preserves_existing_extra_body_keys() -> None:
    existing = {"reasoning": {"effort": "high"}, "other": 1}
    openwebui = aidr.build_openwebui_extra(
        run_id="7",
        lab_name="xstest",
        sample_uuid="u1",
    )

    merged = aidr.merge_openwebui_into_extra_body(existing, openwebui)

    assert merged["reasoning"] == {"effort": "high"}
    assert merged["other"] == 1
    assert merged["_openwebui"] == openwebui
    assert existing == {"reasoning": {"effort": "high"}, "other": 1}


def test_resolve_run_id_and_lab_name_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(aidr.ENV_RUN_ID, "42")
    monkeypatch.setenv(aidr.ENV_LAB_NAME, "aya_en")
    assert aidr.resolve_run_id() == "42"
    assert aidr.resolve_lab_name("ignored_task") == "aya_en"


def test_resolve_fallbacks_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(aidr.ENV_RUN_ID, raising=False)
    monkeypatch.delenv(aidr.ENV_LAB_NAME, raising=False)
    assert aidr.resolve_run_id() == "local"
    assert aidr.resolve_lab_name("advbench") == "advbench"
    assert aidr.resolve_lab_name(None) == "unknown"


def test_resolve_sample_uuid_prefers_task_state() -> None:
    state = TaskState(
        model=ModelName("mockllm/model"),
        sample_id=1,
        epoch=1,
        input="hi",
        messages=[],
        sample_uuid="state-uuid-xyz",
    )
    set_sample_state(state)
    try:
        assert aidr.resolve_sample_uuid("active-sample-id") == "state-uuid-xyz"
    finally:
        set_sample_state(None)  # type: ignore[arg-type]


def test_resolve_sample_uuid_falls_back_when_no_state() -> None:
    set_sample_state(None)  # type: ignore[arg-type]
    assert aidr.resolve_sample_uuid("active-sample-id") == "active-sample-id"
    assert aidr.resolve_sample_uuid(None) == "unknown"


def test_hook_merges_openwebui_into_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(aidr.ENV_RUN_ID, "95")
    monkeypatch.setenv(aidr.ENV_LAB_NAME, "fin_oil")

    state = TaskState(
        model=ModelName("mockllm/model"),
        sample_id=3,
        epoch=1,
        input="prompt",
        messages=[],
        sample_uuid="eval-sample-uuid",
    )
    set_sample_state(state)

    config = GenerateConfig(extra_body={"keep": True})
    data = SimpleNamespace(
        task_name="fin_oil_fp",
        sample_id="active-id-should-not-win",
        config=config,
    )

    try:
        asyncio.run(AidrOpenWebuiHooks().on_before_model_generate(data))  # type: ignore[arg-type]
    finally:
        set_sample_state(None)  # type: ignore[arg-type]

    assert config.extra_body is not None
    assert config.extra_body["keep"] is True
    assert config.extra_body["_openwebui"] == {
        "user_id": "inspect-ai",
        "username": "inspect-ai",
        "session_id": "95",
        "chat_id": "run:95:lab:fin_oil",
        "message_id": "eval-sample-uuid",
        "request_type": "inspect_ai",
    }


def test_phase1_safety_metrics_registers_aidr_hooks() -> None:
    from inspect_ai.hooks._hooks import get_all_hooks
    from inspect_ai._util.registry import registry_info

    import phase1_safety_metrics  # noqa: F401

    names = {registry_info(h).name for h in get_all_hooks()}
    assert any(name.endswith("aidr_openwebui") or "aidr_openwebui" in name for name in names)
