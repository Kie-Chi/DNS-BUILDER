from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.evaluation.dnsb_agent_runner import EventLog, run_model_verification


def args_for(tmp_path: Path, timeout: float = 5.0) -> argparse.Namespace:
    return argparse.Namespace(tool_timeout=timeout)


def test_runner_reruns_verifier_and_retains_report(tmp_path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "verify.sh").write_text(
        "#!/usr/bin/env bash\n"
        "cat > verification-report.json <<'EOF'\n"
        '{"status":"pass","commands":["bash verify.sh"],"checks":[{"name":"query","status":"pass","command":"dig"}]}\n'
        "EOF\n",
        encoding="utf-8",
    )
    events = EventLog(tmp_path / "events.jsonl", "run")
    status, checks, report = run_model_verification(
        project_dir=project,
        verify_path="verify.sh",
        compose_path=None,
        args=args_for(tmp_path),
        events=events,
        log_dir=tmp_path / "logs",
    )
    assert status == "pass"
    assert report == project / "verification-report.json"
    assert all(check["status"] == "pass" for check in checks)
    rows = [json.loads(line) for line in (tmp_path / "events.jsonl").read_text().splitlines()]
    assert any(row.get("stage") == "model-verification" and row.get("status") == "pass" for row in rows)


def test_runner_marks_failed_verifier_and_timeout(tmp_path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "verify.sh").write_text(
        "#!/usr/bin/env bash\n"
        "sleep 1\n"
        "exit 1\n",
        encoding="utf-8",
    )
    events = EventLog(tmp_path / "events.jsonl", "run")
    status, checks, _ = run_model_verification(
        project_dir=project,
        verify_path="verify.sh",
        compose_path=None,
        args=args_for(tmp_path, timeout=0.05),
        events=events,
        log_dir=tmp_path / "logs",
    )
    assert status == "fail"
    assert checks[0]["status"] == "fail"
    assert checks[0]["timed_out"] is True
