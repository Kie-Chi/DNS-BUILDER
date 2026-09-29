from click.testing import CliRunner

import dnsbuilder.cli as cli_module
from dnsbuilder.utils.update import UpdateInfo


def test_update_command_forces_a_fresh_check(monkeypatch):
    calls = []
    monkeypatch.setattr(
        cli_module,
        "check_for_update",
        lambda **kwargs: calls.append(kwargs) or None,
    )

    result = CliRunner().invoke(cli_module.cli, ["update"])

    assert result.exit_code == 0
    assert "0.14.0 is up to date" in result.output
    assert calls == [{"force": True, "allow_disabled": True}]


def test_startup_notice_is_non_blocking(monkeypatch):
    info = UpdateInfo("0.14.0", "0.15.0", "v0.15.0", "https://example.test")
    monkeypatch.setattr(cli_module, "check_for_update", lambda **kwargs: info)

    # Use a harmless command with its implementation stubbed so the group
    # callback runs without requiring Docker.
    monkeypatch.setattr(cli_module, "do_clean", lambda *args, **kwargs: None)
    result = CliRunner().invoke(cli_module.cli, ["clean", "--all"])

    assert result.exit_code == 0
    assert "0.14.0 -> 0.15.0" in result.stderr
    assert "dnsb update --upgrade" in result.stderr
