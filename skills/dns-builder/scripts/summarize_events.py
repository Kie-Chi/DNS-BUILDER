#!/usr/bin/env python3
"""Summarize model/tool/acceptance JSONL events by run and condition.

The model client is responsible for emitting model_call events with provider
usage. This script does not estimate tokens and never silently treats missing
usage as zero.

Example:
    python summarize_events.py --events evaluation/events.jsonl \
      --out evaluation/summary.json
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


TOKEN_FIELDS = (
    "input_tokens",
    "output_tokens",
    "reasoning_tokens",
    "cached_input_tokens",
    "total_tokens",
)

CSV_FIELDS = (
    "run_id",
    "task_id",
    "condition",
    "model",
    "agent_mode",
    "provider",
    "runner_version",
    "material_policy",
    "status",
    "wall_seconds",
    "end_to_end_seconds",
    "model_latency_seconds",
    "tool_seconds",
    "model_verification_seconds",
    "human_seconds",
    "human_review_status",
    "human_reviewer",
    "cost_usd",
    "model_input_tokens",
    "model_output_tokens",
    "model_reasoning_tokens",
    "cached_input_tokens",
    "model_total_tokens",
    "total_tokens_source",
    "agent_events",
    "agent_turns",
    "agent_malformed_lines",
    "agent_tool_calls",
    "react_tool_calls",
    "agent_sessions",
    "model_calls",
    "tool_calls",
    "retries",
    "usage_sources",
    "tool_seconds_by_label",
)


def number(value: Any) -> float | int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    return None


def add_optional(current: float | int | None, value: Any) -> float | int | None:
    value = number(value)
    if value is None:
        return current
    return value if current is None else current + value


def iqr(values: list[float]) -> float | None:
    clean = sorted(v for v in values if isinstance(v, (int, float)))
    if len(clean) < 2:
        return 0.0 if clean else None
    quartiles = statistics.quantiles(clean, n=4, method="inclusive")
    return quartiles[2] - quartiles[0]


def median(values: list[float]) -> float | None:
    clean = [v for v in values if isinstance(v, (int, float))]
    return statistics.median(clean) if clean else None


def new_run(run_id: str) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "task_id": None,
        "condition": None,
        "model": None,
        "agent_mode": None,
        "provider": None,
        "runner_version": None,
        "material_policy": None,
        "model_snapshot": None,
        "skill_id": None,
        "status": "unknown",
        "wall_seconds": None,
        "end_to_end_seconds": None,
        "model_latency_seconds": 0.0,
        "tool_seconds": 0.0,
        "model_verification_seconds": 0.0,
        "human_seconds": None,
        "human_review_status": None,
        "human_reviewer": None,
        "cost_usd": None,
        "model_input_tokens": None,
        "model_output_tokens": None,
        "model_reasoning_tokens": None,
        "cached_input_tokens": None,
        "model_total_tokens": None,
        "total_tokens_source": "provider",
        "agent_events": 0,
        "agent_turns": 0,
        "agent_malformed_lines": 0,
        "agent_tool_calls": 0,
        "react_tool_calls": 0,
        "agent_sessions": [],
        "model_calls": 0,
        "tool_calls": 0,
        "retries": 0,
        "tool_seconds_by_label": {},
        "usage_sources": [],
        "acceptance": {},
        "usage_missing": [],
        "events": 0,
    }


def summarize_events(path: Path) -> list[dict[str, Any]]:
    runs: dict[str, dict[str, Any]] = {}
    with path.open(encoding="utf-8") as stream:
        for line_number, raw in enumerate(stream, start=1):
            if not raw.strip():
                continue
            try:
                event = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
            if not isinstance(event, dict):
                raise ValueError(f"{path}:{line_number}: event must be an object")
            run_id = event.get("run_id")
            if not isinstance(run_id, str) or not run_id:
                raise ValueError(f"{path}:{line_number}: missing string run_id")
            run = runs.setdefault(run_id, new_run(run_id))
            run["events"] += 1
            event_name = event.get("event")

            if event_name == "run_start":
                for field in (
                    "task_id",
                    "condition",
                    "model",
                    "agent_mode",
                    "provider",
                    "runner_version",
                    "material_policy",
                    "model_snapshot",
                    "skill_id",
                ):
                    if field in event:
                        run[field] = event[field]
            elif event_name == "model_call":
                run["model_calls"] += 1
                # A later model attempt is a repair/retry even though it is
                # not a shell tool invocation.  Keep the count in the same
                # run-level field used for tool retries.
                attempt = number(event.get("attempt"))
                if event.get("retry") is True or (isinstance(attempt, (int, float)) and attempt > 1):
                    run["retries"] += 1
                usage_source = event.get("usage_source")
                if usage_source and usage_source not in run["usage_sources"]:
                    run["usage_sources"].append(usage_source)
                session_id = event.get("agent_session_id") or event.get("request_id")
                if event.get("agent") and session_id and session_id not in run["agent_sessions"]:
                    run["agent_sessions"].append(session_id)
                malformed = number(event.get("agent_malformed_lines"))
                if malformed is not None:
                    run["agent_malformed_lines"] = max(
                        run["agent_malformed_lines"], int(malformed)
                    )
                duration = number(event.get("duration_s"))
                if duration is not None:
                    run["model_latency_seconds"] += duration
                usage = event.get("usage") or {}
                if not isinstance(usage, dict):
                    usage = {}
                for field in TOKEN_FIELDS:
                    run_key = (
                        "cached_input_tokens"
                        if field == "cached_input_tokens"
                        else f"model_{field}"
                    )
                    value = usage.get(field)
                    run[run_key] = add_optional(run[run_key], value)
                    if number(value) is None:
                        run["usage_missing"].append(
                            {"event_seq": event.get("seq"), "field": field}
                        )
                cost = number(event.get("cost_usd"))
                if cost is None:
                    cost = number(usage.get("cost_usd"))
                run["cost_usd"] = add_optional(run["cost_usd"], cost)
            elif event_name == "tool_call":
                run["tool_calls"] += 1
                duration = number(event.get("duration_s"))
                if duration is not None:
                    run["tool_seconds"] += duration
                    label = str(event.get("label") or event.get("tool") or "tool")
                    by_label = run["tool_seconds_by_label"]
                    by_label[label] = by_label.get(label, 0.0) + duration
                if event.get("retry") is True:
                    run["retries"] += 1
                if event.get("source") == "agent":
                    run["agent_tool_calls"] += 1
            elif event_name == "agent_event":
                run["agent_events"] += 1
                if event.get("agent_event_type") == "turn.started":
                    run["agent_turns"] += 1
                session_id = event.get("session_id") or event.get("thread_id")
                if session_id and session_id not in run["agent_sessions"]:
                    run["agent_sessions"].append(session_id)
            elif event_name == "acceptance":
                stage = str(event.get("stage", "unknown"))
                run["acceptance"][stage] = {
                    "status": event.get("status", "unknown"),
                    "checks": event.get("checks", []),
                }
                if stage == "model-verification":
                    duration = number(event.get("verification_seconds"))
                    if duration is not None:
                        run["model_verification_seconds"] += duration
                elif stage == "model-react":
                    checks = event.get("checks")
                    if isinstance(checks, list):
                        for check in checks:
                            if not isinstance(check, dict):
                                continue
                            if check.get("name") == "react-tool-use":
                                count = number(check.get("tool_calls"))
                                if count is not None:
                                    run["react_tool_calls"] = max(run["react_tool_calls"], int(count))
            elif event_name == "run_end":
                for field in ("status", "wall_seconds", "human_seconds"):
                    if field in event:
                        run[field] = event[field]
                if number(event.get("model_verification_seconds")) is not None:
                    run["model_verification_seconds"] = number(event.get("model_verification_seconds"))
                run["retries"] = max(
                    run["retries"], int(event.get("retries", run["retries"]) or 0)
                )
            elif event_name == "human_review":
                status = event.get("status")
                run["human_review_status"] = status
                run["human_reviewer"] = event.get("reviewer")
                if number(event.get("human_seconds")) is not None:
                    run["human_seconds"] = number(event.get("human_seconds"))
                review_status = "pass" if status == "feasible" else "fail" if status == "infeasible" else "pending"
                run["acceptance"]["human-review"] = {
                    "status": review_status,
                    "checks": [
                        {
                            "name": "human-feasibility-review",
                            "status": review_status,
                            "reviewer": event.get("reviewer"),
                            "human_seconds": event.get("human_seconds"),
                            "notes": event.get("notes", ""),
                        }
                    ],
                }
                if status == "feasible":
                    run["status"] = "success"
                elif status == "infeasible":
                    run["status"] = "failure"

    result = []
    for run in runs.values():
        if (
            run["model_total_tokens"] is None
            and run["model_input_tokens"] is not None
            and run["model_output_tokens"] is not None
        ):
            run["model_total_tokens"] = (
                run["model_input_tokens"] + run["model_output_tokens"]
            )
            run["total_tokens_source"] = "derived_input_plus_output"
        run["model_latency_seconds"] = round(run["model_latency_seconds"], 6)
        run["tool_seconds"] = round(run["tool_seconds"], 6)
        run["model_verification_seconds"] = round(run["model_verification_seconds"], 6)
        wall_seconds = number(run.get("wall_seconds"))
        human_seconds = number(run.get("human_seconds"))
        if wall_seconds is not None and human_seconds is not None:
            run["end_to_end_seconds"] = round(wall_seconds + human_seconds, 6)
        run["tool_seconds_by_label"] = {
            key: round(value, 6) for key, value in run["tool_seconds_by_label"].items()
        }
        result.append(run)
    return sorted(result, key=lambda item: item["run_id"])


def group_summary(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Never pool old answer-assisted or offline-fixture runs with model data.
    buckets: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for run in runs:
        key = tuple(str(run.get(field) or "unknown") for field in (
            "condition", "material_policy", "runner_version", "provider",
        ))
        buckets[key].append(run)

    summaries: list[dict[str, Any]] = []
    for (condition, material_policy, runner_version, provider), members in sorted(buckets.items()):
        success = sum(1 for run in members if run.get("status") == "success")
        fields = {
            "wall_seconds": [run["wall_seconds"] for run in members],
            "end_to_end_seconds": [run["end_to_end_seconds"] for run in members],
            "model_latency_seconds": [
                run["model_latency_seconds"] for run in members
            ],
            "tool_seconds": [run["tool_seconds"] for run in members],
            "model_verification_seconds": [
                run["model_verification_seconds"] for run in members
            ],
            "model_total_tokens": [
                run["model_total_tokens"] for run in members
            ],
            "model_input_tokens": [
                run["model_input_tokens"] for run in members
            ],
            "model_output_tokens": [
                run["model_output_tokens"] for run in members
            ],
            "cost_usd": [run["cost_usd"] for run in members],
        }
        summary: dict[str, Any] = {
            "condition": condition,
            "material_policy": material_policy,
            "runner_version": runner_version,
            "provider": provider,
            "runs": len(members),
            "successes": success,
            "success_rate": success / len(members) if members else None,
        }
        for field, values in fields.items():
            numeric = [value for value in values if isinstance(value, (int, float))]
            summary[f"{field}_median"] = median(numeric)
            summary[f"{field}_iqr"] = iqr(numeric)
        summaries.append(summary)
    return summaries


def csv_rows(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{key: run.get(key) for key in CSV_FIELDS} for run in runs]


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize evaluation events.")
    parser.add_argument("--events", type=Path, required=True, help="Input JSONL")
    parser.add_argument("--out", type=Path, help="Output JSON/CSV; stdout if omitted")
    parser.add_argument(
        "--format", choices=("json", "csv"), default="json", help="Output format"
    )
    args = parser.parse_args()

    runs = summarize_events(args.events)
    payload = {"schema_version": 3, "runs": runs, "conditions": group_summary(runs)}
    if args.format == "csv":
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            with args.out.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(CSV_FIELDS))
                writer.writeheader()
                writer.writerows(csv_rows(runs))
        else:
            writer = csv.DictWriter(sys.stdout, fieldnames=list(CSV_FIELDS))
            writer.writeheader()
            writer.writerows(csv_rows(runs))
    else:
        text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(text)
        else:
            print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
