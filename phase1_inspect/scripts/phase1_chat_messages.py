#!/usr/bin/env python3
"""Extract chat/message identifiers from Inspect AI eval logs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable


def obj_get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def build_chat_id(run_id: int | str, lab_name: str) -> str:
    return f"run:{run_id}:lab:{lab_name}"


def _content_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            text = obj_get(item, "text", None)
            if text is not None:
                parts.append(str(text))
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(parts)
    return str(content)


def _message_content(message: Any) -> str:
    text = obj_get(message, "text", None)
    if text is not None:
        return str(text)
    return _content_text(obj_get(message, "content", ""))


def _output_completion(output: Any) -> str:
    completion = obj_get(output, "completion", "")
    if completion:
        return str(completion)
    try:
        message = obj_get(output, "message", None)
    except Exception:  # noqa: BLE001 - ModelOutput.message raises on empty choices
        message = None
    return _message_content(message) if message is not None else ""


def _is_model_event(event: Any) -> bool:
    return obj_get(event, "event", "") == "model"


def _sample_key(sample: Any) -> str:
    sample_uuid = obj_get(sample, "uuid", None)
    if sample_uuid:
        return str(sample_uuid)
    return f"sample-{obj_get(sample, 'id', '')}-epoch-{obj_get(sample, 'epoch', '')}"


def extract_sample_messages(sample: Any) -> list[dict[str, Any]]:
    sample_key = _sample_key(sample)
    sample_id = str(obj_get(sample, "id", ""))
    sample_uuid = str(obj_get(sample, "uuid", "") or "")
    epoch = str(obj_get(sample, "epoch", "") or "")
    messages: list[dict[str, Any]] = []

    for event_index, event in enumerate(obj_get(sample, "events", []) or []):
        if not _is_model_event(event):
            continue

        model = str(obj_get(event, "model", "") or "")
        model_role = obj_get(event, "role", None)

        for message_index, message in enumerate(obj_get(event, "input", []) or []):
            messages.append(
                {
                    "message_id": f"{sample_key}:model-{event_index}:msg-{message_index}",
                    "role": str(obj_get(message, "role", "") or ""),
                    "content": _message_content(message),
                    "model": model,
                    "model_role": model_role,
                    "sample_id": sample_id,
                    "sample_uuid": sample_uuid,
                    "epoch": epoch,
                    "event_index": event_index,
                    "message_index": message_index,
                    "source": "input",
                    "error": str(obj_get(event, "error", "") or ""),
                }
            )

        completion = _output_completion(obj_get(event, "output", None))
        if completion:
            messages.append(
                {
                    "message_id": f"{sample_key}:model-{event_index}:completion",
                    "role": "assistant",
                    "content": completion,
                    "model": model,
                    "model_role": model_role,
                    "sample_id": sample_id,
                    "sample_uuid": sample_uuid,
                    "epoch": epoch,
                    "event_index": event_index,
                    "message_index": None,
                    "source": "output",
                    "error": str(obj_get(event, "error", "") or ""),
                }
            )

    return messages


def _read_summaries(eval_log: str) -> list[Any]:
    from inspect_ai.log import read_eval_log_sample_summaries

    return list(read_eval_log_sample_summaries(eval_log))


def _read_sample(eval_log: str, uuid: str) -> Any:
    from inspect_ai.log import read_eval_log_sample

    return read_eval_log_sample(eval_log, uuid=uuid, resolve_attachments=True)


def collect_chat_messages(
    eval_log: str,
    *,
    run_id: int,
    lab_name: str,
    summaries_reader: Callable[[str], list[Any]] = _read_summaries,
    sample_reader: Callable[[str, str], Any] = _read_sample,
) -> dict[str, Any]:
    messages: list[dict[str, Any]] = []
    for summary in summaries_reader(eval_log):
        sample_uuid = obj_get(summary, "uuid", None)
        if not sample_uuid:
            continue
        sample = sample_reader(eval_log, str(sample_uuid))
        messages.extend(extract_sample_messages(sample))

    return {
        "chat_id": build_chat_id(run_id, lab_name),
        "run_id": run_id,
        "lab_name": lab_name,
        "eval_log": eval_log,
        "messages": messages,
        "message_count": len(messages),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--eval-log", required=True)
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--lab-name", required=True)
    args = parser.parse_args()

    eval_path = Path(args.eval_log)
    payload: dict[str, Any]
    if not eval_path.is_file():
        payload = {
            "chat_id": build_chat_id(args.run_id, args.lab_name),
            "run_id": args.run_id,
            "lab_name": args.lab_name,
            "eval_log": str(eval_path),
            "messages": [],
            "message_count": 0,
            "error": f"eval log not found: {eval_path}",
        }
    else:
        try:
            payload = collect_chat_messages(
                str(eval_path), run_id=args.run_id, lab_name=args.lab_name
            )
        except Exception as ex:  # noqa: BLE001
            payload = {
                "chat_id": build_chat_id(args.run_id, args.lab_name),
                "run_id": args.run_id,
                "lab_name": args.lab_name,
                "eval_log": str(eval_path),
                "messages": [],
                "message_count": 0,
                "error": f"{type(ex).__name__}: {ex}",
            }

    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
