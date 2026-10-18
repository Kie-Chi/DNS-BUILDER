#!/usr/bin/env python3
"""Record the final human feasibility decision for a ``blank`` episode.

A positive ``feasible`` decision requires the model ReAct and independent
verifier gates.  A terminal failed episode may instead be recorded as
``infeasible`` when no reviewable project was produced; this preserves the
failure as a human-audited result without treating human review as a
replacement for model validation.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def append_event(events_path: Path, run_id: str, **fields: Any) -> None:
    max_seq = 0
    if events_path.exists():
        for raw in events_path.read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                continue
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict) and isinstance(event.get("seq"), int):
                max_seq = max(max_seq, event["seq"])
    payload = {"event": "human_review", "run_id": run_id, "seq": max_seq + 1, "t": utc_now()}
    payload.update(fields)
    with events_path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, ensure_ascii=False) + "\n")


def acceptance_status(events_path: Path, stage: str) -> str | None:
    """Return the latest acceptance status for a stage."""

    status: str | None = None
    for raw in events_path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and event.get("event") == "acceptance" and event.get("stage") == stage:
            value = event.get("status")
            status = str(value) if value is not None else None
    return status


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--episode", type=Path, required=True, help="blank episode directory")
    parser.add_argument("--status", choices=("feasible", "infeasible"), required=True)
    parser.add_argument("--reviewer", required=True, help="reviewer identifier")
    parser.add_argument("--human-seconds", type=float, required=True)
    parser.add_argument("--notes", default="", help="review rationale and observed limitations")
    args = parser.parse_args()

    episode = args.episode.resolve()
    run_path = episode / "run.json"
    review_path = episode / "artifacts" / "human-review.json"
    events_path = episode / "events.jsonl"
    if not run_path.is_file() or not review_path.is_file() or not events_path.is_file():
        parser.error("episode must contain run.json, artifacts/human-review.json, and events.jsonl")
    run = read_object(run_path)
    if run.get("condition") != "blank":
        parser.error("--episode must be a condition=blank episode")
    react_status = acceptance_status(events_path, "model-react")
    verification_status = acceptance_status(events_path, "model-verification")
    if args.status == "feasible":
        if react_status != "pass":
            parser.error("model ReAct verification must pass before a feasible human review")
        if verification_status != "pass":
            parser.error("independent model-verification rerun must pass before a feasible human review")
    elif react_status == "pass" and verification_status == "pass":
        # A normally completed blank episode can be judged infeasible after
        # inspecting its passing verifier report.  Failed episodes are also
        # allowed below so infrastructure/model failures receive an explicit
        # terminal human classification instead of remaining pending forever.
        pass
    elif str(run.get("status")) not in {"failure", "partial"}:
        parser.error("an infeasible review without both model gates requires a terminal failed episode")
    review = read_object(review_path)
    reviewed_at = utc_now()
    review.update(
        {
            "status": args.status,
            "feasible": args.status == "feasible",
            "reviewer": args.reviewer,
            "reviewed_at": reviewed_at,
            "human_seconds": args.human_seconds,
        "notes": args.notes,
        "gate_status": {"model-react": react_status, "model-verification": verification_status},
        }
    )
    review_path.write_text(json.dumps(review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    append_event(
        events_path,
        str(run.get("run_id")),
        status=args.status,
        feasible=args.status == "feasible",
        reviewer=args.reviewer,
        human_seconds=args.human_seconds,
        notes=args.notes,
        review_path=str(review_path),
    )

    run["status"] = "success" if args.status == "feasible" else "failure"
    run["human_review_status"] = args.status
    run["human_seconds"] = args.human_seconds
    run["human_reviewer"] = args.reviewer
    run_path.write_text(json.dumps(run, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    repo_root = Path(__file__).resolve().parents[2]
    summary_script = repo_root / "skills" / "dns-builder" / "scripts" / "summarize_events.py"
    subprocess.run(
        [sys.executable, str(summary_script), "--events", str(events_path), "--out", str(episode / "summary.json")],
        cwd=repo_root,
        check=False,
    )
    # Importing the runner helper keeps the episode manifest schema identical
    # before and after review.
    from dnsb_agent_runner import write_episode_manifest

    write_episode_manifest(episode)
    print(json.dumps({"episode": str(episode), "status": args.status, "review": str(review_path)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
