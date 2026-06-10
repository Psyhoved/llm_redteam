#!/usr/bin/env python3
"""Report in-flight benchmark sample progress from Inspect AI eval logs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


BENCHMARK_EVAL_NAMES: dict[str, list[str]] = {
    "do_not_answer": ["do-not-answer", "do_not_answer"],
    "aya_en": ["aya-redteaming", "aya_en"],
    "aya_ru": ["aya-redteaming", "aya_ru"],
    "fin_oil": ["fin-oil-fp", "fin_oil"],
    "pii_bench": ["pii-bench", "pii_bench"],
    "wildjailbreak": ["wildjailbreak"],
}


def eval_name_candidates(benchmark_name: str) -> list[str]:
    names = BENCHMARK_EVAL_NAMES.get(benchmark_name, [benchmark_name])
    if benchmark_name not in names:
        names = [benchmark_name, *names]
    seen: set[str] = set()
    out: list[str] = []
    for name in names:
        if name not in seen:
            seen.add(name)
            out.append(name)
    return out


def find_newest_eval_log(base_dir: Path, benchmark_name: str) -> Path | None:
    logs_dir = base_dir / "logs"
    if not logs_dir.is_dir():
        return None
    matches: list[Path] = []
    for eval_name in eval_name_candidates(benchmark_name):
        pattern = f"*_{eval_name}_*.eval"
        matches.extend(logs_dir.glob(pattern))
    if not matches:
        return None
    matches = sorted(set(matches), key=lambda p: p.stat().st_mtime)
    return matches[-1]


def dataset_size(eval_log: Path) -> int | None:
    from inspect_ai.log import read_eval_log

    log = read_eval_log(str(eval_log))
    dataset = getattr(log.eval, "dataset", None)
    if dataset is None:
        return None
    total = getattr(dataset, "samples", None)
    if isinstance(total, int):
        return total
    sample_list = getattr(dataset, "sample_list", None)
    if sample_list is not None:
        return len(sample_list)
    return None


def count_samples(eval_log: Path, limit: int | None) -> tuple[int, int]:
    from inspect_ai.log import read_eval_log_sample_summaries

    summaries = list(read_eval_log_sample_summaries(str(eval_log)))
    samples_done = len(summaries)
    ds_total = dataset_size(eval_log)
    if limit is not None and limit > 0:
        if ds_total is not None:
            samples_total = min(limit, ds_total)
        else:
            samples_total = limit
    elif ds_total is not None:
        samples_total = ds_total
    else:
        samples_total = samples_done
    return samples_done, samples_total


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="", help="unused; kept for CLI symmetry")
    parser.add_argument("--run-id", type=int, default=None, help="unused; kept for CLI symmetry")
    parser.add_argument("--benchmark-name", required=True)
    parser.add_argument("--base-dir", required=True)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    base_dir = Path(args.base_dir)
    payload: dict[str, object] = {
        "samples_done": 0,
        "samples_total": args.limit or 0,
        "eval_log": "",
        "error": "",
    }

    try:
        eval_log = find_newest_eval_log(base_dir, args.benchmark_name)
        if eval_log is None:
            payload["error"] = (
                f"no eval log matching *_{args.benchmark_name}_*.eval in {base_dir / 'logs'}"
            )
            print(json.dumps(payload, ensure_ascii=False))
            return

        samples_done, samples_total = count_samples(eval_log, args.limit)
        payload["samples_done"] = samples_done
        payload["samples_total"] = samples_total
        payload["eval_log"] = str(eval_log)
    except Exception as ex:  # noqa: BLE001
        payload["error"] = f"{type(ex).__name__}: {ex}"
        print(json.dumps(payload, ensure_ascii=False))
        return

    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
