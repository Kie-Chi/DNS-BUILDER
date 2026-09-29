"""DNSSEC signing tool discovery and execution.

The builder signs zones while it is generating artifacts.  This module keeps
that build-time dependency out of the DNS server images and provides two
execution backends:

* ``host`` resolves BIND utilities on the build host and can optionally install
  the corresponding package when explicitly enabled.
* ``docker`` runs the utilities in one user-selected, ephemeral container.

PowerDNS metadata is intentionally not handled here; the metadata writer uses
the Python standard library's sqlite3 module.
"""

from __future__ import annotations

import os
import platform
import shlex
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, Mapping, Optional, Sequence

from ..exceptions import BuildError

logger = __import__("logging").getLogger(__name__)


class DnssecToolError(BuildError):
    """Raised when a DNSSEC utility cannot be discovered or executed."""


TOOL_ENV_VARS: Mapping[str, str] = {
    "dnssec-keygen": "BIND_DNSSEC_KEYGEN",
    "dnssec-signzone": "BIND_DNSSEC_SIGNZONE",
    "dnssec-dsfromkey": "BIND_DNSSEC_DSFROMKEY",
    "named-checkzone": "BIND_DNSSEC_CHECKZONE",
}

TOOL_PACKAGES: Mapping[str, Mapping[str, str]] = {
    "debian": {
        "dnssec-keygen": "bind9-utils",
        "dnssec-signzone": "bind9-utils",
        "dnssec-dsfromkey": "bind9-utils",
        "named-checkzone": "bind9-utils",
    },
    "ubuntu": {
        "dnssec-keygen": "bind9-utils",
        "dnssec-signzone": "bind9-utils",
        "dnssec-dsfromkey": "bind9-utils",
        "named-checkzone": "bind9-utils",
    },
    "fedora": {
        "dnssec-keygen": "bind-utils",
        "dnssec-signzone": "bind-utils",
        "dnssec-dsfromkey": "bind-utils",
        "named-checkzone": "bind-utils",
    },
    "rhel": {
        "dnssec-keygen": "bind-utils",
        "dnssec-signzone": "bind-utils",
        "dnssec-dsfromkey": "bind-utils",
        "named-checkzone": "bind-utils",
    },
    "centos": {
        "dnssec-keygen": "bind-utils",
        "dnssec-signzone": "bind-utils",
        "dnssec-dsfromkey": "bind-utils",
        "named-checkzone": "bind-utils",
    },
    "alpine": {
        "dnssec-keygen": "bind-tools",
        "dnssec-signzone": "bind-tools",
        "dnssec-dsfromkey": "bind-tools",
        "named-checkzone": "bind-tools",
    },
    "macos": {
        "dnssec-keygen": "bind",
        "dnssec-signzone": "bind",
        "dnssec-dsfromkey": "bind",
        "named-checkzone": "bind",
    },
}

KNOWN_TOOL_DIRS = (
    "/usr/bin",
    "/usr/sbin",
    "/usr/local/bin",
    "/usr/local/sbin",
    "/opt/homebrew/bin",
    "/opt/homebrew/sbin",
    "/opt/homebrew/opt/bind/bin",
    "/usr/local/opt/bind/bin",
)

# The default Docker runner is self-contained: it builds this local Dockerfile
# when the image is absent.  Users with a private registry or a prebuilt BIND
# image can still override it through the top-level ``util_image`` setting.
DEFAULT_DNSSEC_TOOL_IMAGE = "dnsbuilder/dnssec-tools:9.18.4"
DEFAULT_DNSSEC_TOOL_DOCKERFILE = "resources/images/dnssec_tools/Dockerfile"


def _os_id() -> str:
    """Return a normalized host OS identifier."""
    if platform.system().lower() == "darwin":
        return "macos"
    if platform.system().lower() == "windows":
        return "windows"
    try:
        values: Dict[str, str] = {}
        with open("/etc/os-release", encoding="utf-8") as handle:
            for line in handle:
                if "=" in line:
                    key, value = line.rstrip().split("=", 1)
                    values[key] = value.strip('"')
        return (values.get("ID") or values.get("ID_LIKE", "").split()[0] or "linux").lower()
    except OSError:
        return platform.system().lower()


def _auto_install_enabled(config: Mapping[str, object]) -> bool:
    value = os.environ.get("DNSSEC_AUTO_INSTALL")
    if value is not None:
        return value.lower() in {"1", "true", "yes", "on"}
    return bool(config.get("util_auto_install", False))


@dataclass
class DnssecToolRunner:
    """Common interface used by zone signing and DNSSEC re-signing."""

    mode: str
    image: Optional[str] = None
    paths: Dict[str, str] = field(default_factory=dict)

    def preflight(self, required_tools: Iterable[str]) -> None:
        raise NotImplementedError

    def resolve(self, tool: str) -> str:
        raise NotImplementedError

    def run(
        self,
        tool: str,
        args: Sequence[object],
        cwd: Path,
        *,
        env: Optional[Mapping[str, str]] = None,
    ) -> subprocess.CompletedProcess:
        raise NotImplementedError


@dataclass
class HostDnssecToolRunner(DnssecToolRunner):
    """Resolve and execute DNSSEC utilities on the build host."""

    mode: str = "host"
    auto_install: bool = False
    os_id: str = field(default_factory=_os_id)

    def _explicit_value(self, tool: str) -> Optional[str]:
        variable = TOOL_ENV_VARS.get(tool)
        if not variable:
            return None
        value = os.environ.get(variable)
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise DnssecToolError(f"{variable} is set but empty; unset it or provide a valid executable")
        candidate = Path(value).expanduser()
        if candidate.is_absolute() or "/" in value:
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)
            raise DnssecToolError(f"{variable}={value!r} does not point to an executable")
        resolved = shutil.which(value)
        if resolved:
            return resolved
        raise DnssecToolError(f"{variable}={value!r} was not found on PATH")

    def _locate(self, tool: str) -> Optional[str]:
        explicit = self._explicit_value(tool)
        if explicit:
            return explicit
        resolved = shutil.which(tool)
        if resolved:
            return resolved
        for directory in KNOWN_TOOL_DIRS:
            candidate = Path(directory) / tool
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)
        return None

    def _install(self, tool: str) -> None:
        package = TOOL_PACKAGES.get(self.os_id, {}).get(tool)
        if not package:
            raise DnssecToolError(
                f"{tool} was not found and automatic installation is unsupported for OS {self.os_id!r}"
            )
        if self.os_id in {"debian", "ubuntu"}:
            commands = [["apt-get", "update"], ["apt-get", "install", "-y", package]]
        elif self.os_id in {"fedora", "rhel", "centos"}:
            manager = shutil.which("dnf") or shutil.which("yum")
            if not manager:
                raise DnssecToolError(f"No dnf/yum package manager found for {self.os_id}")
            commands = [[manager, "install", "-y", package]]
        elif self.os_id == "alpine":
            commands = [["apk", "add", "--no-cache", package]]
        elif self.os_id == "macos":
            manager = shutil.which("brew")
            if not manager:
                raise DnssecToolError(
                    "Homebrew was not found; install BIND or set BIND_DNSSEC_* explicitly"
                )
            # Homebrew's bind formula supplies all four utilities.  Install it
            # once even though the runner may be resolving a single command.
            commands = [[manager, "install", package]]
        else:
            raise DnssecToolError(f"No package installation mapping for OS {self.os_id!r}")
        for command in commands:
            logger.info("Installing DNSSEC dependency: %s", shlex.join(command))
            try:
                subprocess.run(command, check=True, capture_output=True, text=True)
            except (OSError, subprocess.CalledProcessError) as exc:
                detail = getattr(exc, "stderr", None) or str(exc)
                raise DnssecToolError(f"Failed to install {package} for {tool}: {detail}") from exc

    def resolve(self, tool: str) -> str:
        if tool in self.paths:
            return self.paths[tool]
        path = self._locate(tool)
        if path is None and self.auto_install:
            self._install(tool)
            path = self._locate(tool)
        if path is None:
            package = TOOL_PACKAGES.get(self.os_id, {}).get(tool, "the BIND DNSSEC utilities")
            env_name = TOOL_ENV_VARS.get(tool, "the tool override variable")
            raise DnssecToolError(
                f"{tool} was not found. Tried {env_name}, PATH, and known paths; "
                f"OS={self.os_id}. Install {package} or set {env_name} explicitly."
            )
        self.paths[tool] = path
        logger.debug("Resolved DNSSEC tool %s -> %s", tool, path)
        return path

    def preflight(self, required_tools: Iterable[str]) -> None:
        for tool in required_tools:
            self.resolve(tool)

    def run(self, tool: str, args: Sequence[object], cwd: Path, *, env=None):
        command = [self.resolve(tool), *(str(arg) for arg in args)]
        return subprocess.run(
            command,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=True,
            env=dict(env) if env else None,
        )


@dataclass
class DockerDnssecToolRunner(DnssecToolRunner):
    """Run DNSSEC utilities in an ephemeral container."""

    mode: str = "docker"
    image: Optional[str] = None
    docker_command: str = "docker"
    auto_build: bool = True

    def _docker(self, args: Sequence[str], *, check: bool = True) -> subprocess.CompletedProcess:
        command = [self.docker_command, *args]
        try:
            return subprocess.run(command, capture_output=True, text=True, check=check)
        except FileNotFoundError as exc:
            raise DnssecToolError("Docker executable was not found; util_mode=docker requires a Docker daemon") from exc
        except subprocess.CalledProcessError as exc:
            detail = exc.stderr.strip() or exc.stdout.strip() or str(exc)
            raise DnssecToolError(f"Docker command failed: {shlex.join(command)}: {detail}") from exc

    def _default_dockerfile(self) -> Path:
        package_root = Path(__file__).resolve().parents[1]
        dockerfile = package_root / DEFAULT_DNSSEC_TOOL_DOCKERFILE
        if not dockerfile.is_file():
            raise DnssecToolError(
                f"Bundled DNSSEC utility Dockerfile is missing: {dockerfile}"
            )
        return dockerfile

    def _build_default_image(self) -> None:
        dockerfile = self._default_dockerfile()
        assert self.image is not None
        logger.info(
            "Building bundled DNSSEC utility image %s from %s",
            self.image,
            dockerfile,
        )
        self._docker(
            [
                "build",
                "--pull=false",
                "-f",
                str(dockerfile),
                "-t",
                self.image,
                str(dockerfile.parent),
            ]
        )

    def _check_image(self) -> None:
        if self.image is None:
            self.image = DEFAULT_DNSSEC_TOOL_IMAGE
        inspected = self._docker(["image", "inspect", self.image], check=False)
        if inspected.returncode == 0:
            return
        if not self.auto_build:
            raise DnssecToolError(
                f"util_image={self.image!r} is not available locally; "
                "load or build it before using util_mode=docker"
            )
        self._build_default_image()

    def resolve(self, tool: str) -> str:
        if tool in self.paths:
            return self.paths[tool]
        self._check_image()
        variable = TOOL_ENV_VARS.get(tool)
        command = os.environ.get(variable, tool) if variable else tool
        if not command.strip():
            raise DnssecToolError(f"{variable} is set but empty")
        # Check inside the image.  A command path/name from the override is
        # deliberately not resolved on the host.
        probe = [
            "run", "--rm", "--network", "none", "--entrypoint", "/bin/sh",
            self.image, "-c", f"command -v -- {shlex.quote(command)}",
        ]
        result = self._docker(probe, check=False)
        if result.returncode != 0:
            raise DnssecToolError(f"{command!r} is not executable in util_image={self.image!r}")
        self.paths[tool] = command
        return command

    def preflight(self, required_tools: Iterable[str]) -> None:
        self._check_image()
        for tool in required_tools:
            self.resolve(tool)

    @staticmethod
    def _container_arg(arg: object, cwd: Path) -> str:
        value = str(arg)
        try:
            relative = Path(value).resolve().relative_to(cwd.resolve())
        except (ValueError, OSError):
            return value
        return f"/work/{relative.as_posix()}"

    def run(self, tool: str, args: Sequence[object], cwd: Path, *, env=None):
        command = self.resolve(tool)
        host_cwd = cwd.resolve()
        uid = str(os.getuid()) if hasattr(os, "getuid") else "0"
        gid = str(os.getgid()) if hasattr(os, "getgid") else "0"
        docker_args = [
            "run", "--rm", "--network", "none",
            "--user", f"{uid}:{gid}",
            "-v", f"{host_cwd}:/work:rw", "-w", "/work",
        ]
        if env:
            # Keep the runner interface consistent across host and docker
            # modes without copying the host process environment wholesale.
            for key, value in env.items():
                docker_args.extend(["-e", f"{key}={value}"])
        docker_args.extend(["--entrypoint", command, self.image])
        docker_args.extend(self._container_arg(arg, host_cwd) for arg in args)
        return self._docker(docker_args)


def create_dnssec_tool_runner(config: Mapping[str, object]) -> DnssecToolRunner:
    """Create a tool runner from the project-level utility settings."""
    mode = str(config.get("util_mode", "host")).lower()
    if mode == "host":
        return HostDnssecToolRunner(auto_install=_auto_install_enabled(config))
    if mode == "docker":
        configured_image = config.get("util_image") or None
        return DockerDnssecToolRunner(
            image=configured_image,
            auto_build=configured_image is None,
        )
    raise DnssecToolError("util_mode must be either 'host' or 'docker'")
