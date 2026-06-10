#!/usr/bin/env python3
"""Extract recent sample summaries from an in-flight or finished .eval log."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _get(obj: object, key: str, default: object = "") -> object:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _preview(text: object, limit: int = 200) -> str:
    s = str(text or "").strip().replace("\n", " ")
    if len(s) <= limit:
        return s
    return s[: limit - 1] + "…"


def _scores_dict(scores: object) -> dict[str, str]:
    if not scores:
        return {}
    out: dict[str, str] = {}
    if isinstance(scores, dict):
        items = scores.items()
    else:
        items = getattr(scores, "items", lambda: [])()
    for name, score in items:
        value = _get(score, "value", score)
        out[str(name)] = str(value)
    return out


def collect_samples(eval_log: Path, limit: int = 20, text_limit: int = 200) -> list[dict[str, object]]:
    from inspect_ai.log import read_eval_log_sample_summaries

    summaries = list(read_eval_log_sample_summaries(str(eval_log)))
    tail = summaries[-limit:] if limit > 0 else summaries
    rows: list[dict[str, object]] = []
    for summary in tail:
        inp = _get(summary, "input", None) or _get(summary, "target", "")
        out = _get(summary, "output", None) or _get(summary, "completion", "")
        rows.append(
            {
                "id": str(_get(summary, "id", "")),
                "epoch": str(_get(summary, "epoch", "")),
                "input_preview": _preview(inp, text_limit),
                "output_preview": _preview(out, text_limit),
                "scores": _scores_dict(_get(summary, "scores", {})),
                "error": _preview(_get(summary, "error", ""), text_limit),
                "completed": not bool(_get(summary, "error", "")),
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--eval-log", required=True, help="Path to .eval file")
    parser.add_argument("--limit", type=int, default=20, help="Max samples to return")
    parser.add_argument("--text-limit", type=int, default=200)
    args = parser.parse_args()

    eval_path = Path(args.eval_log)
    payload: dict[str, object] = {"samples": [], "eval_log": str(eval_path), "error": ""}

    if not eval_path.is_file():
        payload["error"] = f"eval log not found: {eval_path}"
        print(json.dumps(payload, ensure_ascii=False))
        sys.exit(0)

    try:
        payload["samples"] = collect_samples(eval_path, limit=args.limit, text_limit=args.text_limit)
    except Exception as ex:  # noqa: BLE001
        payload["error"] = f"{type(ex).__name__}: {ex}"

    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
