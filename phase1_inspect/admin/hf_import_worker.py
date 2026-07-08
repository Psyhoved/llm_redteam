"""Worker entrypoint for background Hugging Face dataset imports."""

from __future__ import annotations

import argparse
import sys

from admin import datasets


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a background HF dataset import job.")
    parser.add_argument("--job-id", required=True, help="Import job id from admin UI")
    args = parser.parse_args(argv)
    try:
        datasets.run_hf_import_job(args.job_id)
    except Exception as exc:
        print(f"HF import failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
