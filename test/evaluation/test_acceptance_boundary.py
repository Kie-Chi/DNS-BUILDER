from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.evaluation import dnsb_agent_runner as runner


def fixture_task() -> dict:
    return {
        "fixture_expected": {
            "project_name": "HIDDEN_PROJECT",
            "min_services": 987654321,
            "required_services": ["HIDDEN_NODE"],
        },
        "fixture_runtime": {
            "checks": [{"name": "HIDDEN_CHECK", "service": "HIDDEN_NODE", "command": ["HIDDEN_TRIGGER"]}],
        },
        "expected": {"required_services": ["HIDDEN_LEGACY_NODE"]},
        "runtime": {"checks": [{"command": ["HIDDEN_LEGACY_TRIGGER"]}]},
    }


def stub_build(tmp_path: Path, monkeypatch, compose_data: dict) -> None:
    def command(argv, *, label, **kwargs):
        if label.startswith("dnsb-"):
            base = Path(argv[argv.index("--output-dir") + 1])
            compose = base / "output/teaching/docker-compose.yml"
            compose.parent.mkdir(parents=True, exist_ok=True)
            compose.write_text(json.dumps(compose_data))
        stdout = tmp_path / f"{label}.stdout"
        stderr = tmp_path / f"{label}.stderr"
        stdout.write_text("")
        stderr.write_text("")
        return SimpleNamespace(ok=True, exit_code=0, stdout_path=stdout, stderr_path=stderr)

    monkeypatch.setattr(runner, "run_command", command)
    monkeypatch.setattr(runner.shutil, "which", lambda _name: None)


@pytest.mark.parametrize("provider,expected_ok", [("agent", True), ("fixture", False)])
def test_build_only_uses_hidden_layout_for_fixture(tmp_path: Path, monkeypatch, provider: str, expected_ok: bool) -> None:
    stub_build(tmp_path, monkeypatch, {"name": "teaching", "services": {"resolver": {"image": "normal-base"}}})
    project = tmp_path / "project"
    project.mkdir()
    (project / "main.yml").write_text("name: teaching\n")
    events = runner.EventLog(tmp_path / "events.jsonl", "run")

    ok, _compose, _data, repair = runner.build_once(
        project_dir=project,
        config_path="main.yml",
        build_dir=tmp_path / "build-1",
        attempt=1,
        args=argparse.Namespace(provider=provider, task=fixture_task(), tool_timeout=1),
        events=events,
        log_dir=tmp_path / "logs",
        dnsb_argv=["dnsb"],
    )

    assert ok is expected_ok
    assert "HIDDEN_" not in repair
    assert "987654321" not in repair
    rows = [json.loads(line) for line in (tmp_path / "events.jsonl").read_text().splitlines()]
    check = next(item for item in rows[-1]["checks"] if item["name"] == "service-count")
    assert check["expected_min"] == (987654321 if provider == "fixture" else 1)


def test_generic_structure_rejects_empty_environment(tmp_path: Path, monkeypatch) -> None:
    stub_build(tmp_path, monkeypatch, {"services": {}})
    project = tmp_path / "project"
    project.mkdir()
    events = runner.EventLog(tmp_path / "events.jsonl", "run")

    ok, _compose, _data, repair = runner.build_once(
        project_dir=project, config_path="main.yml", build_dir=tmp_path / "build-1",
        attempt=1, args=argparse.Namespace(provider="agent", task=fixture_task(), tool_timeout=1),
        events=events, log_dir=tmp_path / "logs", dnsb_argv=["dnsb"],
    )

    assert ok is False
    assert "structural validation" in repair
    assert "HIDDEN_" not in repair


@pytest.mark.parametrize("runtime,expected_status", [("auto", "not_run"), ("always", "fail"), ("never", "not_run")])
def test_model_runtime_never_uses_fixture_trigger(tmp_path: Path, monkeypatch, runtime: str, expected_status: str) -> None:
    def unexpected(*args, **kwargs):
        raise AssertionError("A missing independent verifier must not start containers or execute fixture commands")

    monkeypatch.setattr(runner, "docker_available", unexpected)
    monkeypatch.setattr(runner, "run_command", unexpected)
    events = runner.EventLog(tmp_path / "events.jsonl", "run")

    status, checks = runner.run_runtime(
        tmp_path / "docker-compose.yml", fixture_task(),
        argparse.Namespace(provider="agent", runtime=runtime), events, tmp_path / "logs",
    )

    assert status == expected_status
    assert all(check["status"] != "pass" for check in checks)
    assert "HIDDEN_" not in json.dumps(checks)


def test_fixture_runtime_remains_offline_evaluator_input(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(runner, "docker_available", lambda *_args: False)
    events = runner.EventLog(tmp_path / "events.jsonl", "run")

    status, checks = runner.run_runtime(
        tmp_path / "docker-compose.yml", fixture_task(),
        argparse.Namespace(provider="fixture", runtime="auto"), events, tmp_path / "logs",
    )

    assert status == "not_run"
    assert checks[0]["name"] == "docker-daemon"


@pytest.mark.parametrize(
    "record,replacement",
    [
        ("example.com. 300 IN DNSKEY 257 3 13 AQIDBA==\n", "AQIDBQ=="),
        ("example.com. 300 IN DS 10001 13 2 " + "ab" * 32 + "\n", "cd" * 32),
        ("www.example.com. 300 IN RRSIG A 13 3 300 20300101000000 20200101000000 10001 example.com. AQIDBA==\n", "AQIDBQ=="),
    ],
)
def test_semantic_snapshot_preserves_dnssec_material(tmp_path: Path, record: str, replacement: str) -> None:
    source = tmp_path / "zone"
    source.write_text(record)
    _payload, first = runner.semantic_snapshot(tmp_path, {})
    token = "ab" * 32 if " IN DS " in record else "AQIDBA=="
    source.write_text(record.replace(token, replacement))
    _payload, second = runner.semantic_snapshot(tmp_path, {})

    assert first != second
    assert "DYNAMIC_RECORD" not in runner.normalize_text(record, tmp_path)
    assert runner.normalize_text(record, tmp_path) == record


def test_normalization_preserves_signature_times_and_key_tags(tmp_path: Path) -> None:
    record = "www.example.com. 300 IN RRSIG A 13 3 300 20300101000000 20200101000000 10001 example.com. (\n AQIDBA== )\n"
    assert runner.normalize_text(record, tmp_path) == record
    changed = record.replace("20300101000000", "20310101000000").replace("10001", "10002")
    assert runner.normalize_text(record, tmp_path) != runner.normalize_text(changed, tmp_path)


def test_unbound_directive_order_is_not_sorted_away(tmp_path: Path) -> None:
    source = tmp_path / "resolver/contents/unbound_recursor_base.conf"
    source.parent.mkdir(parents=True)
    source.write_text("server:\nmodule-config: validator iterator\nmodule-config: iterator\n")
    _payload, first = runner.semantic_snapshot(tmp_path, {})
    source.write_text("server:\nmodule-config: iterator\nmodule-config: validator iterator\n")
    _payload, second = runner.semantic_snapshot(tmp_path, {})
    assert first != second


def test_normalization_only_removes_declared_soa_serial(tmp_path: Path) -> None:
    original = "example.com. 300 IN SOA ns.example.com. admin.example.com. 1900000000 7200 3600 1209600 3600\n"
    changed = original.replace("1900000000", "1900000001")
    assert runner.normalize_text(original, tmp_path) == runner.normalize_text(changed, tmp_path)


def test_blank_native_agent_does_not_inherit_dnsb_injection(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DNSB_AGENT_DNSB_BIN", "/hidden/checkout/.venv/bin/dnsb")
    captured = {}

    class Process:
        returncode = 0

        def __init__(self, argv, **kwargs):
            captured.update(kwargs)

        def communicate(self, *_args, **_kwargs):
            return b"", b""

    monkeypatch.setattr(runner.subprocess, "Popen", Process)
    args = argparse.Namespace(
        agent="codex", model="snapshot", condition="blank", model_timeout=1,
        dnsb_agent_bin="/hidden/checkout/.venv/bin/dnsb",
    )
    provider = runner.ModelProvider(args, tmp_path, {})
    monkeypatch.setattr(provider, "_agent_argv", lambda _workspace: ["coding-agent"])
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    result = provider._agent("Public prompt", 1, tmp_path / "model", workspace)

    assert result.error is None
    assert "DNSB_AGENT_DNSB_BIN" not in captured["env"]
    assert captured["cwd"] == str(workspace)
    assert not captured["env"]["PATH"].startswith("/hidden/checkout/.venv/bin")
