import json
from types import SimpleNamespace

from dnsbuilder.utils import update


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


def test_check_for_update_reads_latest_tag_and_caches(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setenv("DNSB_UPDATE_CACHE", str(tmp_path / "update.json"))
    monkeypatch.setenv("DNSB_UPDATE_INTERVAL", "3600")

    def fake_urlopen(request, timeout):
        calls.append((request.full_url, timeout))
        return _Response([{"name": "v0.15.0"}, {"name": "v0.13.9"}])

    monkeypatch.setattr(update, "urlopen", fake_urlopen)
    info = update.check_for_update(force=True)

    assert info is not None
    assert info.current_version == "0.14.0"
    assert info.latest_version == "0.15.0"
    assert info.tag == "v0.15.0"
    assert calls

    cached = update.check_for_update()
    assert cached == info
    assert len(calls) == 1


def test_check_for_update_ignores_older_and_invalid_tags(monkeypatch, tmp_path):
    monkeypatch.setenv("DNSB_UPDATE_CACHE", str(tmp_path / "update.json"))
    monkeypatch.setattr(
        update,
        "urlopen",
        lambda request, timeout: _Response(
            [{"name": "not-a-version"}, {"name": "v0.14.0"}]
        ),
    )

    assert update.check_for_update(force=True) is None


def test_update_check_can_be_disabled(monkeypatch, tmp_path):
    monkeypatch.setenv("DNSB_UPDATE_CHECK", "0")
    monkeypatch.setenv("DNSB_UPDATE_CACHE", str(tmp_path / "update.json"))
    monkeypatch.setattr(
        update,
        "urlopen",
        lambda request, timeout: (_ for _ in ()).throw(AssertionError("network")),
    )

    assert update.check_for_update(force=True) is None


def test_explicit_update_can_bypass_disabled_background_check(monkeypatch, tmp_path):
    monkeypatch.setenv("DNSB_UPDATE_CHECK", "0")
    monkeypatch.setenv("DNSB_UPDATE_CACHE", str(tmp_path / "update.json"))
    monkeypatch.setattr(
        update,
        "urlopen",
        lambda request, timeout: _Response([{"name": "v0.15.0"}]),
    )

    info = update.check_for_update(force=True, allow_disabled=True)

    assert info is not None
    assert info.latest_version == "0.15.0"


def test_install_update_uses_current_python_and_tag(monkeypatch):
    calls = []
    expected = SimpleNamespace(returncode=0)

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return expected

    monkeypatch.setattr(update.subprocess, "run", fake_run)
    info = update.UpdateInfo("0.14.0", "0.15.0", "v0.15.0", "https://example.test")
    result = update.install_update(info)

    assert result is expected
    assert calls[0][0][0:4] == [update.sys.executable, "-m", "pip", "install"]
    assert calls[0][0][-1].endswith("@v0.15.0")
    assert calls[0][1] == {"check": False, "text": True}
