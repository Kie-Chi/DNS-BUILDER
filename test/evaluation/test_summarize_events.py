from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "dns-builder" / "scripts"))
from summarize_events import csv_rows, group_summary, new_run, summarize_events  # noqa: E402


def test_summary_keeps_model_react_and_verification_metrics(tmp_path) -> None:
    events = tmp_path / "events.jsonl"
    rows = [
        {"event": "run_start", "run_id": "r1", "task_id": "t", "condition": "blank"},
        {
            "event": "agent_event",
            "run_id": "r1",
            "agent_event_type": "turn.started",
            "session_id": "s1",
        },
        {
            "event": "acceptance",
            "run_id": "r1",
            "stage": "model-react",
            "status": "pass",
            "checks": [{"name": "react-tool-use", "status": "pass", "tool_calls": 4}],
        },
        {
            "event": "acceptance",
            "run_id": "r1",
            "stage": "model-verification",
            "status": "pass",
            "verification_seconds": 2.5,
            "checks": [],
        },
        {
            "event": "run_end",
            "run_id": "r1",
            "status": "pending_review",
            "wall_seconds": 10,
            "human_seconds": None,
        },
    ]
    events.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    run = summarize_events(events)[0]
    assert run["react_tool_calls"] == 4
    assert run["model_verification_seconds"] == 2.5
    assert run["agent_turns"] == 1
    assert run["end_to_end_seconds"] is None


def test_summary_preserves_material_protocol_and_provider(tmp_path) -> None:
    events = tmp_path / "events.jsonl"
    rows = [{
        "event": "run_start", "run_id": "r1", "condition": "dns-builder",
        "provider": "agent", "runner_version": "6", "material_policy": "generic-only-v1",
    }]
    events.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    run = summarize_events(events)[0]
    assert run["provider"] == "agent"
    assert run["runner_version"] == "6"
    assert run["material_policy"] == "generic-only-v1"
    assert csv_rows([run])[0]["material_policy"] == "generic-only-v1"


def test_condition_statistics_do_not_mix_legacy_or_fixture_runs() -> None:
    runs = []
    for index, (policy, version, provider) in enumerate([
        (None, None, None),
        ("generic-only-v1", "5", "agent"),
        ("generic-only-v1", "6", "agent"),
        ("fixture-only-v1", "6", "fixture"),
    ]):
        run = new_run(str(index))
        run.update({
            "condition": "dns-builder", "status": "success",
            "material_policy": policy, "runner_version": version, "provider": provider,
        })
        runs.append(run)
    groups = group_summary(runs)
    assert len(groups) == 4
    assert all(group["runs"] == 1 for group in groups)
    assert {(group["material_policy"], group["runner_version"], group["provider"]) for group in groups} == {
        ("unknown", "unknown", "unknown"),
        ("generic-only-v1", "5", "agent"),
        ("generic-only-v1", "6", "agent"),
        ("fixture-only-v1", "6", "fixture"),
    }
