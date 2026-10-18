from __future__ import annotations

import json

from scripts.evaluation.agent_trace import parse_stream
from scripts.evaluation.dnsb_agent_runner import (
    audit_agent_react,
    build_prompt,
    inspect_verification_report,
    validate_blank_bundle,
)


def line(*events: dict) -> str:
    return "\n".join(json.dumps(event) for event in events) + "\n"


def test_codex_jsonl_usage_tool_and_session_are_normalized() -> None:
    raw = "warning from cli\n" + line(
        {"type": "thread.started", "thread_id": "thread-1"},
        {
            "type": "item.started",
            "timestamp": "2026-01-01T00:00:00Z",
            "item": {
                "id": "call-1",
                "type": "command_execution",
                "command": "echo hello",
                "status": "in_progress",
            },
        },
        {
            "type": "item.completed",
            "timestamp": "2026-01-01T00:00:01Z",
            "item": {
                "id": "call-1",
                "type": "command_execution",
                "command": "echo hello",
                "aggregated_output": "hello\n",
                "exit_code": 0,
                "status": "completed",
            },
        },
        {
            "type": "item.completed",
            "item": {"id": "message-1", "type": "agent_message", "text": "done"},
        },
        {
            "type": "turn.completed",
            "usage": {
                "input_tokens": 100,
                "output_tokens": 20,
                "cached_input_tokens": 40,
                "reasoning_output_tokens": 5,
                "total_tokens": 120,
            },
        },
    )

    trace = parse_stream("codex", raw, model_hint="gpt-test")

    assert trace.session_id == "thread-1"
    assert trace.usage == {
        "input_tokens": 100,
        "output_tokens": 20,
        "reasoning_tokens": 5,
        "cached_input_tokens": 40,
        "total_tokens": 120,
    }
    assert trace.usage_source == "provider"
    assert trace.json_events == 5
    assert trace.malformed_lines == 1
    assert len(trace.tool_calls) == 1
    assert trace.tool_calls[0]["duration_s"] == 1.0
    assert trace.trajectory()["final_metrics"]["total_steps"] == 2


def test_claude_stream_json_attaches_tool_result_and_result_usage() -> None:
    raw = line(
        {
            "type": "system",
            "subtype": "init",
            "session_id": "session-1",
            "model": "claude-test",
            "version": "2.1.0",
        },
        {
            "type": "assistant",
            "message": {
                "id": "message-1",
                "role": "assistant",
                "model": "claude-test",
                "content": [
                    {"type": "text", "text": "running"},
                    {"type": "tool_use", "id": "tool-1", "name": "Bash", "input": {"command": "echo hi"}},
                ],
            },
        },
        {
            "type": "user",
            "message": {"content": [{"type": "tool_result", "tool_use_id": "tool-1", "content": "hi\n"}]},
        },
        {
            "type": "result",
            "session_id": "session-1",
            "result": "finished",
            "usage": {"input_tokens": 80, "output_tokens": 12, "cache_read_input_tokens": 20},
            "total_cost_usd": 0.012,
        },
    )

    trace = parse_stream("claude", raw, model_hint="claude-test")

    assert trace.session_id == "session-1"
    assert trace.usage["input_tokens"] == 80
    assert trace.usage["cached_input_tokens"] == 20
    assert trace.extra["total_cost_usd"] == 0.012
    assert len(trace.tool_calls) == 1
    step = trace.trajectory()["steps"][0]
    assert step["tool_calls"][0]["function_name"] == "Bash"
    assert step["observation"]["results"][0]["content"] == "hi\n"


def test_blank_prompt_has_only_paper_task_and_generic_bundle_contract(tmp_path) -> None:
    task = {
        "task_id": "paper-case",
        "title": "paper case",
        "instructions": "Reproduce the environment from the paper.",
        "reference_files": ["should-not-be-injected.md"],
    }
    prompt = build_prompt(
        task=task,
        pdf_text="paper evidence",
        repo_root=tmp_path,
        condition="blank",
        max_pdf_chars=1000,
    )
    assert "paper evidence" in prompt
    assert "should-not-be-injected.md" not in prompt
    assert "DNS-BUILDER" not in prompt
    assert "Public repository material available" not in prompt
    assert "docker-compose.yml" in prompt
    assert "verification-report.json" in prompt
    assert "mandatory verifier" in prompt


def test_blank_bundle_does_not_require_dnsbuilder_config() -> None:
    entrypoint, files, verify_path, notes = validate_blank_bundle(
        {
            "files": {
                "docker-compose.yml": "services: {}",
                "verify.sh": "#!/usr/bin/env bash\n",
                "verification-report.json": '{"status":"pass","commands":["bash verify.sh"],"checks":[{"name":"smoke","status":"pass","command":"bash verify.sh"}]}',
            },
            "entrypoint": "docker-compose.yml",
            "verify_path": "verify.sh",
            "notes": "generic baseline",
        }
    )
    assert entrypoint == "docker-compose.yml"
    assert files["docker-compose.yml"] == "services: {}"
    assert verify_path == "verify.sh"
    assert notes == "generic baseline"


def test_blank_bundle_requires_verifier() -> None:
    try:
        validate_blank_bundle({"files": {"docker-compose.yml": "services: {}"}})
    except ValueError as exc:
        assert "verify_path" in str(exc)
    else:  # pragma: no cover - assertion keeps the contract explicit
        raise AssertionError("blank bundles must declare verify_path")


def test_verification_report_requires_pass(tmp_path) -> None:
    report = tmp_path / "verification-report.json"
    report.write_text('{"status":"fail","checks":[{"name":"query","status":"fail"}]}')
    path, ok, detail = inspect_verification_report(tmp_path)
    assert path == report
    assert not ok
    assert "failed checks" in detail


def test_verification_report_accepts_boolean_check_results(tmp_path) -> None:
    report = tmp_path / "verification-report.json"
    report.write_text(
        '{"status":"pass","commands":["bash verify.sh"],'
        '"checks":[{"name":"smoke","passed":true}]}'
    )
    path, ok, detail = inspect_verification_report(tmp_path)
    assert path == report
    assert ok
    assert "passing result" in detail


def test_react_audit_requires_successful_verifier_call() -> None:
    class Trace:
        tool_calls = [
            {
                "tool_name": "command_execution",
                "arguments": {"command": "bash verify.sh"},
                "status": "completed",
                "exit_code": 0,
            }
        ]

    ok, checks = audit_agent_react(Trace(), "verify.sh")
    assert ok
    assert all(check["status"] == "pass" for check in checks)
