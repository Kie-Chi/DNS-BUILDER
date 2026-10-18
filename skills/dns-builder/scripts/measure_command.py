#!/usr/bin/env python3
"""Measure one deterministic command and write a JSON event.

Example:
    python measure_command.py --out run/commands/build.json \
      --label dnsb-build --log-dir run/logs -- \
      uv run dnsb --no-update-check build main.yml --workdir @config

This records command wall time and process output. It cannot record model API
tokens; the model client must emit model_call events separately.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_env(items: Sequence[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            raise ValueError(f"--env expects KEY=VALUE, got {item!r}")
        key, value = item.split("=", 1)
        if not key:
            raise ValueError("--env key cannot be empty")
        result[key] = value
    return result


def default_log_paths(out: Path, label: str) -> tuple[Path, Path]:
    stem = out.with_suffix("")
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in label)
    return stem.with_name(f"{stem.name}.{safe}.stdout.log"), stem.with_name(
        f"{stem.name}.{safe}.stderr.log"
    )


def run(command: list[str], args: argparse.Namespace) -> int:
    out = args.out.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    cwd = Path(args.cwd).resolve() if args.cwd else Path.cwd().resolve()
    if not cwd.is_dir():
        raise SystemExit(f"cwd does not exist or is not a directory: {cwd}")

    if args.stdout:
        stdout_path = args.stdout.resolve()
    elif args.log_dir:
        stdout_path = args.log_dir.resolve() / f"{args.label}.stdout.log"
    else:
        stdout_path, _ = default_log_paths(out, args.label)
    if args.stderr:
        stderr_path = args.stderr.resolve()
    elif args.log_dir:
        stderr_path = args.log_dir.resolve() / f"{args.label}.stderr.log"
    else:
        _, stderr_path = default_log_paths(out, args.label)
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.parent.mkdir(parents=True, exist_ok=True)

    child_env = os.environ.copy()
    child_env.update(parse_env(args.env))
    start_wall = utc_now()
    start_mono = time.perf_counter()
    returncode: int | None = None
    error: str | None = None
    try:
        with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            process = subprocess.Popen(
                command,
                cwd=str(cwd),
                env=child_env,
                stdout=stdout,
                stderr=stderr,
            )
            returncode = process.wait()
    except FileNotFoundError as exc:
        error = str(exc)
        returncode = 127
    except OSError as exc:
        error = str(exc)
        returncode = 126
    end_mono = time.perf_counter()
    end_wall = utc_now()

    event = {
        "event": "tool_call",
        "label": args.label,
        "argv": command,
        "command_display": shlex.join(command),
        "cwd": str(cwd),
        "t_start": start_wall,
        "t_end": end_wall,
        "duration_s": round(end_mono - start_mono, 6),
        "exit_code": returncode,
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
        "stdout_bytes": stdout_path.stat().st_size if stdout_path.exists() else 0,
        "stderr_bytes": stderr_path.stat().st_size if stderr_path.exists() else 0,
        "stdout_sha256": sha256_file(stdout_path) if stdout_path.exists() else None,
        "stderr_sha256": sha256_file(stderr_path) if stderr_path.exists() else None,
        "host": platform.node(),
        "platform": platform.platform(),
        "python": sys.version.split()[0],
    }
    if error:
        event["error"] = error
    out.write_text(json.dumps(event, indent=2, ensure_ascii=False) + "\n")
    return int(returncode)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run one command and write a JSON timing event."
    )
    parser.add_argument("--out", type=Path, required=True, help="JSON event path")
    parser.add_argument("--label", default="command", help="Short event/log label")
    parser.add_argument("--log-dir", type=Path, help="Directory for stdout/stderr logs")
    parser.add_argument("--stdout", type=Path, help="Explicit stdout log path")
    parser.add_argument("--stderr", type=Path, help="Explicit stderr log path")
    parser.add_argument("--cwd", type=Path, help="Child process working directory")
    parser.add_argument(
        "--env", action="append", default=[], help="Extra environment KEY=VALUE"
    )
    parser.add_argument(
        "command", nargs=argparse.REMAINDER, help="Command after a -- separator"
    )
    args = parser.parse_args()
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("provide a command after --")
    return run(command, args)


if __name__ == "__main__":
    raise SystemExit(main())
