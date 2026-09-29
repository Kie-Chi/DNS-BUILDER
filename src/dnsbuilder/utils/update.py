"""Version discovery and opt-in self-update helpers for the ``dnsb`` CLI.

The project is distributed from source rather than a stable PyPI project, so
the default update source is the repository's GitHub tag API.  Network errors
are deliberately non-fatal: an update check must never prevent a DNS build.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..rules.version import Version


DEFAULT_REPOSITORY = "Kie-Chi/DNS-BUILDER"
DEFAULT_TAGS_URL = (
    f"https://api.github.com/repos/{DEFAULT_REPOSITORY}/tags?per_page=100"
)
DEFAULT_REPOSITORY_URL = f"https://github.com/{DEFAULT_REPOSITORY}"
DEFAULT_CHECK_INTERVAL = 24 * 60 * 60
DEFAULT_TIMEOUT = 2.0


@dataclass(frozen=True)
class UpdateInfo:
    """A newer version discovered from the configured update source."""

    current_version: str
    latest_version: str
    tag: str
    url: str


def _disabled(value: str | None) -> bool:
    return (value or "").strip().lower() in {"0", "false", "no", "off"}


def _cache_path() -> Path:
    configured = os.environ.get("DNSB_UPDATE_CACHE")
    if configured:
        return Path(configured).expanduser()

    cache_root = os.environ.get("XDG_CACHE_HOME")
    if cache_root:
        return Path(cache_root).expanduser() / "dnsbuilder" / "update.json"
    return Path.home() / ".cache" / "dnsbuilder" / "update.json"


def _read_cache(path: Path, now: float, interval: float) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        checked_at = float(data["checked_at"])
        if now - checked_at <= interval:
            return data
    except (OSError, ValueError, TypeError, KeyError):
        return None
    return None


def _write_cache(path: Path, data: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f"{path.suffix}.tmp")
        temporary.write_text(json.dumps(data), encoding="utf-8")
        temporary.replace(path)
    except OSError:
        # Read-only home directories and sandboxed CI must not break the CLI.
        return


def _parse_version(value: str) -> Version | None:
    value = value.strip()
    if value.startswith("refs/tags/"):
        value = value.removeprefix("refs/tags/")
    if value.startswith(("v", "V")):
        value = value[1:]
    try:
        return Version(value)
    except Exception:
        return None


def _latest_from_tags(payload: Any) -> tuple[str, str] | None:
    if not isinstance(payload, list):
        return None

    candidates: list[tuple[Version, str]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if not isinstance(name, str):
            continue
        parsed = _parse_version(name)
        if parsed is not None:
            candidates.append((parsed, name))
    if not candidates:
        return None
    _, tag = max(candidates, key=lambda pair: pair[0])
    return tag, str(_parse_version(tag))


def _fetch_latest(timeout: float) -> tuple[str, str] | None:
    source_url = os.environ.get("DNSB_UPDATE_URL", DEFAULT_TAGS_URL)
    request = Request(
        source_url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"dnsbuilder/{current_version()}",
        },
    )
    with urlopen(request, timeout=timeout) as response:  # nosec B310
        payload = json.loads(response.read().decode("utf-8"))
    return _latest_from_tags(payload)


def current_version() -> str:
    # Import lazily to keep this utility usable during package bootstrap.
    from .. import __version__

    return __version__


def check_for_update(
    *, force: bool = False, allow_disabled: bool = False
) -> UpdateInfo | None:
    """Return update information, or ``None`` when no update is available.

    The normal startup path is cached for 24 hours.  ``force=True`` is used by
    the explicit ``dnsb update`` command and bypasses that cache.
    """

    if _disabled(os.environ.get("DNSB_UPDATE_CHECK")) and not allow_disabled:
        return None

    now = time.time()
    try:
        interval = float(
            os.environ.get("DNSB_UPDATE_INTERVAL", DEFAULT_CHECK_INTERVAL)
        )
    except ValueError:
        interval = DEFAULT_CHECK_INTERVAL
    path = _cache_path()
    cached = None if force else _read_cache(path, now, interval)

    if cached is None:
        try:
            fetched = _fetch_latest(
                float(os.environ.get("DNSB_UPDATE_TIMEOUT", DEFAULT_TIMEOUT))
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError, HTTPError, URLError):
            return None
        if fetched is None:
            return None
        tag, latest = fetched
        cached = {
            "checked_at": now,
            "latest_version": latest,
            "tag": tag,
        }
        _write_cache(path, cached)

    latest = cached.get("latest_version")
    tag = cached.get("tag")
    if not isinstance(latest, str) or not isinstance(tag, str):
        return None

    current = _parse_version(current_version())
    available = _parse_version(latest)
    if current is None or available is None or available <= current:
        return None
    return UpdateInfo(
        current_version=current_version(),
        latest_version=latest,
        tag=tag,
        url=f"{DEFAULT_REPOSITORY_URL}/tree/{tag}",
    )


def update_notice(info: UpdateInfo) -> str:
    """Format a short, stderr-friendly startup notice."""

    return (
        f"A newer DNSBuilder version is available: {info.current_version} -> "
        f"{info.latest_version}. Run 'dnsb update' to view details or "
        f"'dnsb update --upgrade' to install it."
    )


def install_update(info: UpdateInfo) -> subprocess.CompletedProcess[str]:
    """Install a tagged source revision into the current Python environment."""

    source = os.environ.get(
        "DNSB_UPDATE_SOURCE", f"git+{DEFAULT_REPOSITORY_URL}.git"
    )
    requirement = f"{source}@{info.tag}"
    return subprocess.run(
        [sys.executable, "-m", "pip", "install", "--upgrade", requirement],
        check=False,
        text=True,
    )


__all__ = [
    "DEFAULT_TAGS_URL",
    "UpdateInfo",
    "check_for_update",
    "current_version",
    "install_update",
    "update_notice",
]
