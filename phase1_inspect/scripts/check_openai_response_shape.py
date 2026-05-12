#!/usr/bin/env python3
"""Safely inspect the OpenAI-compatible chat response shape.

This script intentionally does not print API keys or full model responses. It
prints only types and presence of fields that matter for Inspect AI compatibility.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI


def service_model_name(model: str) -> str:
    prefix = "openai-api/myproxy/"
    if model.startswith(prefix):
        return model[len(prefix) :]
    return model


def has_attr(obj: Any, name: str) -> bool:
    return getattr(obj, name, None) is not None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", default=str(Path(__file__).resolve().parents[2] / ".env"))
    parser.add_argument("--model", default="")
    parser.add_argument("--base-url", default="")
    args = parser.parse_args()

    load_dotenv(args.env_file)

    target_model = args.model or os.getenv("TARGET_MODEL", "")
    if not target_model:
        print("ERROR: TARGET_MODEL is not set (or pass --model)", file=sys.stderr)
        sys.exit(2)

    base_url = args.base_url or os.getenv("MYPROXY_BASE_URL") or os.getenv("TARGET_BASE_URL") or ""
    api_key = os.getenv("MYPROXY_API_KEY") or os.getenv("TARGET_API_KEY") or os.getenv("OPENROUTER_API_KEY") or ""
    if not base_url:
        print("ERROR: MYPROXY_BASE_URL/TARGET_BASE_URL is not set (or pass --base-url)", file=sys.stderr)
        sys.exit(2)
    if not api_key:
        print("ERROR: no API key env var found (MYPROXY_API_KEY/TARGET_API_KEY/OPENROUTER_API_KEY)", file=sys.stderr)
        sys.exit(2)

    model = service_model_name(target_model)
    client = OpenAI(base_url=base_url, api_key=api_key)
    completion = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": "Reply with exactly: ok"}],
        max_tokens=16,
    )

    choice = completion.choices[0]
    message = choice.message
    content = message.content

    print(f"base_url_set={bool(base_url)}")
    print(f"target_model={target_model}")
    print(f"service_model={model}")
    print(f"finish_reason={choice.finish_reason}")
    print(f"message.content.type={type(content).__name__}")
    print(f"message.content.is_str={isinstance(content, str)}")
    print(f"has.reasoning={has_attr(message, 'reasoning')}")
    print(f"has.reasoning_content={has_attr(message, 'reasoning_content')}")
    print(f"has.reasoning_details={has_attr(message, 'reasoning_details')}")

    if not isinstance(content, str):
        print(
            "ERROR: choices[0].message.content is not a string. "
            "Inspect AI's OpenAI-compatible text path expects string content.",
            file=sys.stderr,
        )
        sys.exit(1)

    print("OK: choices[0].message.content is a string")


if __name__ == "__main__":
    main()
