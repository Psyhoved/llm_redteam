"""Inspect AI hooks: tag outbound LLM requests for AIDR / Langfuse.

Injects OpenWebUI-compatible tracing fields into GenerateConfig.extra_body so
MYPROXY (and OpenRouter graders) can separate Inspect traffic from real chats.
"""

from __future__ import annotations

import os
from typing import Any

from inspect_ai.hooks import BeforeModelGenerate, Hooks, hooks
from inspect_ai.solver._task_state import sample_state

AIDR_USER_ID = "inspect-ai"
AIDR_USERNAME = "inspect-ai"
AIDR_REQUEST_TYPE = "inspect_ai"
ENV_RUN_ID = "INSPECT_AIDR_RUN_ID"
ENV_LAB_NAME = "INSPECT_AIDR_LAB_NAME"


def build_chat_id(run_id: str, lab_name: str) -> str:
    return f"run:{run_id}:lab:{lab_name}"


def build_openwebui_extra(
    *,
    run_id: str,
    lab_name: str,
    sample_uuid: str,
) -> dict[str, Any]:
    """Build the `_openwebui` object for an Inspect AI model request body."""
    return {
        "user_id": AIDR_USER_ID,
        "username": AIDR_USERNAME,
        "session_id": run_id,
        "chat_id": build_chat_id(run_id, lab_name),
        "message_id": sample_uuid,
        "request_type": AIDR_REQUEST_TYPE,
    }


def resolve_run_id() -> str:
    value = (os.environ.get(ENV_RUN_ID) or "").strip()
    return value or "local"


def resolve_lab_name(task_name: str | None) -> str:
    value = (os.environ.get(ENV_LAB_NAME) or "").strip()
    if value:
        return value
    return (task_name or "").strip() or "unknown"


def resolve_sample_uuid(fallback: str | None) -> str:
    state = sample_state()
    if state is not None and getattr(state, "uuid", None):
        return str(state.uuid)
    return (fallback or "").strip() or "unknown"


def merge_openwebui_into_extra_body(
    extra_body: dict[str, Any] | None,
    openwebui: dict[str, Any],
) -> dict[str, Any]:
    """Return a new extra_body dict with `_openwebui` set, preserving other keys."""
    merged = dict(extra_body or {})
    merged["_openwebui"] = openwebui
    return merged


@hooks(
    name="aidr_openwebui",
    description="Inject AIDR/OpenWebUI tracing fields into Inspect model requests",
)
class AidrOpenWebuiHooks(Hooks):
    async def on_before_model_generate(self, data: BeforeModelGenerate) -> None:
        openwebui = build_openwebui_extra(
            run_id=resolve_run_id(),
            lab_name=resolve_lab_name(data.task_name),
            sample_uuid=resolve_sample_uuid(data.sample_id),
        )
        data.config.extra_body = merge_openwebui_into_extra_body(
            data.config.extra_body,
            openwebui,
        )
