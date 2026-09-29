import os

import pytest

from dnsbuilder.utils.dnssec_tools import (
    DEFAULT_DNSSEC_TOOL_IMAGE,
    DnssecToolError,
    DockerDnssecToolRunner,
    HostDnssecToolRunner,
    create_dnssec_tool_runner,
)


def test_host_runner_honors_explicit_override(tmp_path, monkeypatch):
    tool = tmp_path / "dnssec-signzone"
    tool.write_text("#!/bin/sh\nexit 0\n")
    tool.chmod(0o755)
    monkeypatch.setenv("BIND_DNSSEC_SIGNZONE", str(tool))

    runner = HostDnssecToolRunner()
    runner.preflight(["dnssec-signzone"])

    assert runner.resolve("dnssec-signzone") == str(tool)


def test_host_runner_rejects_invalid_explicit_override(tmp_path, monkeypatch):
    missing = tmp_path / "missing-signzone"
    monkeypatch.setenv("BIND_DNSSEC_SIGNZONE", str(missing))

    with pytest.raises(DnssecToolError, match="BIND_DNSSEC_SIGNZONE"):
        HostDnssecToolRunner().preflight(["dnssec-signzone"])


def test_host_runner_does_not_install_by_default(monkeypatch):
    monkeypatch.setattr("dnsbuilder.utils.dnssec_tools.KNOWN_TOOL_DIRS", ())
    monkeypatch.setenv("PATH", os.devnull)
    runner = HostDnssecToolRunner(auto_install=False, os_id="unknown")

    with pytest.raises(DnssecToolError, match="dnssec-signzone"):
        runner.preflight(["dnssec-signzone"])


def test_runner_factory_supports_explicit_docker_mode():
    runner = create_dnssec_tool_runner(
        {"util_mode": "docker", "util_image": "example/bind-tools:9.20"}
    )

    assert isinstance(runner, DockerDnssecToolRunner)
    assert runner.image == "example/bind-tools:9.20"
    assert runner.auto_build is False


def test_runner_factory_uses_bundled_docker_image_by_default():
    runner = create_dnssec_tool_runner({"util_mode": "docker"})

    assert isinstance(runner, DockerDnssecToolRunner)
    assert runner.image is None
    assert runner.auto_build is True


def test_default_docker_runner_builds_bundled_image(monkeypatch):
    runner = DockerDnssecToolRunner()
    commands = []

    def fake_docker(args, check=True):
        commands.append((list(args), check))
        if args[:3] == ["image", "inspect", DEFAULT_DNSSEC_TOOL_IMAGE]:
            from subprocess import CompletedProcess

            return CompletedProcess(args, 1, "", "missing")
        from subprocess import CompletedProcess

        return CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(runner, "_docker", fake_docker)
    runner.preflight(["dnssec-signzone"])

    assert runner.image == DEFAULT_DNSSEC_TOOL_IMAGE
    assert any(command[0] == "build" for command, _ in commands)
    assert any(command[:3] == ["image", "inspect", DEFAULT_DNSSEC_TOOL_IMAGE] for command, _ in commands)


def test_runner_factory_rejects_unknown_mode():
    with pytest.raises(DnssecToolError, match="host.*docker"):
        create_dnssec_tool_runner({"util_mode": "container"})
