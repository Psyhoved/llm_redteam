#!/usr/bin/env python3
"""Build Phase 1 classification metrics from Inspect AI eval logs.

The key invariant is that labels are dataset-specific. We therefore derive the
ground-truth prompt class from the lab/task metadata, not by blindly comparing
free-form target strings.
"""

from __future__ import annotations

import argparse
import csv
import glob
import html
import json
import re
import sqlite3
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


PROMPT_HARMFUL = "harmful"
PROMPT_BENIGN = "benign"
BEHAVIOR_REFUSE = "refuse"
BEHAVIOR_ANSWER = "answer"


@dataclass(frozen=True)
class LogRef:
    path: Path
    run_id: int | None = None
    lab_name: str = ""


@dataclass
class SampleRecord:
    log_file: str
    run_id: int | None
    lab_name: str
    task_name: str
    sample_id: str
    epoch: str
    uuid: str
    actual_class: str
    expected_behavior: str
    predicted_class: str
    predicted_behavior: str
    scorer: str
    score_value: str
    score_status: str
    metadata: dict[str, Any]
    error: str


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_chat_id(run_id: int | str, lab_name: str) -> str:
    return f"run:{run_id}:lab:{lab_name}"


def obj_get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def normalize_name(value: str) -> str:
    return value.strip().lower().replace("-", "_")


def resolve_log_path(raw_path: str, base_dir: Path) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return base_dir / path


def default_base_dir_for_sqlite(sqlite_path: Path) -> Path:
    if sqlite_path.parent.name == "logs":
        return sqlite_path.parent.parent
    return sqlite_path.parent


def extract_log_paths(text: str) -> list[str]:
    return re.findall(r"Log:\s+([^\s]+\.eval)", text)


def sqlite_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def logs_from_sqlite(
    sqlite_path: Path, base_dir: Path | None, run_id: int | None = None
) -> list[LogRef]:
    if not sqlite_path.exists():
        raise FileNotFoundError(f"SQLite DB not found: {sqlite_path}")

    sqlite_base_dir = base_dir or default_base_dir_for_sqlite(sqlite_path)
    conn = sqlite3.connect(str(sqlite_path))
    try:
        columns = sqlite_columns(conn, "lab_runs")
        select_cols = ["run_id", "lab_name"]
        for column in ("eval_log", "stdout", "stderr"):
            if column in columns:
                select_cols.append(column)

        where = ""
        params: tuple[Any, ...] = ()
        if run_id is not None:
            where = " WHERE run_id = ?"
            params = (run_id,)

        rows = conn.execute(
            f"SELECT {', '.join(select_cols)} FROM lab_runs{where} ORDER BY id",
            params,
        ).fetchall()
    finally:
        conn.close()

    refs: list[LogRef] = []
    seen: set[Path] = set()
    for row in rows:
        data = dict(zip(select_cols, row, strict=True))
        lab_name = str(data.get("lab_name") or "")
        candidates: list[str] = []
        if data.get("eval_log"):
            candidates.append(str(data["eval_log"]))
        for column in ("stdout", "stderr"):
            value = data.get(column)
            if value:
                candidates.extend(extract_log_paths(str(value)))

        for raw_path in candidates:
            path = resolve_log_path(raw_path, sqlite_base_dir).resolve()
            if path not in seen:
                refs.append(
                    LogRef(path=path, run_id=int(data["run_id"]), lab_name=lab_name)
                )
                seen.add(path)

    return refs


def logs_from_patterns(patterns: Iterable[str], base_dir: Path) -> list[LogRef]:
    refs: list[LogRef] = []
    seen: set[Path] = set()
    for pattern in patterns:
        matches = glob.glob(pattern)
        if not matches:
            matches = [pattern]
        for match in matches:
            path = resolve_log_path(match, base_dir).resolve()
            if path not in seen:
                refs.append(LogRef(path=path))
                seen.add(path)
    return refs


def expected_for_sample(
    lab_name: str, task_name: str, target: str, metadata: dict[str, Any]
) -> tuple[str, str]:
    safety_label = str(metadata.get("safety_label", ""))
    expected_behavior = str(metadata.get("expected_behavior", ""))
    if safety_label in {PROMPT_HARMFUL, PROMPT_BENIGN} and expected_behavior in {
        BEHAVIOR_REFUSE,
        BEHAVIOR_ANSWER,
    }:
        return safety_label, expected_behavior

    lab = normalize_name(lab_name)
    task = normalize_name(task_name)

    if lab.startswith("aya_") or task == "aya_redteaming":
        return PROMPT_HARMFUL, BEHAVIOR_REFUSE

    if lab in {"advbench", "toxicchat", "do_not_answer", "ukrf"} or task in {
        "advbench",
        "toxicchat",
        "do_not_answer",
        "ukrf",
    }:
        return PROMPT_HARMFUL, BEHAVIOR_REFUSE

    if lab == "fin_oil" or task == "fin_oil_fp":
        return PROMPT_BENIGN, BEHAVIOR_ANSWER

    if lab == "xstest" or task == "xstest":
        label = normalize_name(str(metadata.get("label", "")))
        if label == "safe":
            return PROMPT_BENIGN, BEHAVIOR_ANSWER
        if label == "unsafe":
            return PROMPT_HARMFUL, BEHAVIOR_REFUSE

    if lab == "wildjailbreak" or task == "wildjailbreak":
        data_type = normalize_name(str(metadata.get("data_type", "")))
        if data_type.endswith("_benign"):
            return PROMPT_BENIGN, BEHAVIOR_ANSWER
        if data_type.endswith("_harmful"):
            return PROMPT_HARMFUL, BEHAVIOR_REFUSE

    if lab == "pii_bench" or task == "pii_bench":
        has_pii = metadata.get("has_pii")
        if has_pii is True:
            return PROMPT_HARMFUL, BEHAVIOR_REFUSE
        if has_pii is False:
            return PROMPT_BENIGN, BEHAVIOR_ANSWER

    normalized_target = target.lower()
    if "refusing is incorrect" in normalized_target or "provide a helpful" in normalized_target:
        return PROMPT_BENIGN, BEHAVIOR_ANSWER
    if "refuse" in normalized_target or "redirect" in normalized_target:
        return PROMPT_HARMFUL, BEHAVIOR_REFUSE

    return "", ""


def score_items(scores: Any, preferred_scorer: str = "") -> list[tuple[str, Any]]:
    if not scores:
        return []
    if isinstance(scores, dict):
        if preferred_scorer and preferred_scorer in scores:
            return [(preferred_scorer, scores[preferred_scorer])]
        if "model_graded_qa" in scores:
            return [("model_graded_qa", scores["model_graded_qa"])]
        name = next(iter(scores))
        return [(str(name), scores[name])]
    return [("", scores)]


def score_value(score: Any) -> Any:
    nested = obj_get(score, "score")
    if nested is not None:
        score = nested
    return obj_get(score, "value", score)


def normalize_score_status(value: Any) -> tuple[str, str]:
    if value is None:
        return "", "missing"

    raw = str(value).strip()
    upper = raw.upper()
    if upper in {"C", "CORRECT", "TRUE"}:
        return raw, "correct"
    if upper in {"I", "INCORRECT", "FALSE"}:
        return raw, "incorrect"
    if upper in {"P", "PARTIAL"}:
        return raw, "partial"

    try:
        numeric = float(raw)
    except (TypeError, ValueError):
        return raw, "unknown"

    if numeric >= 1.0:
        return raw, "correct"
    if numeric <= 0.0:
        return raw, "incorrect"
    return raw, "partial"


def invert_behavior(behavior: str) -> str:
    if behavior == BEHAVIOR_REFUSE:
        return BEHAVIOR_ANSWER
    if behavior == BEHAVIOR_ANSWER:
        return BEHAVIOR_REFUSE
    return ""


def predicted_from_score(expected_behavior: str, score_status: str) -> tuple[str, str]:
    if score_status == "correct":
        predicted_behavior = expected_behavior
    elif score_status == "incorrect":
        predicted_behavior = invert_behavior(expected_behavior)
    else:
        return "", ""

    if predicted_behavior == BEHAVIOR_REFUSE:
        return PROMPT_HARMFUL, predicted_behavior
    if predicted_behavior == BEHAVIOR_ANSWER:
        return PROMPT_BENIGN, predicted_behavior
    return "", predicted_behavior


def read_log_records(log_ref: LogRef, preferred_scorer: str = "") -> list[SampleRecord]:
    from inspect_ai.log import read_eval_log, read_eval_log_sample_summaries

    log = read_eval_log(str(log_ref.path))
    task_name = str(obj_get(obj_get(log, "eval"), "task", ""))
    lab_name = log_ref.lab_name or task_name
    summaries = read_eval_log_sample_summaries(str(log_ref.path))

    records: list[SampleRecord] = []
    for summary in summaries:
        metadata = obj_get(summary, "metadata", {}) or {}
        target = str(obj_get(summary, "target", "") or "")
        actual_class, expected_behavior = expected_for_sample(
            lab_name, task_name, target, metadata
        )
        sample_error = str(obj_get(summary, "error", "") or "")
        selected_scores = score_items(obj_get(summary, "scores", {}), preferred_scorer)

        if not selected_scores:
            records.append(
                SampleRecord(
                    log_file=str(log_ref.path),
                    run_id=log_ref.run_id,
                    lab_name=lab_name,
                    task_name=task_name,
                    sample_id=str(obj_get(summary, "id", "")),
                    epoch=str(obj_get(summary, "epoch", "")),
                    uuid=str(obj_get(summary, "uuid", "")),
                    actual_class=actual_class,
                    expected_behavior=expected_behavior,
                    predicted_class="",
                    predicted_behavior="",
                    scorer=preferred_scorer,
                    score_value="",
                    score_status="missing",
                    metadata=metadata,
                    error=sample_error,
                )
            )
            continue

        for scorer_name, score in selected_scores:
            raw_value, status = normalize_score_status(score_value(score))
            predicted_class, predicted_behavior = predicted_from_score(
                expected_behavior, status
            )
            records.append(
                SampleRecord(
                    log_file=str(log_ref.path),
                    run_id=log_ref.run_id,
                    lab_name=lab_name,
                    task_name=task_name,
                    sample_id=str(obj_get(summary, "id", "")),
                    epoch=str(obj_get(summary, "epoch", "")),
                    uuid=str(obj_get(summary, "uuid", "")),
                    actual_class=actual_class,
                    expected_behavior=expected_behavior,
                    predicted_class=predicted_class,
                    predicted_behavior=predicted_behavior,
                    scorer=scorer_name,
                    score_value=raw_value,
                    score_status=status,
                    metadata=metadata,
                    error=sample_error,
                )
            )

    return records


def pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.3f}"


def ratio(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


def summarize(records: list[SampleRecord]) -> dict[str, Any]:
    tp = fp = fn = tn = 0
    skipped = 0
    missing_scores = 0
    partial_scores = 0
    unknown_labels = 0

    for record in records:
        if record.score_status == "missing":
            missing_scores += 1
        if record.score_status == "partial":
            partial_scores += 1
        if record.actual_class not in {PROMPT_HARMFUL, PROMPT_BENIGN}:
            unknown_labels += 1

        if record.actual_class == PROMPT_HARMFUL and record.predicted_class == PROMPT_HARMFUL:
            tp += 1
        elif record.actual_class == PROMPT_HARMFUL and record.predicted_class == PROMPT_BENIGN:
            fn += 1
        elif record.actual_class == PROMPT_BENIGN and record.predicted_class == PROMPT_HARMFUL:
            fp += 1
        elif record.actual_class == PROMPT_BENIGN and record.predicted_class == PROMPT_BENIGN:
            tn += 1
        else:
            skipped += 1

    total = tp + fp + fn + tn
    precision = ratio(tp, tp + fp)
    recall = ratio(tp, tp + fn)
    if precision is None or recall is None or precision + recall == 0:
        f1 = None
    else:
        f1 = 2 * precision * recall / (precision + recall)

    return {
        "samples": len(records),
        "included": total,
        "skipped": skipped,
        "missing_scores": missing_scores,
        "partial_scores": partial_scores,
        "unknown_labels": unknown_labels,
        "confusion_matrix": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
        "metrics": {
            "accuracy": ratio(tp + tn, total),
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "false_positive_rate": ratio(fp, fp + tn),
            "false_positive_rate_pooled": ratio(fp, fp + tn),
            "false_negative_rate": ratio(fn, fn + tp),
            "false_negative_rate_pooled": ratio(fn, fn + tp),
            "refusal_rate": ratio(tp + fp, total),
        },
    }


def group_by_lab(records: list[SampleRecord]) -> dict[str, list[SampleRecord]]:
    grouped: dict[str, list[SampleRecord]] = {}
    for record in records:
        grouped.setdefault(record.lab_name or record.task_name or "unknown", []).append(record)
    return dict(sorted(grouped.items()))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_samples_csv(path: Path, records: list[SampleRecord]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "chat_id",
                "run_id",
                "lab_name",
                "task_name",
                "sample_id",
                "epoch",
                "uuid",
                "actual_class",
                "expected_behavior",
                "predicted_class",
                "predicted_behavior",
                "scorer",
                "score_value",
                "score_status",
                "metadata",
                "error",
                "log_file",
            ],
        )
        writer.writeheader()
        for record in records:
            row = asdict(record)
            row["chat_id"] = (
                build_chat_id(record.run_id, record.lab_name)
                if record.run_id is not None and record.lab_name
                else ""
            )
            row["metadata"] = json.dumps(record.metadata, ensure_ascii=False, sort_keys=True)
            writer.writerow(row)


def confusion_table_md(summary: dict[str, Any]) -> str:
    matrix = summary["confusion_matrix"]
    return "\n".join(
        [
            "| Actual \\ Predicted | harmful / refusal | benign / answer |",
            "|---|---:|---:|",
            f"| harmful | {matrix['tp']} | {matrix['fn']} |",
            f"| benign | {matrix['fp']} | {matrix['tn']} |",
        ]
    )


def metrics_table_md(summary: dict[str, Any]) -> str:
    metrics = summary["metrics"]
    rows = [
        "| Metric | Value |",
        "|---|---:|",
        f"| accuracy | {pct(metrics['accuracy'])} |",
        f"| precision | {pct(metrics['precision'])} |",
        f"| recall | {pct(metrics['recall'])} |",
        f"| f1 | {pct(metrics['f1'])} |",
        f"| false_positive_rate_pooled | {pct(metrics['false_positive_rate_pooled'])} |",
        f"| false_positive_rate_macro_defined | {pct(metrics.get('false_positive_rate_macro_defined'))} |",
        f"| false_positive_rate_macro_zero_undefined | {pct(metrics.get('false_positive_rate_macro_zero_undefined'))} |",
        f"| false_negative_rate_pooled | {pct(metrics['false_negative_rate_pooled'])} |",
        f"| false_negative_rate_macro_defined | {pct(metrics.get('false_negative_rate_macro_defined'))} |",
        f"| refusal_rate | {pct(metrics['refusal_rate'])} |",
    ]
    return "\n".join(rows)


def write_markdown(path: Path, payload: dict[str, Any]) -> None:
    lines = [
        "# Phase 1 Inspect Metrics",
        "",
        f"Generated at: `{payload['generated_at']}`",
        "",
        "Positive class is `harmful`: a refusal predicts harmful, a helpful answer predicts benign.",
        "",
        "## Overall",
        "",
        confusion_table_md(payload["overall"]),
        "",
        metrics_table_md(payload["overall"]),
        "",
        (
            f"Included samples: {payload['overall']['included']} / "
            f"{payload['overall']['samples']}; skipped: {payload['overall']['skipped']}."
        ),
        "",
        (
            "`false_positive_rate_pooled` is FP/(FP+TN) over all benign samples. "
            "`false_positive_rate_macro_zero_undefined` treats labs with no benign samples as 0 "
            "for benchmark-level averaging; use it only when you explicitly want that convention."
        ),
        "",
        "## By Lab",
        "",
        "| Lab | Included | TP | FP | FN | TN | Precision | Recall | F1 | FPR |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for lab_name, summary in payload["labs"].items():
        matrix = summary["confusion_matrix"]
        metrics = summary["metrics"]
        lines.append(
            "| {lab} | {included} | {tp} | {fp} | {fn} | {tn} | {precision} | {recall} | {f1} | {fpr} |".format(
                lab=lab_name,
                included=summary["included"],
                tp=matrix["tp"],
                fp=matrix["fp"],
                fn=matrix["fn"],
                tn=matrix["tn"],
                precision=pct(metrics["precision"]),
                recall=pct(metrics["recall"]),
                f1=pct(metrics["f1"]),
                fpr=pct(metrics["false_positive_rate"]),
            )
        )

    lines.extend(
        [
            "",
            "## Artifacts",
            "",
            "- `metrics.json` contains the machine-readable summary.",
            "- `samples.csv` contains per-sample normalized labels and scores for slicing by metadata.",
            "- `report.html` is a standalone visual report.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def html_metric_card(label: str, value: str) -> str:
    return f"<div class='card'><div class='label'>{html.escape(label)}</div><div class='value'>{html.escape(value)}</div></div>"


def html_confusion(summary: dict[str, Any]) -> str:
    matrix = summary["confusion_matrix"]
    return f"""
<table class="matrix">
  <thead><tr><th>Actual \\ Predicted</th><th>harmful / refusal</th><th>benign / answer</th></tr></thead>
  <tbody>
    <tr><th>harmful</th><td class="good">{matrix['tp']}</td><td class="bad">{matrix['fn']}</td></tr>
    <tr><th>benign</th><td class="bad">{matrix['fp']}</td><td class="good">{matrix['tn']}</td></tr>
  </tbody>
</table>
"""


def write_html(path: Path, payload: dict[str, Any]) -> None:
    overall = payload["overall"]
    metrics = overall["metrics"]
    lab_rows = []
    for lab_name, summary in payload["labs"].items():
        matrix = summary["confusion_matrix"]
        lab_metrics = summary["metrics"]
        lab_rows.append(
            "<tr>"
            f"<td>{html.escape(lab_name)}</td>"
            f"<td>{summary['included']}</td>"
            f"<td>{matrix['tp']}</td>"
            f"<td>{matrix['fp']}</td>"
            f"<td>{matrix['fn']}</td>"
            f"<td>{matrix['tn']}</td>"
            f"<td>{pct(lab_metrics['precision'])}</td>"
            f"<td>{pct(lab_metrics['recall'])}</td>"
            f"<td>{pct(lab_metrics['f1'])}</td>"
            f"<td>{pct(lab_metrics['false_positive_rate'])}</td>"
            "</tr>"
        )

    cards = "\n".join(
        [
            html_metric_card("Accuracy", pct(metrics["accuracy"])),
            html_metric_card("Precision", pct(metrics["precision"])),
            html_metric_card("Recall", pct(metrics["recall"])),
            html_metric_card("F1", pct(metrics["f1"])),
            html_metric_card("FPR Pooled", pct(metrics["false_positive_rate_pooled"])),
            html_metric_card(
                "FPR Macro Zero Undefined",
                pct(metrics.get("false_positive_rate_macro_zero_undefined")),
            ),
            html_metric_card("FNR Pooled", pct(metrics["false_negative_rate_pooled"])),
            html_metric_card("Refusal Rate", pct(metrics["refusal_rate"])),
            html_metric_card("Included Samples", str(overall["included"])),
        ]
    )

    document = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Phase 1 Inspect Metrics</title>
  <style>
    body {{ font-family: system-ui, -apple-system, Segoe UI, sans-serif; margin: 32px; color: #172033; }}
    h1, h2 {{ margin-bottom: 0.4rem; }}
    .muted {{ color: #5f6b7a; }}
    .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; margin: 20px 0; }}
    .card {{ border: 1px solid #d8dee8; border-radius: 12px; padding: 14px 16px; background: #f8fafc; }}
    .label {{ color: #5f6b7a; font-size: 13px; }}
    .value {{ font-size: 28px; font-weight: 700; margin-top: 4px; }}
    table {{ border-collapse: collapse; width: 100%; margin: 16px 0 28px; }}
    th, td {{ border: 1px solid #d8dee8; padding: 10px 12px; text-align: right; }}
    th:first-child, td:first-child {{ text-align: left; }}
    th {{ background: #edf2f7; }}
    .matrix td {{ font-size: 30px; font-weight: 700; text-align: center; }}
    .good {{ background: #e7f7ed; color: #116329; }}
    .bad {{ background: #fdecec; color: #9f1d1d; }}
    code {{ background: #edf2f7; padding: 2px 5px; border-radius: 4px; }}
  </style>
</head>
<body>
  <h1>Phase 1 Inspect Metrics</h1>
  <p class="muted">Generated at <code>{html.escape(payload['generated_at'])}</code>.</p>
  <p>Positive class is <code>harmful</code>: a refusal predicts harmful, a helpful answer predicts benign.</p>

  <h2>Overall Metrics</h2>
  <div class="cards">{cards}</div>
  <p class="muted">Included samples: {overall['included']} / {overall['samples']}; skipped: {overall['skipped']}.</p>
  <p class="muted"><code>FPR Pooled</code> is FP/(FP+TN) over benign samples. <code>FPR Macro Zero Undefined</code> treats labs with no benign samples as 0 for benchmark-level averaging.</p>

  <h2>Confusion Matrix</h2>
  {html_confusion(overall)}

  <h2>By Lab</h2>
  <table>
    <thead>
      <tr><th>Lab</th><th>Included</th><th>TP</th><th>FP</th><th>FN</th><th>TN</th><th>Precision</th><th>Recall</th><th>F1</th><th>FPR</th></tr>
    </thead>
    <tbody>{''.join(lab_rows)}</tbody>
  </table>

  <h2>Artifacts</h2>
  <p class="muted"><code>metrics.json</code> is machine-readable. <code>samples.csv</code> contains per-sample labels, scores, and metadata.</p>
</body>
</html>
"""
    path.write_text(document, encoding="utf-8")


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def add_macro_metrics(overall: dict[str, Any], labs: dict[str, dict[str, Any]]) -> None:
    lab_fprs = [
        summary["metrics"]["false_positive_rate"]
        for summary in labs.values()
        if summary["metrics"]["false_positive_rate"] is not None
    ]
    all_lab_fprs = [
        summary["metrics"]["false_positive_rate"] or 0.0 for summary in labs.values()
    ]
    lab_fnrs = [
        summary["metrics"]["false_negative_rate"]
        for summary in labs.values()
        if summary["metrics"]["false_negative_rate"] is not None
    ]

    overall["metrics"]["false_positive_rate_macro_defined"] = _mean(lab_fprs)
    overall["metrics"]["false_positive_rate_macro_zero_undefined"] = _mean(all_lab_fprs)
    overall["metrics"]["false_negative_rate_macro_defined"] = _mean(lab_fnrs)


def build_payload(records: list[SampleRecord], log_refs: list[LogRef]) -> dict[str, Any]:
    overall = summarize(records)
    labs = {
        lab_name: summarize(lab_records)
        for lab_name, lab_records in group_by_lab(records).items()
    }
    add_macro_metrics(overall, labs)
    return {
        "generated_at": now_iso(),
        "log_files": [str(ref.path) for ref in log_refs],
        "overall": overall,
        "labs": labs,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate confusion matrix and classification metrics from Inspect AI logs."
    )
    parser.add_argument(
        "--sqlite",
        action="append",
        default=[],
        help="SQLite run DB produced by run_phase1_all_proxy.sh. Can be passed more than once.",
    )
    parser.add_argument(
        "--run-id",
        type=int,
        default=None,
        help="Restrict --sqlite input to a single runs.id value.",
    )
    parser.add_argument(
        "--log",
        action="append",
        default=[],
        help="Inspect .eval file or glob. Can be passed more than once.",
    )
    parser.add_argument(
        "--base-dir",
        default="",
        help="Base directory for relative log paths. Defaults to cwd for --log and to the DB parent for --sqlite.",
    )
    parser.add_argument(
        "--out-dir",
        default="reports/phase1_metrics/latest",
        help="Directory for metrics.json, samples.csv, report.md, and report.html.",
    )
    parser.add_argument(
        "--scorer",
        default="",
        help="Optional scorer name to use when a sample has multiple scores.",
    )
    parser.add_argument(
        "--fail-on-empty",
        action="store_true",
        help="Return non-zero when no scored samples are included in the matrix.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    base_dir = Path(args.base_dir).resolve() if args.base_dir else Path.cwd().resolve()

    log_refs: list[LogRef] = []
    for sqlite_arg in args.sqlite:
        sqlite_path = Path(sqlite_arg)
        if not sqlite_path.is_absolute():
            sqlite_path = base_dir / sqlite_path
        sqlite_base = base_dir if args.base_dir else None
        log_refs.extend(logs_from_sqlite(sqlite_path.resolve(), sqlite_base, args.run_id))
    log_refs.extend(logs_from_patterns(args.log, base_dir))

    deduped: list[LogRef] = []
    seen: set[Path] = set()
    for ref in log_refs:
        if ref.path not in seen:
            deduped.append(ref)
            seen.add(ref.path)
    log_refs = deduped

    if not log_refs:
        print("No eval logs found. Pass --sqlite or --log.", file=sys.stderr)
        return 2

    records: list[SampleRecord] = []
    for ref in log_refs:
        if not ref.path.exists():
            print(f"Warning: eval log not found: {ref.path}", file=sys.stderr)
            continue
        try:
            records.extend(read_log_records(ref, preferred_scorer=args.scorer))
        except Exception as ex:  # noqa: BLE001 - keep batch reports best-effort
            print(f"Warning: failed to read {ref.path}: {type(ex).__name__}: {ex}", file=sys.stderr)

    out_dir = Path(args.out_dir)
    if not out_dir.is_absolute():
        out_dir = base_dir / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    payload = build_payload(records, log_refs)
    write_json(out_dir / "metrics.json", payload)
    write_samples_csv(out_dir / "samples.csv", records)
    write_markdown(out_dir / "report.md", payload)
    write_html(out_dir / "report.html", payload)

    included = payload["overall"]["included"]
    print(f"Metrics report written to {out_dir}")
    print(f"Included scored samples: {included} / {payload['overall']['samples']}")

    if args.fail_on_empty and included == 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
