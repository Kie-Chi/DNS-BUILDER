#!/usr/bin/env python3
"""Create a stable, mtime-independent manifest for a source or build tree.

The manifest omits no files by default except metadata/cache directories and
Python bytecode. Add --ignore for run logs or known dynamic artifacts. The
tree_sha256 is based on relative paths, file sizes, and content hashes, so the
absolute checkout path and mtimes do not affect it.

Example:
    python manifest.py --root output/paper-case --out run/manifest.json \
      --ignore '*.log' --ignore '*/.dnsb_cache/*'
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
from pathlib import Path
from typing import Iterable


DEFAULT_IGNORES = (
    ".git",
    ".dnsb_cache",
    "__pycache__",
    "*.pyc",
)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ignored(relative: str, patterns: Iterable[str]) -> bool:
    posix = relative.replace(os.sep, "/")
    basename = posix.rsplit("/", 1)[-1]
    return any(
        fnmatch.fnmatch(posix, pattern)
        or fnmatch.fnmatch(basename, pattern)
        or posix == pattern
        or posix.startswith(pattern.rstrip("/") + "/")
        for pattern in patterns
    )


def collect(root: Path, patterns: tuple[str, ...], output: Path | None) -> list[dict]:
    records: list[dict] = []
    output_resolved = output.resolve() if output else None
    for current, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        rel_current = current_path.relative_to(root)
        kept_dirs: list[str] = []
        for dirname in sorted(dirnames):
            rel = (rel_current / dirname).as_posix()
            path = current_path / dirname
            if ignored(rel, patterns) or (path / ".git").is_dir():
                continue
            kept_dirs.append(dirname)
        dirnames[:] = kept_dirs
        for filename in sorted(filenames):
            path = current_path / filename
            rel = path.relative_to(root).as_posix()
            if output_resolved and path.resolve() == output_resolved:
                continue
            if ignored(rel, patterns):
                continue
            if path.is_symlink():
                target = os.readlink(path)
                records.append(
                    {
                        "path": rel,
                        "type": "symlink",
                        "target": target,
                        "sha256": sha256_bytes(target.encode()),
                    }
                )
            elif path.is_file():
                records.append(
                    {
                        "path": rel,
                        "type": "file",
                        "bytes": path.stat().st_size,
                        "sha256": sha256_file(path),
                    }
                )
    return records


def tree_hash(records: list[dict]) -> str:
    digest = hashlib.sha256()
    for record in records:
        line = json.dumps(record, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        digest.update((line + "\n").encode())
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Write a stable artifact manifest.")
    parser.add_argument("--root", type=Path, required=True, help="Tree to enumerate")
    parser.add_argument("--out", type=Path, required=True, help="Manifest JSON path")
    parser.add_argument(
        "--ignore",
        action="append",
        default=[],
        help="Relative path or fnmatch pattern to omit; may be repeated",
    )
    args = parser.parse_args()

    root = args.root.resolve()
    if not root.is_dir():
        parser.error(f"root is not a directory: {root}")
    out = args.out.resolve()
    patterns = tuple(DEFAULT_IGNORES) + tuple(args.ignore)
    records = collect(root, patterns, out)
    records.sort(key=lambda item: item["path"])
    payload = {
        "schema_version": 1,
        "root": ".",
        "ignore": list(patterns),
        "file_count": len(records),
        "tree_sha256": tree_hash(records),
        "files": records,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    print(f"manifest: {out}")
    print(f"files: {len(records)}")
    print(f"tree_sha256: {payload['tree_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
