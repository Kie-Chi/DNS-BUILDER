#!/usr/bin/env python3
"""Run an end-to-end paper-to-DNS-BUILDER evaluation episode.

The runner deliberately keeps model interaction and deterministic acceptance
separate.  API/command providers return a JSON file bundle; the native
``agent`` provider instead lets Codex or Claude Code write an isolated project
workspace directly and preserves its JSONL stream plus an ATIF trajectory. The
runner builds the resulting project with DNS-BUILDER, independently reruns the
model-owned verifier, validates the generated Compose file, optionally starts
the environment, and performs a clean second build. Every provider request,
native agent event, and tool invocation is appended to ``events.jsonl`` so the result can be consumed by
``summarize_events.py``.

The ``fixture`` provider is intentionally offline.  It copies the hidden
golden project for a task and is useful for testing the evaluator itself; its
token usage is reported as unavailable and must not be interpreted as model
performance.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

try:
    from agent_trace import AgentTrace, parse_stream
except ImportError:  # pragma: no cover - package-style imports
    from scripts.evaluation.agent_trace import AgentTrace, parse_stream


RUNNER_VERSION = "6"
MATERIAL_POLICY = "generic-only-v1"
FIXTURE_MATERIAL_POLICY = "fixture-only-v1"
COMMON_SKILL_FILES = (
    "skills/dns-builder/SKILL.md",
    "skills/dns-builder/references/source-map.md",
    "skills/dns-builder/references/configuration.md",
    "skills/dns-builder/references/topology.md",
    "skills/dns-builder/references/dnssec.md",
    "skills/dns-builder/references/zone-mutation.md",
    "skills/dns-builder/references/runtime.md",
    "skills/dns-builder/references/reproduction.md",
    "skills/dns-builder/references/example-patterns.md",
    "skills/dns-builder/references/evaluation.md",
    "skills/dns-builder/assets/basic/main.yml",
    "skills/dns-builder/assets/basic/verify.sh",
    "skills/dns-builder/scripts/manifest.py",
    "skills/dns-builder/scripts/measure_command.py",
    "skills/dns-builder/scripts/summarize_events.py",
)
GENERIC_REFERENCE_FILES = frozenset(COMMON_SKILL_FILES) | frozenset(
    {
        "doc/config/index.md",
        "doc/config/top-level.md",
        "doc/config/images.md",
        "doc/config/external-images.md",
        "doc/config/builds.md",
        "doc/config/auto.md",
        "doc/config/processing-pipeline.md",
        "doc/rule/build-templates.md",
        "doc/rule/behavior-dsl.md",
        "doc/rule/builtins-and-placeholders.md",
        "doc/rule/paths-and-fs.md",
        "doc/rule/merge-and-override.md",
        "doc/dnssec.md",
        "doc/cli.md",
    }
)
DEFAULT_MODEL = "gpt-5.2"
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_REFERENCE_CHARS = 120_000
MAX_REPAIR_CHARS = 16_000

# A model-owned verification report is part of the episode artifact.  Keeping
# the names deliberately small makes the contract portable between Codex,
# Claude Code, and bundle adapters while still allowing a project to organize
# its supporting files below ``scripts/`` or ``artifacts/``.
VERIFICATION_SCRIPT_NAMES = (
    "verify.sh",
    "verify.bash",
    "verify.py",
    "scripts/verify.sh",
    "scripts/verify.bash",
    "scripts/verify.py",
)
VERIFICATION_REPORT_NAMES = (
    "verification-report.json",
    "verification_report.json",
    "artifacts/verification-report.json",
    "artifacts/verification_report.json",
)


class PendingHumanReview(Exception):
    """Pause after model verification so blank can receive human final review."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_tree(root: Path) -> str:
    """Hash relative paths and file bytes without mtime or absolute paths."""

    digest = hashlib.sha256()
    if not root.is_dir():
        return digest.hexdigest()
    for path in sorted(
        item
        for item in root.rglob("*")
        if item.is_file()
        and "__pycache__" not in item.parts
        and item.suffix != ".pyc"
    ):
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        digest.update(b"\n")
    return digest.hexdigest()


def safe_label(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in value)


def tail_text(path: Path, limit: int = 8_000) -> str:
    if not path.exists():
        return ""
    data = path.read_bytes()
    return data[-limit:].decode("utf-8", errors="replace")


def git_value(repo_root: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = result.stdout.strip()
    return value if result.returncode == 0 and value else None


def import_yaml() -> Any:
    try:
        import yaml  # type: ignore

        return yaml
    except ImportError:
        return None


class EventLog:
    """Append one structured event per line and assign a monotonic sequence."""

    def __init__(self, path: Path, run_id: str):
        self.path = path
        self.run_id = run_id
        self.seq = 0
        self.model_latency_seconds = 0.0
        self.tool_seconds = 0.0
        self.model_verification_seconds = 0.0
        self.model_usage: dict[str, int | None] = empty_usage()
        path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, event: str, **fields: Any) -> dict[str, Any]:
        self.seq += 1
        payload: dict[str, Any] = {
            "event": event,
            "run_id": self.run_id,
            "seq": self.seq,
            "t": utc_now(),
        }
        payload.update(fields)
        if event == "model_call":
            duration = fields.get("duration_s")
            if isinstance(duration, (int, float)) and not isinstance(duration, bool):
                self.model_latency_seconds += float(duration)
            usage = fields.get("usage")
            if isinstance(usage, dict):
                for key in self.model_usage:
                    value = usage.get(key)
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        self.model_usage[key] = int(value) if self.model_usage[key] is None else int(self.model_usage[key]) + int(value)
        elif event == "tool_call":
            duration = fields.get("duration_s")
            if isinstance(duration, (int, float)) and not isinstance(duration, bool):
                self.tool_seconds += float(duration)
        elif event == "acceptance" and fields.get("stage") == "model-verification":
            duration = fields.get("verification_seconds")
            if isinstance(duration, (int, float)) and not isinstance(duration, bool):
                self.model_verification_seconds += float(duration)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return payload


@dataclass
class CommandResult:
    argv: list[str]
    exit_code: int
    duration_s: float
    stdout_path: Path
    stderr_path: Path
    timed_out: bool = False
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


def run_command(
    argv: Sequence[str],
    *,
    label: str,
    cwd: Path,
    log_dir: Path,
    events: EventLog,
    timeout: float,
    env: Mapping[str, str] | None = None,
    stdin: bytes | None = None,
) -> CommandResult:
    """Run a fixed command, save raw output, and emit a tool_call event."""

    log_dir.mkdir(parents=True, exist_ok=True)
    stem = safe_label(label)
    stdout_path = log_dir / f"{stem}.stdout.log"
    stderr_path = log_dir / f"{stem}.stderr.log"
    child_env = os.environ.copy()
    if env:
        child_env.update(env)
    start = time.perf_counter()
    exit_code = 126
    timed_out = False
    error: str | None = None
    stdout_data = b""
    stderr_data = b""
    try:
        process = subprocess.Popen(
            list(argv),
            cwd=str(cwd),
            env=child_env,
            stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        try:
            stdout_data, stderr_data = process.communicate(stdin, timeout=timeout)
            exit_code = process.returncode
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            stdout_data = exc.stdout or b""
            stderr_data = exc.stderr or b""
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except OSError:
                process.kill()
            more_out, more_err = process.communicate()
            stdout_data += more_out or b""
            stderr_data += more_err or b""
            exit_code = 124
            error = f"command timed out after {timeout:g}s"
    except FileNotFoundError as exc:
        error = str(exc)
        exit_code = 127
    except OSError as exc:
        error = str(exc)
        exit_code = 126
    duration = time.perf_counter() - start
    stdout_path.write_bytes(stdout_data)
    stderr_path.write_bytes(stderr_data)
    event: dict[str, Any] = {
        "tool": "shell",
        "label": label,
        "argv": list(argv),
        "command_display": shlex.join(list(argv)),
        "cwd": str(cwd),
        "duration_s": round(duration, 6),
        "exit_code": exit_code,
        "timed_out": timed_out,
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
        "stdout_bytes": len(stdout_data),
        "stderr_bytes": len(stderr_data),
        "stdout_sha256": sha256_bytes(stdout_data),
        "stderr_sha256": sha256_bytes(stderr_data),
    }
    if error:
        event["error"] = error
    events.write("tool_call", **event)
    return CommandResult(
        argv=list(argv),
        exit_code=exit_code,
        duration_s=duration,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        timed_out=timed_out,
        error=error,
    )


def resolve_task(repo_root: Path, task_arg: str) -> tuple[dict[str, Any], Path]:
    candidate = Path(task_arg)
    if not candidate.is_absolute():
        direct = repo_root / candidate
        by_id = repo_root / "scripts" / "evaluation" / "tasks" / f"{task_arg}.json"
        candidate = direct if direct.exists() else by_id
    candidate = candidate.resolve()
    if not candidate.is_file():
        raise FileNotFoundError(f"task definition not found: {candidate}")
    task = json.loads(candidate.read_text(encoding="utf-8"))
    if not isinstance(task, dict) or not isinstance(task.get("task_id"), str):
        raise ValueError(f"invalid task definition: {candidate}")
    return task, candidate


def resolve_repo_path(repo_root: Path, value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (repo_root / path).resolve()


def extract_pdf(
    pdf_path: Path, input_dir: Path, events: EventLog, log_dir: Path, timeout: float
) -> tuple[str, str, int]:
    """Extract layout-preserving text and save one file per PDF page."""

    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")
    pdf_copy = input_dir / "paper.pdf"
    pdf_copy.parent.mkdir(parents=True, exist_ok=True)
    if pdf_path.resolve() != pdf_copy.resolve():
        shutil.copy2(pdf_path, pdf_copy)
    pdf_sha = sha256_file(pdf_copy)
    text_path = input_dir / "pdf.txt"
    pages_dir = input_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    pdftotext = shutil.which("pdftotext")
    start = time.perf_counter()
    method = "pdftotext"
    error: str | None = None
    text = ""
    if pdftotext:
        result = run_command(
            [pdftotext, "-layout", str(pdf_copy), str(text_path)],
            label="pdf-extract",
            cwd=input_dir,
            log_dir=log_dir,
            events=events,
            timeout=timeout,
        )
        if result.ok and text_path.exists():
            text = text_path.read_text(encoding="utf-8", errors="replace")
        else:
            error = tail_text(result.stderr_path)
    if not text:
        method = "pypdf"
        try:
            from pypdf import PdfReader  # type: ignore

            reader = PdfReader(str(pdf_copy))
            pages = [(page.extract_text() or "") for page in reader.pages]
            text = "\f".join(pages)
            text_path.write_text(text, encoding="utf-8")
        except Exception as exc:  # pragma: no cover - depends on local PDF stack
            error = error or str(exc)
    if not text.strip():
        events.write(
            "pdf_extract",
            status="fail",
            pdf_path=str(pdf_copy),
            pdf_sha256=pdf_sha,
            method=method,
            duration_s=round(time.perf_counter() - start, 6),
            error=error or "no text extracted",
        )
        raise RuntimeError(f"could not extract text from PDF: {error or 'empty output'}")
    pages = text.split("\f")
    # pdftotext commonly appends one trailing form-feed after the final page;
    # do not count that sentinel as a paper page.
    while len(pages) > 1 and not pages[-1].strip():
        pages.pop()
    text = "\f".join(pages)
    text_path.write_text(text, encoding="utf-8")
    for old in pages_dir.glob("page-*.txt"):
        old.unlink()
    for index, page in enumerate(pages, start=1):
        (pages_dir / f"page-{index:03d}.txt").write_text(page, encoding="utf-8")
    # Keep rasterized pages for audit and optional multimodal/local-model
    # adapters.  The text prompt remains the portable baseline input.
    pdftoppm = shutil.which("pdftoppm")
    rendered_dir = pages_dir / "rendered"
    rendered_dir.mkdir(parents=True, exist_ok=True)
    for rendered in rendered_dir.glob("page-*.png"):
        rendered.unlink()
    if pdftoppm:
        render_result = run_command(
            [pdftoppm, "-png", "-r", "120", str(pdf_copy), str(rendered_dir / "page")],
            label="pdf-render",
            cwd=input_dir,
            log_dir=log_dir,
            events=events,
            timeout=timeout,
        )
        rendered_count = len(list(rendered_dir.glob("page-*.png")))
        events.write(
            "pdf_render",
            status="pass" if render_result.ok and rendered_count else "fail",
            directory=str(rendered_dir),
            pages=rendered_count,
        )
    else:
        events.write("pdf_render", status="not_run", reason="pdftoppm not found", directory=str(rendered_dir), pages=0)
    events.write(
        "pdf_extract",
        status="pass",
        pdf_path=str(pdf_copy),
        pdf_sha256=pdf_sha,
        method=method,
        duration_s=round(time.perf_counter() - start, 6),
        chars=len(text),
        pages=len(pages),
        text_path=str(text_path),
    )
    return text, pdf_sha, len(pages)


def generic_reference_path(repo_root: Path, relative: str) -> Path:
    """Resolve a reviewed file without permitting symlink aliases to answers."""

    if relative not in GENERIC_REFERENCE_FILES:
        raise ValueError(f"Reference is outside the generic-only allowlist: {relative!r}")
    root = repo_root.resolve()
    path = root / relative
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"Generic reference escapes the repository: {relative}")
    if resolved != path:
        raise ValueError(f"Generic reference is a symlink alias: {relative}")
    if not path.is_file():
        raise FileNotFoundError(f"Generic reference is missing: {relative}")
    return path


def read_reference(repo_root: Path, relative: str) -> str:
    path = generic_reference_path(repo_root, relative)
    content = path.read_text(encoding="utf-8", errors="replace")
    if len(content) > MAX_REFERENCE_CHARS:
        content = content[:MAX_REFERENCE_CHARS] + "\n[reference truncated by runner]"
    return content


def task_material_paths(task: Mapping[str, Any]) -> list[str]:
    """Select reusable tool material, never a task's solution or evaluator data."""

    paths = list(COMMON_SKILL_FILES)
    for key in ("skill_reference_files", "agent_material_files", "reference_files"):
        values = task.get(key, [])
        if values is None:
            values = []
        if not isinstance(values, list):
            raise ValueError(f"{key} must be a list of generic reference paths")
        for value in values:
            if not isinstance(value, str) or value not in GENERIC_REFERENCE_FILES:
                raise ValueError(f"Reference is outside the generic-only allowlist: {value!r}")
            if value not in paths:
                paths.append(value)
    return paths


def skill_material(repo_root: Path, task: Mapping[str, Any] | None = None) -> str:
    paths = [
        path for path in task_material_paths(task or {})
        if path.startswith("skills/dns-builder/")
    ]
    chunks = []
    for relative in paths:
        chunks.append(f"\n===== {relative} =====\n{read_reference(repo_root, relative)}")
    return "".join(chunks)


def compact_pdf_for_prompt(
    pdf_text: str, max_chars: int, needles: Sequence[str] | None = None
) -> str:
    """Keep the paper evidence that is relevant to the task under a hard cap.

    The extracted PDF can contain figures, references, and repeated headers that
    do not help a coding agent construct the target.  When truncation is needed
    retain the opening pages and every page mentioning the task or its topology,
    then fill remaining space in original order.  Both experimental conditions
    use this identical selection, and the complete PDF remains in ``input/``.
    """

    if max_chars <= 0 or len(pdf_text) <= max_chars:
        return pdf_text
    pages = pdf_text.split("\f")
    preferred: list[int] = []
    needles = tuple(needles or ("dns", "attack", "resolver", "configuration"))
    for index, page in enumerate(pages):
        lowered = page.lower()
        if any(needle.lower() in lowered for needle in needles):
            preferred.append(index)

    # The old greedy selection filled the cap with the opening pages and then
    # silently dropped the paper's later evaluation/topology pages.  That is
    # especially harmful for a blank coding agent: it sees the definition of
    # an attack but not the concrete experiment it must reproduce.  Keep the
    # opening pages and every page matching the task needles, distributing the
    # cap across those pages.  Long pages are clipped at both ends so section
    # headings and conclusions survive together.
    target_order: list[int] = []
    for index in list(range(min(2, len(pages)))) + preferred:
        if index not in target_order:
            target_order.append(index)

    def clip_page(page: str, budget: int) -> str:
        if len(page) <= budget:
            return page
        marker = "\n[runner clipped this paper page excerpt]\n"
        if budget <= len(marker) + 2:
            return page[:budget]
        left = max(1, (budget - len(marker)) // 2)
        right = max(1, budget - len(marker) - left)
        return page[:left] + marker + page[-right:]

    if target_order:
        # A small floor keeps a short but relevant page from consuming all of
        # the budget while still preserving evidence across the paper.
        base = max_chars // len(target_order)
        budgets = {index: base for index in target_order}
        remaining = max_chars - base * len(target_order)
        for index in target_order:
            if remaining <= 0:
                break
            extra = min(remaining, max(0, len(pages[index]) - budgets[index]))
            budgets[index] += extra
            remaining -= extra
        selected = target_order
        snippets = [clip_page(pages[index], budgets[index]) for index in selected]
    else:
        selected = []
        used = 0
        for index, page in enumerate(pages):
            extra = len(page) + (1 if selected else 0)
            if selected and used + extra > max_chars:
                break
            selected.append(index)
            used += extra
        snippets = [pages[index] for index in selected]
    omitted = len(pages) - len(selected)
    result = "\f".join(snippets)
    return result + f"\n\n[runner retained {len(selected)}/{len(pages)} paper pages; {omitted} pages omitted from the model prompt; full PDF is archived in input/paper.pdf]"


def stage_agent_material(
    workspace: Path,
    *,
    repo_root: Path,
    task: Mapping[str, Any],
    pdf_text: str,
    condition: str,
) -> Path:
    """Stage controlled, condition-specific inputs inside an agent workspace.

    Workspace agents otherwise receive the entire paper and skill inline on
    every stateless Responses request.  Staging the same bytes as readable
    files makes the first request small and lets the model retrieve only the
    section it needs.  The directory is transient and removed before the
    workspace becomes an episode artifact.
    """

    material = workspace / ".runner-material"
    if material.exists():
        shutil.rmtree(material)
    material.mkdir(parents=True, exist_ok=True)
    (material / "paper.txt").write_text(pdf_text, encoding="utf-8")
    # Both conditions receive the same public requirement. Evaluator paths,
    # expected topology, thresholds, runtime commands, and rubric stay hidden.
    public_task = {
        key: task.get(key)
        for key in ("task_id", "title", "instructions")
        if task.get(key) is not None
    }
    (material / "task.json").write_text(
        json.dumps(public_task, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if condition == "dns-builder":
        for relative in task_material_paths(task):
            source = generic_reference_path(repo_root, relative)
            target = material / "references" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    return material


def remove_transient_agent_material(workspace: Path) -> None:
    for name in (".runner-material", ".runner-evaluation-context.txt"):
        path = workspace / name
        if path.exists():
            shutil.rmtree(path) if path.is_dir() else path.unlink()


def build_prompt(
    *,
    task: dict[str, Any],
    pdf_text: str,
    repo_root: Path,
    condition: str,
    repair: str | None = None,
    max_pdf_chars: int,
    workspace_mode: bool = False,
) -> str:
    is_blank = condition == "blank"
    is_dns_builder = condition == "dns-builder"
    references = [] if is_blank else [
        path for path in task_material_paths(task)
        if not path.startswith("skills/dns-builder/")
    ]
    public: list[str] = []
    skill = ""
    if workspace_mode:
        # Full evidence and the condition-specific skill are staged below the
        # workspace and can be retrieved through the native tools.  The first
        # request therefore contains only a small index, while the complete
        # paper remains available for precise page-level inspection.
        if is_blank:
            # Give the blank agent a bounded, page-labelled excerpt in the
            # first request.  This is still paper-only evidence, while
            # avoiding a long turn that merely dumps the full PDF through a
            # tool before any project files are created.
            paper_excerpt = compact_pdf_for_prompt(
                pdf_text, min(max_pdf_chars, 32_000), task.get("paper_needles")
            )
            pdf_for_prompt = "\n".join(
                f"===== PAGE {index} =====\n{page}"
                for index, page in enumerate(paper_excerpt.split("\f"), start=1)
            )
        else:
            pdf_for_prompt = (
                "The complete extracted paper (with form-feed page breaks) is at "
                "`.runner-material/paper.txt`; use `run_shell` with `rg` or "
                "`read_file` to inspect the relevant attack and evaluation pages."
            )
        if is_dns_builder:
            public_material_notice = (
                "Generic DNS-BUILDER methods, configuration fragments, and a normal "
                "delegation example are staged under `.runner-material/references/`. "
                "Read the skill index and only the techniques you need. Derive the "
                "task's topology, parameters, payload, and verifier from the paper; "
                "no task solution or task-specific verifier is supplied."
            )
        else:
            public_material_notice = "No repository, DNS-BUILDER skill, examples, or reference material is available in the blank condition."
    else:
        for relative in references:
            if isinstance(relative, str):
                public.append(f"\n===== {relative} =====\n{read_reference(repo_root, relative)}")
        pdf_for_prompt = compact_pdf_for_prompt(
            pdf_text, max_pdf_chars, task.get("paper_needles")
        )
        # Preserve page provenance in the prompt so a model can cite evidence
        # without guessing from character offsets.
        pdf_for_prompt = "\n".join(
            f"===== PAGE {index} =====\n{page}"
            for index, page in enumerate(pdf_for_prompt.split("\f"), start=1)
        )
        public_material_notice = ""
        skill = skill_material(repo_root, task) if is_dns_builder else ""
    if workspace_mode:
        if is_blank:
            output_contract = """Work directly in the current empty isolated workspace. Create a complete, self-contained DNS reproduction project using tools you choose. Do not assume this repository, hidden reference files, or pre-existing project assets are available. Include every Dockerfile, Compose file, configuration, script, fixture, and verification file needed to build and run the environment. You MUST include a root `verify.sh` (or `verify.py`) and a root `verification-report.json` contract. The verifier must build or prepare the project, start every required service, execute the paper-grounded DNS queries/trigger, assert the observed RCODE/answer/authority/path behavior, clean up containers/volumes, and write `verification-report.json` with `status: \"pass\"` and a `checks` array. Do not merely describe files in your answer. Keep all files below the workspace, use relative paths, and do not create `.git/`; the evaluator will preserve the workspace as an artifact and a human will review feasibility.

Use a bounded implementation loop so the end-to-end artifact is produced promptly:
1. Read the paper evidence once and extract only the DNS roles, trigger, expected observation, and the minimum parameters needed to reproduce it.
2. Create the complete project within the next few tool calls, then run the root verifier before doing broad investigation.
3. Give Docker, Compose, DNS queries, and any network waits explicit bounded timeouts; make the verifier clean up even after a failed check. Do not depend on downloading arbitrary images or packages at verification time; inspect and use ordinary locally available runtime/base images or standard-library components where possible. Do not assume GNU `timeout` exists; use Docker's own bounded flags or Python subprocess/socket timeouts.
   Before writing Dockerfiles, inspect `docker image ls` and choose a normal reusable local base image (for example a locally cached `python:3.12-slim`, Python/Debian/Ubuntu image). Never reference an image whose name contains an episode workspace, `dnsb-blank-agent`, `dnsb-image-builder`, `project-`, or another generated project/reproduction name; the evaluator will reject cross-episode image dependencies.
4. Make the checks assert the paper's actual topology, delegation/referral or resolver behavior, trigger, and expected observation. A generic DNS answer or a renamed mock does not satisfy the reproduction.
5. The deliverable must include a root `compose.yaml` or `docker-compose.yml` plus the Dockerfiles and service sources it needs. The passing verifier must exercise that Compose environment and record service startup, the DNS trigger, resolver path, and cleanup; a host-only fallback may explain an infrastructure failure but cannot be the only passing path.
6. Write `verification-report.json` with a real JSON serializer (for example Python `json.dump`), validate it with `python3 -m json.tool`, and include a non-empty `checks` array before declaring `status: "pass"`.
7. If verification fails, inspect only the failing command or log, make one targeted repair, and rerun the verifier. Do not repeatedly reread unchanged paper pages or redesign a working project."""
        else:
            output_contract = """Work directly in the current isolated workspace. Create the complete DNS-BUILDER project on disk, including the task config (normally `main.yml`) and every source/resource file required by build and runtime checks. Include a root `verify.sh` (or `verify.py`) and a root `verification-report.json` contract. Before your final response, use your available tools to run the verifier end to end: build/prepare the environment, start the services, execute the paper-grounded DNS queries/trigger, assert the observed behavior, clean up, and write `verification-report.json` with `status: \"pass\"` and a `checks` array. Merely creating files without executing the verifier is incomplete. Do not merely describe files in your answer. All files must remain below the workspace, use relative paths, and must not create `output/`, `.dnsb_cache/`, or `.git/`; the runner owns generated outputs. You may inspect and edit files with your normal tools. At the end, briefly report what you created; the runner will use the workspace itself as the artifact."""
            output_contract += """

Evaluation execution budget: the wrapper exposes the DNS-BUILDER `dnsb`
executable on PATH. Read `.runner-material/references/skills/dns-builder/SKILL.md`
and select the reusable technique references needed by the paper. The basic
example demonstrates normal delegation only; it is not a task solution.
Derive the required roles, topology, software settings, DNS messages, and
verification assertions from the supplied evidence. Write a self-contained
project, run your verifier, inspect the failing command or log, and repair the
smallest cause while preserving the paper mechanism. Do not inspect hidden
fixtures, other episodes, exported projects, or same-task historical examples.
Use `dnsb --no-update-check build main.yml --workdir @config --output-dir
<bounded-dir>` for generated outputs. The CLI takes the config as a positional
argument; its output base contains `output/<project-name>/docker-compose.yml`.
Stop after a passing report or an explicit infrastructure failure.
"""
        output_contract += """

Tool-surface restriction: use only the adapter's declared local file and shell
tools: `read_file`/`write_file`/`run_shell`, or the native agent's equivalent
Read/Write/Edit/Bash tools. Do not call MCP, CUA, browser, custom host tools,
or an undeclared tool. Keep commands bounded and actions observable in the
runner's tool stream. These restrictions are not an OS sandbox.
"""
    else:
        if is_blank:
            output_contract = """Return exactly one JSON object and no Markdown fences or commentary. The object must have this shape:
{
  "files": {"docker-compose.yml": "...", "resource/example.py": "..."},
  "entrypoint": "docker-compose.yml",
  "verify_path": "verify.sh",
  "notes": "brief assumptions, tool versions, and evidence"
}

The files map is the complete self-contained reproduction project. You may choose Docker Compose, scripts, or another local orchestration format, but include every file needed by a human to build and run it. `verify_path` is mandatory and must point to a shell or Python verifier that builds/prepares the environment, starts all services, executes and asserts the paper-grounded DNS behavior, cleans up, and writes a root `verification-report.json` from actual observations. All paths must be relative POSIX paths, with no '..', no absolute paths, and no generated output directories. Do not refer to repository files or assets that are not present in the files map. This bundle adapter cannot demonstrate model ReAct execution; its output remains diagnostic and cannot receive a positive final review without the required model gates."""
        else:
            output_contract = """Return exactly one JSON object and no Markdown fences or commentary. The object must have this shape:
{
  "config_path": "main.yml",
  "files": {"main.yml": "...", "resource/example.py": "..."},
  "verify_path": "verify.sh",
  "notes": "brief assumptions and evidence"
}

The files map is the complete project source. All paths must be relative POSIX paths, with no '..', no absolute paths, and no generated output directories. Include every file needed by the build and verifier. The runner will write the files, run dnsb build, and validate Compose. Task-owned independent mechanism checks may be unavailable; legacy fixture commands are never requirements for a model project. Do not return shell commands, tool calls, or base64 unless a text file truly requires it."""
    instructions = str(task.get("instructions") or "")
    if is_dns_builder:
        instructions += "\nUse DNS-BUILDER and the generic technique references; infer all task-specific decisions from the supplied paper evidence."
    public_material = (
        f"Public repository material available to you:\n{''.join(public)}"
        if public
        else public_material_notice
    )
    prompt = f"""You are an autonomous DNS-BUILDER project author in a reproducible evaluation.

{output_contract}

Task id: {task.get('task_id')}
Task title: {task.get('title')}
Task instructions:
{instructions}

Paper text extracted with page breaks (form-feed):
----- BEGIN PAPER -----
{pdf_for_prompt}
----- END PAPER -----

{public_material}
{skill}
"""
    if is_blank:
        prompt = prompt.replace(
            "You are an autonomous DNS-BUILDER project author in a reproducible evaluation.",
            "You are an autonomous DNS environment reproduction engineer in a reproducible evaluation.\nYou receive only the paper evidence and the task requirement below. Choose the implementation tools yourself.",
        )
    if workspace_mode:
        prompt += """

===== END-TO-END MODEL VERIFICATION (highest priority) =====
The task is incomplete until you personally execute the verification entrypoint
with your available tools.  Creating Compose files, Dockerfiles, or a verifier
without running it does not count.  The executed checks must cover the complete
paper mechanism: build or prepare the images, start all required services, issue
the relevant DNS queries/trigger, inspect RCODE/answers/authority and the
resolver path (including expected failure/timeout behavior), then clean up.
Leave the exact commands and observed results in `verification-report.json`;
use `status: "pass"` only when every required check passed.  The evaluator will
rerun the same entrypoint and a human will perform only the final feasibility
review after this model-verification gate.
"""
    else:
        prompt += """

===== END-TO-END VERIFICATION CONTRACT (highest priority) =====
Include the mandatory verifier, which must write `verification-report.json`
from actual command outcomes. Never predeclare a passing report for commands
you could not execute. This bundle adapter has no interactive tool channel and
cannot prove ReAct execution; final paired experiments use agent-mode=workspace.
A runner rerun of the verifier is diagnostic, not proof of model execution.
"""
    if not workspace_mode:
        if is_blank:
            prompt += """
===== BLANK BASELINE CONSTRAINT (highest priority) =====
You have no interactive tool channel and no repository reference material. Do not
mention or depend on the current repository, its examples, or hidden files. Return
one complete self-contained JSON bundle matching the output contract.
The evaluator preserves the bundle as diagnostic output. A human cannot mark
it feasible until the model execution and independent rerun gates have passed.
"""
        else:
            prompt += """

===== BUNDLE ADAPTER CONSTRAINT (highest priority) =====
This adapter has no interactive tool channel. Do not call tools, do not inspect the
workspace, and do not describe a plan. Treat the repository material above as
reference text only. Return one complete JSON object matching the output contract
above, including every source file needed for this paper's environment. The runner will
write that object to disk and perform all build and runtime checks.
"""
    if repair:
        repair_instruction = (
            "The previous attempt did not pass the deterministic checks. Diagnose and fix the failure in the current workspace; leave a complete replacement project on disk."
            if workspace_mode
            else "The previous attempt did not pass the deterministic checks. Return a complete replacement JSON bundle, not a patch. Diagnose and fix the failure while preserving the paper mechanism."
        )
        prompt += f"""

{repair_instruction}
----- BEGIN FAILURE REPORT -----
{repair[:MAX_REPAIR_CHARS]}
----- END FAILURE REPORT -----
"""
    return prompt


def extract_json_object(text: str) -> dict[str, Any]:
    """Parse a model response that may contain a single fenced JSON object."""

    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, count=1, flags=re.I)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        starts = [i for i, char in enumerate(cleaned) if char == "{"]
        value = None
        for start in starts:
            try:
                candidate, end = decoder.raw_decode(cleaned[start:])
            except json.JSONDecodeError:
                continue
            if cleaned[start + end :].strip():
                continue
            value = candidate
            break
        if value is None:
            raise ValueError("model response is not one JSON object")
    if not isinstance(value, dict):
        raise ValueError("model JSON must be an object")
    return value


def validate_relative_path(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty relative path")
    path = value.replace("\\", "/")
    pure = PurePosixPath(path)
    if pure.is_absolute() or path.startswith("/") or re.match(r"^[A-Za-z]:", path):
        raise ValueError(f"{field} must be relative: {value!r}")
    if any(part in ("", ".", "..") for part in pure.parts):
        raise ValueError(f"{field} contains an unsafe path: {value!r}")
    return pure.as_posix()


def validate_bundle(bundle: dict[str, Any], task: dict[str, Any]) -> tuple[str, dict[str, str], str | None, str]:
    config_path = validate_relative_path(
        bundle.get("config_path") or "main.yml",
        field="config_path",
    )
    raw_files = bundle.get("files")
    if not isinstance(raw_files, dict) or not raw_files:
        raise ValueError("files must be a non-empty object")
    files: dict[str, str] = {}
    for raw_path, content in raw_files.items():
        path = validate_relative_path(raw_path, field="file path")
        if path == "output" or path.startswith("output/") or path == ".dnsb_cache" or path.startswith(".dnsb_cache/") or path.startswith(".git/"):
            raise ValueError(f"generated/cache path is not allowed: {path}")
        if not isinstance(content, str):
            raise ValueError(f"file content must be text: {path}")
        if len(content.encode("utf-8")) > MAX_FILE_BYTES:
            raise ValueError(f"file is too large: {path}")
        files[path] = content
    if config_path not in files:
        raise ValueError(f"config_path is missing from files: {config_path}")
    verify_path = bundle.get("verify_path")
    if verify_path is not None:
        verify_path = validate_relative_path(verify_path, field="verify_path")
        if verify_path not in files:
            raise ValueError(f"verify_path is missing from files: {verify_path}")
    notes = bundle.get("notes", "")
    if not isinstance(notes, str):
        notes = str(notes)
    return config_path, files, verify_path, notes


def validate_blank_bundle(
    bundle: dict[str, Any],
) -> tuple[str | None, dict[str, str], str, str]:
    """Validate a self-contained baseline bundle without a DNS-BUILDER contract."""

    raw_files = bundle.get("files")
    if not isinstance(raw_files, dict) or not raw_files:
        raise ValueError("files must be a non-empty object")
    files: dict[str, str] = {}
    for raw_path, content in raw_files.items():
        path = validate_relative_path(raw_path, field="file path")
        if path == ".git" or path.startswith(".git/"):
            raise ValueError(f"repository metadata path is not allowed: {path}")
        if path == "output" or path.startswith("output/") or path == ".dnsb_cache" or path.startswith(".dnsb_cache/"):
            raise ValueError(f"generated/cache path is not allowed: {path}")
        if not isinstance(content, str):
            raise ValueError(f"file content must be text: {path}")
        if len(content.encode("utf-8")) > MAX_FILE_BYTES:
            raise ValueError(f"file is too large: {path}")
        files[path] = content
    entrypoint = bundle.get("entrypoint")
    if entrypoint is not None:
        entrypoint = validate_relative_path(entrypoint, field="entrypoint")
        if entrypoint not in files:
            raise ValueError(f"entrypoint is missing from files: {entrypoint}")
    # The blank condition is a fair comparison only when the model supplies a
    # runnable end-to-end verifier.  A project that merely contains Compose
    # files is not an evaluated DNS environment, so ``verify_path`` is
    # intentionally mandatory here (including bundle adapters).
    verify_path_value = bundle.get("verify_path")
    if verify_path_value is None:
        raise ValueError("blank bundle must provide verify_path (verify.sh or verify.py)")
    verify_path = validate_relative_path(verify_path_value, field="verify_path")
    if PurePosixPath(verify_path).suffix.lower() not in {".sh", ".bash", ".py"}:
        raise ValueError("blank verify_path must name a .sh, .bash, or .py script")
    if verify_path not in files:
        raise ValueError(f"verify_path is missing from files: {verify_path}")
    notes = bundle.get("notes", "")
    if not isinstance(notes, str):
        notes = str(notes)
    return entrypoint, files, verify_path, notes


def discover_verification_script(project_dir: Path) -> str | None:
    """Return the portable model-verification entrypoint in a workspace.

    Native agents do not return a JSON bundle, so the workspace contract uses
    one of a few explicit, relative names.  We do not recursively guess an
    arbitrary executable: an unambiguous entrypoint is needed for a repeatable
    audit rerun.
    """

    root = project_dir.resolve()
    for relative in VERIFICATION_SCRIPT_NAMES:
        path = root / relative
        if path.is_file() and not path.is_symlink():
            return relative
    return None


def discover_verification_report(project_dir: Path) -> Path | None:
    """Find the JSON report produced by the model's verification script."""

    root = project_dir.resolve()
    for relative in VERIFICATION_REPORT_NAMES:
        path = root / relative
        if path.is_file() and not path.is_symlink():
            return path
    return None


def inspect_verification_report(project_dir: Path) -> tuple[Path | None, bool, str]:
    """Validate the model-owned verification report without trusting prose.

    The report must be JSON, declare a passing status (or ``passed: true``),
    and contain no explicitly failing checks.  The raw report remains in the
    project artifact; this function only returns a compact reason for the
    event log.
    """

    report = discover_verification_report(project_dir)
    if report is None:
        return None, False, "verification-report.json is missing"
    try:
        value = json.loads(report.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return report, False, f"verification report is not valid JSON: {exc}"
    if not isinstance(value, dict):
        return report, False, "verification report must be a JSON object"
    status = str(value.get("status", "")).strip().lower()
    passed = value.get("passed") is True or status in {"pass", "passed", "success", "ok"}
    checks = value.get("checks")
    if not isinstance(checks, list) or not checks:
        return report, False, "verification report must contain a non-empty checks array"
    failed_checks: list[Any] = []
    incomplete_checks: list[Any] = []
    if isinstance(checks, list):
        for check in checks:
            if not isinstance(check, dict):
                incomplete_checks.append(check)
                continue
            # Accept the common boolean form used by lightweight verifiers
            # (``{"passed": true}``) alongside the normalized status form.
            # The report still must contain an explicit result for every
            # check; a missing boolean and missing status remains incomplete.
            if check.get("passed") is True:
                check_status = "pass"
            elif check.get("passed") is False:
                check_status = "fail"
            else:
                check_status = str(check.get("status", "")).lower()
            if check_status in {"fail", "failed", "error"}:
                failed_checks.append(check.get("name") or check)
            elif check_status not in {"pass", "passed", "success", "ok"}:
                incomplete_checks.append(check.get("name") or check)
    if failed_checks:
        return report, False, f"verification report contains failed checks: {failed_checks}"
    if incomplete_checks:
        return report, False, f"verification report contains incomplete checks: {incomplete_checks}"
    commands = value.get("commands")
    has_command_evidence = isinstance(commands, list) and bool(commands)
    if not has_command_evidence:
        has_command_evidence = any(
            isinstance(check, dict) and (check.get("command") or check.get("argv"))
            for check in checks
        )
    if not has_command_evidence:
        return report, False, "verification report must preserve executed commands or argv"
    if not passed:
        return report, False, "verification report does not declare status=pass or passed=true"
    return report, True, "verification report declares a passing result"


def _call_text(call: Mapping[str, Any]) -> str:
    """Serialize a normalized tool call for conservative marker checks."""

    try:
        return json.dumps(
            {
                "tool_name": call.get("tool_name"),
                "arguments": call.get("arguments"),
                "output": call.get("output"),
            },
            ensure_ascii=False,
            sort_keys=True,
        ).lower()
    except (TypeError, ValueError):
        return str(call).lower()


def _call_succeeded(call: Mapping[str, Any]) -> bool:
    exit_code = call.get("exit_code")
    if isinstance(exit_code, (int, float)) and not isinstance(exit_code, bool):
        return int(exit_code) == 0
    status = str(call.get("status") or "").lower()
    return status in {"completed", "complete", "success", "succeeded", "ok"}


def audit_agent_react(
    trace: AgentTrace | None,
    verify_path: str | None,
    *,
    require: bool = True,
) -> tuple[bool, list[dict[str, Any]]]:
    """Check that a native agent actually used tools to run its verifier.

    A report written by the model alone is insufficient: the normalized trace
    must contain at least one tool call mentioning the declared verifier, and
    that call must have completed successfully.  This is intentionally a
    structural ReAct audit; semantic DNS claims are checked from the report
    and by the independent rerun below.
    """

    if not require:
        return True, [{"name": "react-tool-use", "status": "not_required"}]
    if trace is None:
        return False, [
            {
                "name": "react-tool-use",
                "status": "fail",
                "detail": "native agent trace is unavailable",
            }
        ]
    calls = list(trace.tool_calls)
    checks: list[dict[str, Any]] = [
        {
            "name": "react-tool-use",
            "status": "pass" if calls else "fail",
            "tool_calls": len(calls),
        }
    ]
    marker = Path(verify_path).name.lower() if verify_path else ""
    matching = []
    for call in calls:
        text = _call_text(call)
        executable_marker = marker and any(
            token in text
            for token in (
                f"bash {marker}",
                f"sh {marker}",
                f"python {marker}",
                f"python3 {marker}",
                f"./{marker}",
                f"/{marker}",
            )
        )
        if executable_marker:
            matching.append(call)
    successful = [call for call in matching if _call_succeeded(call)]
    checks.append(
        {
            "name": "react-verification-command",
            "status": "pass" if successful else "fail",
            "declared_verify_path": verify_path,
            "matching_tool_calls": len(matching),
            "successful_tool_calls": len(successful),
        }
    )
    return all(check["status"] == "pass" for check in checks), checks


def run_model_verification(
    *,
    project_dir: Path,
    verify_path: str,
    compose_path: Path | None,
    args: argparse.Namespace,
    events: EventLog,
    log_dir: Path,
) -> tuple[str, list[dict[str, Any]], Path | None]:
    """Rerun the model's verifier and record its independent acceptance.

    The verifier is run from the project root in a clean subprocess.  The
    runner supplies the generated Compose path when DNS-BUILDER produced one;
    projects may use ``DNSB_COMPOSE_FILE``/``COMPOSE_FILE`` or ignore it when
    they own their own orchestration.
    """

    relative = validate_relative_path(verify_path, field="verify_path")
    script = (project_dir / relative).resolve()
    if project_dir.resolve() not in script.parents or not script.is_file() or script.is_symlink():
        checks = [{"name": "verify_path", "status": "fail", "detail": f"missing verifier: {relative}"}]
        events.write("acceptance", stage="model-verification", status="fail", checks=checks, verification_seconds=0.0)
        return "fail", checks, None
    suffix = script.suffix.lower()
    if suffix == ".py":
        argv = [sys.executable, str(script)]
    elif suffix in {".sh", ".bash"}:
        argv = ["bash", str(script)]
    elif os.access(script, os.X_OK):
        argv = [str(script)]
    else:
        # Keep the contract useful for a text script without silently
        # executing it through a shell chosen by the host.
        argv = ["bash", str(script)]
    env: dict[str, str] = {
        "DNSB_PROJECT_DIR": str(project_dir),
    }
    if compose_path is not None:
        env["DNSB_COMPOSE_FILE"] = str(compose_path)
        env["COMPOSE_FILE"] = str(compose_path)
    result = run_command(
        argv,
        label="model-verification",
        cwd=project_dir,
        log_dir=log_dir,
        events=events,
        timeout=args.tool_timeout,
        env=env,
    )
    report_path, report_ok, report_detail = inspect_verification_report(project_dir)
    checks = [
        {
            "name": "verification-command",
            "status": "pass" if result.ok else "fail",
            "exit_code": result.exit_code,
            "timed_out": result.timed_out,
        },
        {
            "name": "verification-report",
            "status": "pass" if report_ok else "fail",
            "path": str(report_path) if report_path else None,
            "detail": report_detail,
        },
    ]
    status = "pass" if all(check["status"] == "pass" for check in checks) else "fail"
    events.write(
        "acceptance",
        stage="model-verification",
        status=status,
        checks=checks,
        verification_seconds=round(result.duration_s, 6),
        report_path=str(report_path) if report_path else None,
    )
    if report_path is not None:
        events.write(
            "artifact",
            kind="verification-report",
            path=str(report_path),
            status="pass" if report_ok else "fail",
            sha256=sha256_file(report_path),
        )
    return status, checks, report_path


def model_verification_required(args: argparse.Namespace, condition: str) -> bool:
    """Whether this episode must pass the model-verification gate.

    ``fixture`` remains an offline evaluator fixture and has no model/ReAct
    semantics.  Every real blank episode is gated.  Native workspace agents in
    either condition are gated so the paired experiment gives both conditions
    the same opportunity to validate their own environment.
    """

    if args.provider == "fixture":
        return False
    if condition == "blank":
        return True
    return args.provider == "agent" and args.agent_mode == "workspace"


def write_project(project_dir: Path, files: Mapping[str, str]) -> None:
    if project_dir.exists():
        shutil.rmtree(project_dir)
    project_dir.mkdir(parents=True, exist_ok=True)
    for relative, content in files.items():
        path = project_dir / relative
        resolved = path.resolve()
        if project_dir.resolve() not in resolved.parents:
            raise ValueError(f"path escaped project root: {relative}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def validate_agent_workspace(
    project_dir: Path,
    config_path: str | None,
    *,
    require_config: bool = True,
    require_verification: bool = False,
    reject_temporary_images: bool = False,
) -> tuple[bool, list[dict[str, Any]]]:
    """Validate a workspace written by a coding agent before building it."""

    checks: list[dict[str, Any]] = []
    root = project_dir.resolve()
    if require_config:
        if not config_path:
            checks.append({"name": "config-present", "status": "fail", "path": None})
        else:
            config = root / config_path
            checks.append(
                {
                    "name": "config-present",
                    "status": "pass" if config.is_file() and not config.is_symlink() else "fail",
                    "path": config_path,
                }
            )
    else:
        files = [path for path in root.rglob("*") if path.is_file()] if root.is_dir() else []
        checks.append({"name": "workspace-nonempty", "status": "pass" if files else "fail", "file_count": len(files)})
    forbidden: list[str] = []
    unsafe: list[str] = []
    oversized: list[str] = []
    cross_episode_images: list[dict[str, Any]] = []
    # A blank project must be self-contained.  In particular, it must not
    # refer to a temporary image produced by another episode (or to a
    # DNS-BUILDER image that the blank condition was never given).  Such a
    # reference can appear in Compose, a Dockerfile, or a shell verifier, so
    # inspect only image-bearing lines across text files and retain the exact
    # path/line for the repair prompt.
    temporary_image_pattern = re.compile(
        r"(?:dnsb-blank-agent-[A-Za-z0-9_.-]+|"
        r"dnsb-image-builder-[A-Za-z0-9_.-]+|"
        r"project-[A-Za-z0-9_.-]+|"
        r"[A-Za-z0-9_.-]+(?:reproduction|workspace|agent)[A-Za-z0-9_.-]*)",
        flags=re.IGNORECASE,
    )
    image_line_pattern = re.compile(
        r"(?:^\s*(?:from|image\s*:)|docker\s+(?:run|build)|--from(?:=|\s))",
        flags=re.IGNORECASE,
    )
    if root.is_dir():
        for path in root.rglob("*"):
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                unsafe.append(relative)
                continue
            if relative == "output" or relative.startswith("output/"):
                forbidden.append(relative)
            if relative == ".dnsb_cache" or relative.startswith(".dnsb_cache/"):
                forbidden.append(relative)
            if relative == ".git" or relative.startswith(".git/"):
                forbidden.append(relative)
            if path.is_file() and path.stat().st_size > MAX_FILE_BYTES:
                oversized.append(relative)
            if reject_temporary_images and path.is_file() and path.stat().st_size <= MAX_FILE_BYTES:
                try:
                    text = path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    text = ""
                for line_number, line in enumerate(text.splitlines(), start=1):
                    if not image_line_pattern.search(line):
                        continue
                    match = temporary_image_pattern.search(line)
                    if match:
                        cross_episode_images.append(
                            {
                                "path": relative,
                                "line": line_number,
                                "detail": line.strip()[:500],
                                "reference": match.group(0),
                            }
                        )
    else:
        unsafe.append("<workspace missing>")
    if require_verification:
        verify_path = discover_verification_script(root)
        report_path = discover_verification_report(root)
        checks.extend(
            [
                {
                    "name": "verification-script",
                    "status": "pass" if verify_path else "fail",
                    "path": verify_path,
                },
                {
                    "name": "verification-report",
                    "status": "pass" if report_path else "fail",
                    "path": str(report_path.relative_to(root)) if report_path else None,
                },
            ]
        )
    checks.extend(
        [
            {"name": "forbidden-generated-paths", "status": "pass" if not forbidden else "fail", "paths": forbidden},
            {"name": "unsafe-links", "status": "pass" if not unsafe else "fail", "paths": unsafe},
            {"name": "file-size-limit", "status": "pass" if not oversized else "fail", "paths": oversized},
            {
                "name": "self-contained-image-references",
                "status": "pass" if not cross_episode_images else "fail",
                "references": cross_episode_images,
            },
        ]
    )
    return all(check["status"] == "pass" for check in checks), checks


def archive_agent_workspace(project_dir: Path, destination: Path) -> str | None:
    """Copy a failed direct-agent attempt into the immutable episode artifacts."""

    if not project_dir.exists():
        return None
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(project_dir, destination, symlinks=True)
    return sha256_tree(destination)


def write_episode_manifest(output: Path) -> Path:
    """Index every retained episode file, including logs and raw agent traces."""

    target = output / "artifacts" / "episode-manifest.json"
    records: list[dict[str, Any]] = []
    for path in sorted(output.rglob("*")):
        if path.resolve() == target.resolve():
            continue
        relative = path.relative_to(output).as_posix()
        if path.is_symlink():
            link = os.readlink(path)
            records.append(
                {
                    "path": relative,
                    "type": "symlink",
                    "target": link,
                    "bytes": len(link.encode("utf-8")),
                    "sha256": sha256_bytes(link.encode("utf-8")),
                }
            )
            continue
        if not path.is_file():
            continue
        records.append(
            {
                "path": relative,
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    payload = {
        "schema_version": 1,
        "root": ".",
        "file_count": len(records),
        "files": records,
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def write_evidence_file(
    project_dir: Path,
    *,
    task: dict[str, Any],
    pdf_path: Path,
    pdf_sha256: str,
    page_count: int,
    notes: str,
    include_references: bool = True,
) -> bool:
    """Add evaluator-owned provenance without inventing paper facts.

    A model may supply its own evidence.md.  When it does not, the runner
    writes a small metadata-only file so every accepted project records which
    paper and task produced it; claims about topology remain the model's notes
    or the task's fixed assertions.
    """

    path = project_dir / "evidence.md"
    if path.exists():
        return False
    references = (
        task_material_paths(task)
        if include_references
        else []
    )
    supplied_material = (
        ["- Public material supplied to the model:", *[f"  - `{item}`" for item in references]]
        if include_references
        else [
            "- Public material supplied to the model:",
            "  - None (blank-information baseline; only the paper PDF and generic task requirement were supplied).",
        ]
    )
    content = "\n".join(
        [
            "# Evaluation provenance",
            "",
            "This file was added by `dnsb_agent_runner.py`; it records inputs and does not replace paper-grounded evidence.",
            "",
            f"- Task: `{task.get('task_id')}`",
            f"- Paper: `{pdf_path.name}`",
            f"- Paper SHA-256: `{pdf_sha256}`",
            f"- Extracted pages: `{page_count}`",
            *supplied_material,
            "",
            "## Model notes",
            "",
            notes.strip() or "No model notes were returned.",
            "",
            "The deterministic acceptance checks and raw event log are stored in the episode directory.",
            "",
        ]
    )
    path.write_text(content, encoding="utf-8")
    return True


def write_human_review_template(output: Path, task: dict[str, Any]) -> Path:
    """Create a final feasibility review record after model verification."""

    path = output / "artifacts" / "human-review.json"
    review = {
        "schema_version": 1,
        "status": "pending",
        "feasible": None,
        "reviewer": None,
        "reviewed_at": None,
        "human_seconds": None,
        "notes": "",
        "criteria": list((task.get("human_review") or {}).get("criteria") or []),
        "preconditions": [
            "acceptance.model-react.status == pass",
            "acceptance.model-verification.status == pass",
        ],
        "instructions": "Model ReAct verification must already pass. Use review_episode.py after inspecting the project, verification report, logs, and paper evidence; human review is the final feasibility decision, not a substitute for model verification.",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


@dataclass
class ProviderResult:
    text: str
    usage: dict[str, int | None]
    usage_source: str
    request_id: str | None
    raw: Any
    error: str | None
    duration_s: float
    agent_trace: AgentTrace | None = None
    raw_event_path: Path | None = None
    raw_stderr_path: Path | None = None
    trajectory_path: Path | None = None


def empty_usage() -> dict[str, int | None]:
    return {
        "input_tokens": None,
        "output_tokens": None,
        "reasoning_tokens": None,
        "cached_input_tokens": None,
        "total_tokens": None,
    }


def normalize_openai_usage(raw: Any) -> dict[str, int | None]:
    usage = raw if isinstance(raw, dict) else {}
    result = empty_usage()
    for key in ("input_tokens", "output_tokens", "total_tokens"):
        value = usage.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            result[key] = int(value)
    input_details = usage.get("input_tokens_details") or usage.get("prompt_tokens_details") or {}
    output_details = usage.get("output_tokens_details") or usage.get("completion_tokens_details") or {}
    if isinstance(input_details, dict):
        value = input_details.get("cached_tokens")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            result["cached_input_tokens"] = int(value)
    if isinstance(output_details, dict):
        value = output_details.get("reasoning_tokens")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            result["reasoning_tokens"] = int(value)
    # Chat Completions compatibility is useful for local proxies.
    if result["input_tokens"] is None and isinstance(usage.get("prompt_tokens"), (int, float)):
        result["input_tokens"] = int(usage["prompt_tokens"])
    if result["output_tokens"] is None and isinstance(usage.get("completion_tokens"), (int, float)):
        result["output_tokens"] = int(usage["completion_tokens"])
    if result["total_tokens"] is None and isinstance(usage.get("total_tokens"), (int, float)):
        result["total_tokens"] = int(usage["total_tokens"])
    return result


def output_text_from_response(payload: Any) -> str:
    if isinstance(payload, dict) and isinstance(payload.get("output_text"), str):
        return payload["output_text"]
    pieces: list[str] = []
    output = payload.get("output") if isinstance(payload, dict) else None
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and isinstance(part.get("text"), str):
                        pieces.append(part["text"])
    if pieces:
        return "".join(pieces)
    choices = payload.get("choices") if isinstance(payload, dict) else None
    if isinstance(choices, list) and choices:
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            return message["content"]
    return ""


class ModelProvider:
    def __init__(self, args: argparse.Namespace, repo_root: Path, task: dict[str, Any]):
        self.args = args
        self.repo_root = repo_root
        self.task = task

    def call(
        self,
        prompt: str,
        attempt: int,
        model_dir: Path,
        workspace_dir: Path | None = None,
    ) -> ProviderResult:
        if self.args.provider == "fixture":
            return self._fixture(attempt)
        if self.args.provider == "command":
            return self._command(prompt, attempt, model_dir)
        if self.args.provider == "agent":
            return self._agent(prompt, attempt, model_dir, workspace_dir)
        return self._openai(prompt, attempt, model_dir)

    def _fixture(self, attempt: int) -> ProviderResult:
        start = time.perf_counter()
        source = self.task.get("source_project")
        if not isinstance(source, str):
            return ProviderResult("", empty_usage(), "fixture", None, None, "task has no source_project", time.perf_counter() - start)
        source_dir = resolve_repo_path(self.repo_root, source)
        if not source_dir.is_dir():
            return ProviderResult("", empty_usage(), "fixture", None, None, f"fixture source not found: {source_dir}", time.perf_counter() - start)
        files: dict[str, str] = {}
        for path in sorted(source_dir.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(source_dir).as_posix()
            if relative.startswith("output/") or relative.startswith(".dnsb_cache/") or relative.startswith(".git/"):
                continue
            try:
                files[relative] = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                return ProviderResult("", empty_usage(), "fixture", None, None, f"fixture file is not UTF-8 text: {relative}", time.perf_counter() - start)
        text = json.dumps(
            {
                "config_path": self.task.get("fixture_config_path", "main.yml"),
                "files": files,
                "verify_path": None,
                "notes": "offline golden fixture; no model tokens are available",
            },
            ensure_ascii=False,
        )
        return ProviderResult(text, empty_usage(), "fixture", f"fixture-{attempt}", None, None, time.perf_counter() - start)

    def _command(self, prompt: str, attempt: int, model_dir: Path) -> ProviderResult:
        start = time.perf_counter()
        if not self.args.command:
            return ProviderResult("", empty_usage(), "unavailable", None, None, "--command is required for provider=command", 0.0)
        argv = shlex.split(self.args.command)
        if not argv:
            return ProviderResult("", empty_usage(), "unavailable", None, None, "--command is empty", 0.0)
        stdout_path = model_dir / f"attempt-{attempt:03d}.command.stdout.log"
        stderr_path = model_dir / f"attempt-{attempt:03d}.command.stderr.log"
        command_env = os.environ.copy()
        if self.args.command_usage_file:
            usage_path = Path(self.args.command_usage_file.replace("{attempt}", str(attempt)))
            if not usage_path.is_absolute():
                usage_path = self.repo_root / usage_path
            command_env["DNSB_USAGE_FILE"] = str(usage_path)
        try:
            proc = subprocess.run(
                argv,
                input=prompt,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=self.repo_root,
                env=command_env,
                timeout=self.args.model_timeout,
                check=False,
            )
            stdout_path.write_text(proc.stdout, encoding="utf-8")
            stderr_path.write_text(proc.stderr, encoding="utf-8")
            error = None if proc.returncode == 0 else tail_text(stderr_path) or f"exit code {proc.returncode}"
            usage = empty_usage()
            usage_source = "unavailable"
            usage_candidates: list[Path] = []
            if self.args.command_usage_file:
                usage_path = Path(self.args.command_usage_file.replace("{attempt}", str(attempt)))
                usage_candidates.append(usage_path if usage_path.is_absolute() else self.repo_root / usage_path)
            for line in proc.stderr.splitlines():
                if line.startswith("DNSB_USAGE_JSON:"):
                    try:
                        usage_payload = json.loads(line.split(":", 1)[1].strip())
                        usage = normalize_openai_usage(usage_payload)
                        usage_source = "provider"
                    except (json.JSONDecodeError, TypeError):
                        pass
            for usage_path in usage_candidates:
                if usage_path.is_file():
                    try:
                        usage = normalize_openai_usage(json.loads(usage_path.read_text(encoding="utf-8")))
                        usage_source = "provider"
                    except (OSError, json.JSONDecodeError, TypeError):
                        pass
            return ProviderResult(
                proc.stdout,
                usage,
                usage_source,
                None,
                None,
                error,
                time.perf_counter() - start,
                raw_event_path=stdout_path,
                raw_stderr_path=stderr_path,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout if isinstance(exc.stdout, str) else ""
            stderr = exc.stderr if isinstance(exc.stderr, str) else ""
            stdout_path.write_text(stdout, encoding="utf-8")
            stderr_path.write_text(stderr, encoding="utf-8")
            return ProviderResult(
                "",
                empty_usage(),
                "unavailable",
                None,
                None,
                f"model command timed out after {self.args.model_timeout:g}s",
                time.perf_counter() - start,
                raw_event_path=stdout_path,
                raw_stderr_path=stderr_path,
            )
        except OSError as exc:
            return ProviderResult("", empty_usage(), "unavailable", None, None, str(exc), time.perf_counter() - start)

    def _agent_argv(self, workspace_dir: Path) -> list[str]:
        """Build an unattended Codex/Claude Code invocation.

        ``--agent-command`` is intentionally an argv template rather than a
        shell command.  ``{workspace}``, ``{model}``, and ``{agent}`` are
        replaced before ``shlex.split`` so a lab can point the runner at a
        wrapper while retaining the same stdin/JSONL contract.
        """

        agent = str(self.args.agent)
        if self.args.agent_command:
            command = self.args.agent_command
            replacements = {
                "{workspace}": str(workspace_dir),
                "{model}": str(self.args.model or ""),
                "{agent}": agent,
            }
            for source, value in replacements.items():
                command = command.replace(source, value)
            argv = shlex.split(command)
            if not argv:
                raise ValueError("--agent-command is empty")
            return argv
        if agent == "codex":
            executable = shutil.which("codex") or "codex"
            argv = [
                executable,
                "exec",
                "--json",
                "--skip-git-repo-check",
                "-C",
                str(workspace_dir),
                "-s",
                self.args.agent_sandbox,
                # The standalone runner has no ChatGPT code-mode host. Keep
                # Codex's normal function-call items so every tool operation
                # remains observable in stdout JSONL (the Harbor adapter uses
                # the same switches).
                "--disable",
                "code_mode",
                "--disable",
                "code_mode_only",
            ]
            if self.args.model:
                argv.extend(["--model", self.args.model])
            # A bare '-' makes Codex consume the prompt from stdin and keeps
            # the full prompt out of process listings and shell history.
            argv.append("-")
            return argv
        if agent == "claude":
            executable = shutil.which("claude") or "claude"
            argv = [
                executable,
                "-p",
                "--verbose",
                "--output-format",
                "stream-json",
                "--permission-mode",
                self.args.agent_permission_mode,
                "--no-session-persistence",
                # Keep the episode on the declared workspace and make every
                # filesystem/command action visible in the stream.  In
                # particular, do not let a user-level MCP/Computer-Use server
                # become an untracked path around the ReAct gate.
                "--tools",
                "Bash,Read,Write,Edit",
                "--strict-mcp-config",
                "--mcp-config",
                '{"mcpServers":{}}',
            ]
            if self.args.model:
                argv.extend(["--model", self.args.model])
            return argv
        raise ValueError(f"unsupported --agent: {agent}")

    def _agent(
        self,
        prompt: str,
        attempt: int,
        model_dir: Path,
        workspace_dir: Path | None,
    ) -> ProviderResult:
        """Run a native coding-agent CLI against an isolated workspace.

        The stdout stream is saved byte-for-byte.  Parsed JSON events are
        projected into an ATIF-shaped trajectory and are also returned to the
        runner so it can append provider-neutral ``agent_event`` and
        ``tool_call`` records to the episode ledger.
        """

        start = time.perf_counter()
        if workspace_dir is None:
            return ProviderResult(
                "",
                empty_usage(),
                "unavailable",
                None,
                None,
                "agent provider requires a workspace",
                0.0,
            )
        model_dir.mkdir(parents=True, exist_ok=True)
        raw_path = model_dir / f"attempt-{attempt:03d}.{self.args.agent}.txt"
        events_path = model_dir / f"attempt-{attempt:03d}.agent-events.jsonl"
        stderr_path = model_dir / f"attempt-{attempt:03d}.{self.args.agent}.stderr.log"
        trajectory_path = model_dir / f"attempt-{attempt:03d}.trajectory.json"
        try:
            argv = self._agent_argv(workspace_dir)
        except (OSError, ValueError) as exc:
            return ProviderResult(
                "",
                empty_usage(),
                "unavailable",
                None,
                None,
                str(exc),
                time.perf_counter() - start,
            )
        child_env = os.environ.copy()
        child_env.update(
            {
                "DNSB_AGENT": str(self.args.agent),
                "DNSB_AGENT_WORKSPACE": str(workspace_dir),
                "DNSB_AGENT_ATTEMPT": str(attempt),
            }
        )
        # Never inherit a prior episode's explicit DNS-BUILDER injection.
        # PATH and arbitrary shell access still require external isolation.
        child_env.pop("DNSB_AGENT_DNSB_BIN", None)
        dnsb_bin = getattr(self.args, "dnsb_agent_bin", None) if self.args.condition == "dns-builder" else None
        if dnsb_bin:
            child_env["DNSB_AGENT_DNSB_BIN"] = str(dnsb_bin)
            child_env["PATH"] = str(Path(dnsb_bin).resolve().parent) + os.pathsep + child_env.get("PATH", "")
        stdout_data = b""
        stderr_data = b""
        exit_code = 126
        error: str | None = None
        process_started = time.perf_counter()
        try:
            process = subprocess.Popen(
                argv,
                cwd=str(workspace_dir),
                env=child_env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
            try:
                stdout_data, stderr_data = process.communicate(
                    prompt.encode("utf-8"), timeout=self.args.model_timeout
                )
                exit_code = process.returncode
            except subprocess.TimeoutExpired as exc:
                stdout_data = exc.stdout or b""
                stderr_data = exc.stderr or b""
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except OSError:
                    process.kill()
                more_out, more_err = process.communicate()
                stdout_data += more_out or b""
                stderr_data += more_err or b""
                exit_code = 124
                error = f"agent timed out after {self.args.model_timeout:g}s"
            if exit_code != 0 and error is None:
                error = (
                    stderr_data.decode("utf-8", errors="replace")[-8_000:].strip()
                    or f"agent exit code {exit_code}"
                )
        except FileNotFoundError as exc:
            error = str(exc)
            exit_code = 127
        except OSError as exc:
            error = str(exc)
            exit_code = 126
        process_duration = time.perf_counter() - process_started
        raw_path.write_bytes(stdout_data)
        stderr_path.write_bytes(stderr_data)
        raw_text = stdout_data.decode("utf-8", errors="replace")
        # Keep a JSON-only convenience stream for line-oriented tooling.  The
        # raw Harbor-compatible ``*.txt`` file remains authoritative and may
        # contain CLI warnings before the JSONL events.
        valid_lines: list[str] = []
        for line in raw_text.splitlines(keepends=True):
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                valid_lines.append(line if line.endswith("\n") else line + "\n")
        events_path.write_text("".join(valid_lines), encoding="utf-8")
        trace = parse_stream(str(self.args.agent), raw_text, model_hint=self.args.model)
        trajectory_path.write_text(
            json.dumps(
                trace.trajectory(raw_path=str(raw_path)),
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        request_id = trace.session_id
        if error is None and trace.extra.get("error"):
            error = str(trace.extra["error"])
        return ProviderResult(
            trace.text,
            trace.usage,
            trace.usage_source,
            request_id,
            {
                "agent": self.args.agent,
                "argv": argv,
                "exit_code": exit_code,
                "json_events": trace.json_events,
                "malformed_lines": trace.malformed_lines,
            },
            error,
            process_duration,
            agent_trace=trace,
            raw_event_path=raw_path,
            raw_stderr_path=stderr_path,
            trajectory_path=trajectory_path,
        )

    def _openai(self, prompt: str, attempt: int, model_dir: Path) -> ProviderResult:
        start = time.perf_counter()
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            return ProviderResult("", empty_usage(), "unavailable", None, None, "OPENAI_API_KEY is not set", time.perf_counter() - start)
        model = self.args.model or DEFAULT_MODEL
        body: dict[str, Any] = {"model": model, "input": prompt}
        if self.args.max_output_tokens:
            body["max_output_tokens"] = self.args.max_output_tokens
        request = urllib.request.Request(
            self.args.openai_url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        raw_bytes = b""
        header_request_id: str | None = None
        response_path = model_dir / f"attempt-{attempt:03d}.response.json"
        try:
            with urllib.request.urlopen(request, timeout=self.args.model_timeout) as response:
                header_request_id = response.headers.get("x-request-id")
                raw_bytes = response.read()
            payload = json.loads(raw_bytes.decode("utf-8"))
            response_path.write_bytes(raw_bytes)
            usage = normalize_openai_usage(payload.get("usage") if isinstance(payload, dict) else None)
            request_id = payload.get("id") if isinstance(payload, dict) else None
            request_id = request_id or header_request_id
            return ProviderResult(
                output_text_from_response(payload),
                usage,
                "provider",
                str(request_id) if request_id else None,
                payload,
                None,
                time.perf_counter() - start,
                raw_event_path=response_path,
            )
        except urllib.error.HTTPError as exc:
            raw_bytes = exc.read() if hasattr(exc, "read") else b""
            detail = raw_bytes.decode("utf-8", errors="replace")[-4_000:]
            response_path.write_bytes(raw_bytes)
            return ProviderResult(
                "", empty_usage(), "unavailable", None, None,
                f"HTTP {exc.code}: {detail}", time.perf_counter() - start,
                raw_event_path=response_path,
            )
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            if raw_bytes:
                response_path.write_bytes(raw_bytes)
            return ProviderResult(
                "", empty_usage(), "unavailable", None, None, str(exc),
                time.perf_counter() - start,
                raw_event_path=response_path if raw_bytes else None,
            )


def usage_cost(usage: Mapping[str, int | None], args: argparse.Namespace) -> float | None:
    input_tokens = usage.get("input_tokens")
    output_tokens = usage.get("output_tokens")
    cached = usage.get("cached_input_tokens") or 0
    if not isinstance(input_tokens, int) or not isinstance(output_tokens, int):
        return None
    if args.input_price is None or args.output_price is None:
        return None
    billable_input = max(0, input_tokens - cached)
    cost = billable_input * args.input_price / 1_000_000
    if args.cached_input_price is not None:
        cost += cached * args.cached_input_price / 1_000_000
    else:
        cost += cached * args.input_price / 1_000_000
    cost += output_tokens * args.output_price / 1_000_000
    return cost


def find_compose(build_base: Path) -> Path | None:
    candidates = sorted(build_base.glob("output/*/docker-compose.yml"))
    return candidates[0] if len(candidates) == 1 else (candidates[0] if candidates else None)


def compose_json_from_yaml(path: Path) -> Any:
    yaml = import_yaml()
    if yaml is None:
        raise RuntimeError("PyYAML is unavailable; install it or run the runner in .venv")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def parse_compose(
    compose_path: Path,
    *,
    events: EventLog,
    log_dir: Path,
    timeout: float,
) -> tuple[Any | None, CommandResult | None]:
    data = None
    try:
        data = compose_json_from_yaml(compose_path)
    except Exception:
        docker = shutil.which("docker")
        if docker:
            result = run_command(
                [docker, "compose", "-f", str(compose_path), "config", "--format", "json"],
                label=f"compose-config-json-{safe_label(compose_path.parents[2].name if len(compose_path.parents) > 2 else compose_path.parent.name)}-{safe_label(compose_path.parent.name)}",
                cwd=compose_path.parent,
                log_dir=log_dir,
                events=events,
                timeout=timeout,
            )
            if result.ok:
                try:
                    data = json.loads(result.stdout_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    data = None
            return data, result
    return data, None


def structural_checks(compose: Any, task: dict[str, Any], artifact_root: Path | None = None) -> tuple[bool, list[dict[str, Any]]]:
    checks: list[dict[str, Any]] = []
    if not isinstance(compose, dict):
        return False, [{"name": "compose-object", "status": "fail", "detail": "Compose is not an object"}]
    services = compose.get("services")
    if not isinstance(services, dict):
        return False, [{"name": "services", "status": "fail", "detail": "services is missing"}]
    service_names = list(services)
    non_builder = [name for name in service_names if not str(name).startswith("dnsb-image-builder-")]
    expected = task.get("expected") or {}
    project_expected = expected.get("project_name")
    actual_name = compose.get("name")
    checks.append({"name": "project-name", "status": "pass" if not project_expected or actual_name == project_expected else "fail", "expected": project_expected, "actual": actual_name})
    minimum = expected.get("min_services", 1)
    checks.append({"name": "service-count", "status": "pass" if not isinstance(minimum, int) or len(non_builder) >= minimum else "fail", "expected_min": minimum, "actual": len(non_builder), "services": sorted(non_builder)})
    required = expected.get("required_services") or []
    missing = [name for name in required if name not in services]
    checks.append({"name": "required-services", "status": "pass" if not missing else "fail", "missing": missing})
    prefix_counts = expected.get("prefix_counts") or {}
    for prefix, count in prefix_counts.items():
        actual = sum(1 for name in service_names if str(name).startswith(str(prefix)))
        checks.append({"name": f"prefix:{prefix}", "status": "pass" if actual == count else "fail", "expected": count, "actual": actual})
    # Task definitions may add content assertions for generated per-service
    # configuration.  This catches a project that merely creates the right
    # number of containers but omits the DNS forwarding/stub mechanism.
    for index, assertion in enumerate(expected.get("config_assertions") or [], start=1):
        if not isinstance(assertion, dict) or artifact_root is None:
            checks.append({"name": f"config-assertion-{index}", "status": "fail", "detail": "invalid assertion or artifact root"})
            continue
        pattern = assertion.get("service_glob")
        relative = assertion.get("path")
        needles = assertion.get("contains") or []
        matched = [str(name) for name in service_names if isinstance(pattern, str) and fnmatch.fnmatch(str(name), pattern)]
        missing_files: list[str] = []
        missing_needles: list[str] = []
        if not isinstance(relative, str) or not isinstance(needles, list):
            checks.append({"name": f"config-assertion-{index}", "status": "fail", "detail": "invalid assertion fields"})
            continue
        for service in matched:
            path = artifact_root / service / relative
            if not path.is_file():
                missing_files.append(f"{service}/{relative}")
                continue
            content = path.read_text(encoding="utf-8", errors="replace")
            for needle in needles:
                if isinstance(needle, str) and needle not in content:
                    missing_needles.append(f"{service}: {needle}")
        assertion_ok = bool(matched) and not missing_files and not missing_needles
        checks.append({"name": f"config-assertion-{index}", "status": "pass" if assertion_ok else "fail", "service_glob": pattern, "matched": len(matched), "missing_files": missing_files, "missing_content": missing_needles})
    return all(check["status"] == "pass" for check in checks), checks


def normalize_text(text: str, root: Path) -> str:
    # Generated docker.hook files contain the absolute output path.
    for candidate in (str(root), str(root.resolve()), str(root.parent), str(root.parent.resolve())):
        text = text.replace(candidate, "<build-root>")
    # Only normalize declared build metadata. Cryptographic bytes, key tags,
    # algorithms, record counts, TTLs, and signature lifetimes remain evidence.
    text = re.sub(r"(?m)^(\s*)\d{8,}\s*(;\s*serial)", r"\1<SERIAL> \2", text, flags=re.I)
    text = re.sub(r"(\bSOA\b[^\n]*?\s)\d{8,}(?=\s)", r"\1<SERIAL>", text, flags=re.I)
    text = re.sub(r"(?m)^;\s*File written on .*\s*$", "; File written on <BUILD_TIME>", text)
    text = re.sub(r"(?m)^;\s*(Created|Publish|Activate): .*\s*$", r"; \1: <BUILD_TIME>", text)
    # PkgInstaller may emit this defensive pip prerequisite block depending on
    # the order in which shared image consumers are visited.  Both forms have
    # the same runtime meaning for the pinned Python base image, so omit the
    # generated block from the semantic (rather than exact) comparison.
    text = re.sub(
        r"\n?# Install prerequisites for [^\n]+\n"
        r"RUN if ! \(command -v [^\n]+\n"
        r"\s+apt-get update && apt-get install -y --no-install-recommends [^\n]+;\n"
        r"\s+fi\n",
        "\n",
        text,
    )
    return text


def semantic_snapshot(root: Path, compose: Any) -> tuple[dict[str, Any], str]:
    def canonical(value: Any) -> Any:
        if isinstance(value, dict):
            return {str(k): canonical(value[k]) for k in sorted(value, key=lambda item: str(item))}
        if isinstance(value, list):
            return [canonical(item) for item in value]
        if isinstance(value, str):
            return normalize_text(value, root)
        return value

    records: list[dict[str, Any]] = []
    for current, dirs, filenames in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in {".dnsb_cache", ".git", "__pycache__"})
        for filename in sorted(filenames):
            path = Path(current) / filename
            relative = path.relative_to(root).as_posix()
            if filename.endswith(".pyc"):
                continue
            raw = path.read_bytes()
            try:
                content = normalize_text(raw.decode("utf-8"), root).encode("utf-8")
                kind = "text"
            except UnicodeDecodeError:
                content = raw
                kind = "binary"
            records.append({"path": relative, "type": kind, "bytes": len(content), "sha256": sha256_bytes(content)})
    payload = {"compose": canonical(compose), "files": records}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return payload, sha256_bytes(encoded)


def run_manifest(root: Path, output: Path, *, label: str, args: argparse.Namespace, events: EventLog, log_dir: Path) -> CommandResult:
    script = Path(__file__).resolve().parents[2] / "skills" / "dns-builder" / "scripts" / "manifest.py"
    return run_command(
        [sys.executable, str(script), "--root", str(root), "--out", str(output)],
        label=label,
        cwd=Path(__file__).resolve().parents[2],
        log_dir=log_dir,
        events=events,
        timeout=args.tool_timeout,
    )


def build_once(
    *,
    project_dir: Path,
    config_path: str,
    build_dir: Path,
    attempt: int,
    args: argparse.Namespace,
    events: EventLog,
    log_dir: Path,
    dnsb_argv: list[str],
) -> tuple[bool, Path | None, Any | None, str]:
    if build_dir.exists():
        shutil.rmtree(build_dir)
    build_dir.mkdir(parents=True, exist_ok=True)
    config = project_dir / config_path
    build_label = "dnsb-rebuild" if build_dir.name == "build-2" else f"dnsb-build-attempt-{attempt}"
    result = run_command(
        [*dnsb_argv, "--no-update-check", "build", str(config), "--workdir", "@config", "--output-dir", str(build_dir)],
        label=build_label,
        cwd=project_dir,
        log_dir=log_dir,
        events=events,
        timeout=args.tool_timeout,
    )
    compose = find_compose(build_dir)
    if not result.ok or compose is None:
        detail = f"dnsb exit={result.exit_code}; compose={compose}\nSTDERR:\n{tail_text(result.stderr_path)}\nSTDOUT:\n{tail_text(result.stdout_path)}"
        return False, compose, None, detail
    docker = shutil.which("docker")
    compose_check: CommandResult | None = None
    if docker:
        compose_check = run_command(
            [docker, "compose", "-f", str(compose), "config", "--quiet"],
            label=("compose-config-rebuild" if build_dir.name == "build-2" else f"compose-config-attempt-{attempt}"),
            cwd=compose.parent,
            log_dir=log_dir,
            events=events,
            timeout=args.tool_timeout,
        )
        if not compose_check.ok:
            detail = f"Compose config failed\nSTDERR:\n{tail_text(compose_check.stderr_path)}"
            return False, compose, None, detail
    parsed, _parser_result = parse_compose(compose, events=events, log_dir=log_dir, timeout=args.tool_timeout)
    if parsed is None:
        return False, compose, None, "could not parse generated docker-compose.yml"
    # Legacy layout assertions only exercise evaluator fixtures. A model is
    # never required to guess hidden service names, paths, or payload literals.
    expected = (args.task.get("fixture_expected") or {}) if args.provider == "fixture" else {}
    passed, checks = structural_checks(parsed, {"expected": expected}, compose.parent)
    stage = "rebuild-structure" if build_dir.name == "build-2" else f"build-attempt-{attempt}"
    events.write("acceptance", stage=stage, status="pass" if passed else "fail", checks=checks, compose_path=str(compose))
    if not passed:
        # Full evaluator checks remain in events.jsonl, outside model inputs.
        return False, compose, parsed, "generated Compose failed structural validation; inspect the project and build logs"
    return True, compose, parsed, ""


def docker_available(args: argparse.Namespace, events: EventLog, log_dir: Path) -> bool:
    docker = shutil.which("docker")
    if not docker:
        return False
    result = run_command([docker, "info"], label="docker-info", cwd=Path.cwd(), log_dir=log_dir, events=events, timeout=min(args.tool_timeout, 30))
    return result.ok


def last_json_object(path: Path) -> dict[str, Any] | None:
    """Read the last compact JSON object emitted by a runtime probe."""

    if not path.is_file():
        return None
    for raw in reversed(path.read_text(encoding="utf-8", errors="replace").splitlines()):
        raw = raw.strip()
        if not raw:
            continue
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def run_runtime(
    compose: Path,
    task: dict[str, Any],
    args: argparse.Namespace,
    events: EventLog,
    log_dir: Path,
) -> tuple[str, list[dict[str, Any]]]:
    if args.runtime == "never":
        checks = [{"name": "runtime-disabled", "status": "not_run"}]
        events.write("acceptance", stage="runtime", status="not_run", checks=checks, reason="--runtime never")
        return "not_run", checks
    fixture_mode = args.provider == "fixture"
    runtime = task.get("fixture_runtime" if fixture_mode else "independent_runtime") or {}
    configured_checks = runtime.get("checks")
    if not isinstance(configured_checks, list) or not configured_checks:
        status = "fail" if args.runtime == "always" else "not_run"
        checks = [{
            "name": "independent-mechanism-verifier",
            "status": status,
            "detail": "No independent mechanism checks are configured; fixture-only scripts and model assertions are not acceptance.",
        }]
        events.write("acceptance", stage="runtime", status=status, checks=checks)
        return status, checks
    available = docker_available(args, events, log_dir)
    if not available:
        checks = [{"name": "docker-daemon", "status": "fail" if args.runtime == "always" else "not_run", "detail": "docker info failed"}]
        status = "fail" if args.runtime == "always" else "not_run"
        events.write("acceptance", stage="runtime", status=status, checks=checks, reason="Docker daemon unavailable")
        return status, checks
    docker = shutil.which("docker") or "docker"
    checks: list[dict[str, Any]] = []
    up = run_command([docker, "compose", "-f", str(compose), "up", "--build", "-d"], label="compose-up", cwd=compose.parent, log_dir=log_dir, events=events, timeout=args.tool_timeout)
    checks.append({"name": "compose-up", "status": "pass" if up.ok else "fail", "exit_code": up.exit_code})
    try:
        if up.ok:
            ps = run_command([docker, "compose", "-f", str(compose), "ps"], label="compose-ps", cwd=compose.parent, log_dir=log_dir, events=events, timeout=args.tool_timeout)
            checks.append({"name": "compose-ps", "status": "pass" if ps.ok else "fail", "exit_code": ps.exit_code})
            images = run_command([docker, "compose", "-f", str(compose), "images", "--format", "json"], label="compose-images", cwd=compose.parent, log_dir=log_dir, events=events, timeout=args.tool_timeout)
            checks.append({"name": "compose-images", "status": "pass" if images.ok else "info", "exit_code": images.exit_code})
            for index, configured in enumerate(configured_checks, start=1):
                if not isinstance(configured, dict):
                    checks.append({"name": f"runtime-command-{index}", "status": "fail", "detail": "runtime check is not an object"})
                    continue
                name = configured.get("name") or f"runtime-command-{index}"
                service = configured.get("service")
                command = configured.get("command")
                if not isinstance(service, str) or not isinstance(command, list) or not all(isinstance(item, str) for item in command):
                    checks.append({"name": str(name), "status": "fail", "detail": "runtime check is invalid"})
                    continue
                query_ok = False
                trial = 0
                query_metrics: dict[str, Any] | None = None
                for trial in range(1, 4):
                    if trial > 1:
                        time.sleep(2)
                    query = run_command([docker, "compose", "-f", str(compose), "exec", "-T", service, *command], label=f"runtime-{safe_label(str(name))}-{trial}", cwd=compose.parent, log_dir=log_dir, events=events, timeout=args.tool_timeout)
                    if query.ok:
                        query_ok = True
                        query_metrics = last_json_object(query.stdout_path)
                        break
                check = {"name": str(name), "status": "pass" if query_ok else "fail", "service": service, "attempts": trial}
                if query_metrics is not None:
                    check["metrics"] = query_metrics
                checks.append(check)
        status = "pass" if checks and all(item["status"] == "pass" for item in checks) else "fail"
    finally:
        down = run_command([docker, "compose", "-f", str(compose), "down", "--volumes", "--remove-orphans"], label="compose-down", cwd=compose.parent, log_dir=log_dir, events=events, timeout=args.tool_timeout)
        checks.append({"name": "compose-down", "status": "pass" if down.ok else "fail", "exit_code": down.exit_code})
        if not down.ok:
            status = "fail"
    events.write("acceptance", stage="runtime", status=status, checks=checks, evidence_source="fixture-runtime" if fixture_mode else "evaluator-runtime")
    return status, checks


def select_dnsb(repo_root: Path, requested: str | None) -> list[str]:
    if requested:
        return shlex.split(requested)
    venv = repo_root / ".venv" / "bin" / "dnsb"
    if venv.is_file() and os.access(venv, os.X_OK):
        return [str(venv)]
    found = shutil.which("dnsb")
    if found:
        return [found]
    uv = shutil.which("uv")
    if uv:
        return [uv, "run", "dnsb"]
    raise FileNotFoundError("dnsb, .venv/bin/dnsb, and uv were not found")


def record_agent_trace(
    trace: AgentTrace,
    *,
    raw_path: Path | None,
    attempt: int,
    events: EventLog,
) -> None:
    """Append compact hashes and tool records for every native JSONL event."""

    if raw_path is None or not raw_path.exists():
        return
    raw_lines = raw_path.read_bytes().splitlines()
    for index, raw_line in enumerate(raw_lines, start=1):
        try:
            payload = json.loads(raw_line.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            # Non-JSON CLI warnings are preserved in the raw file and counted
            # by the parser, but they are not synthetic agent events.
            continue
        if not isinstance(payload, dict):
            continue
        event_fields: dict[str, Any] = {
            "attempt": attempt,
            "agent": trace.provider,
            "agent_event_index": index,
            "agent_event_type": payload.get("type"),
            "agent_event_subtype": payload.get("subtype"),
            "session_id": trace.session_id,
            "raw_event_path": str(raw_path),
            "raw_event_bytes": len(raw_line),
            "raw_event_sha256": sha256_bytes(raw_line),
        }
        for key in ("thread_id", "session_id", "sessionId", "uuid"):
            if payload.get(key) is not None:
                event_fields[key] = payload[key]
        events.write("agent_event", **event_fields)
    for index, call in enumerate(trace.tool_calls, start=1):
        fields: dict[str, Any] = {
            "source": "agent",
            "agent": trace.provider,
            "attempt": attempt,
            "label": f"agent-{trace.provider}-{index}",
            "tool": call.get("tool_name") or "unknown",
            "tool_call_id": call.get("call_id"),
            "arguments_sha256": call.get("argument_sha256"),
            "result_sha256": call.get("output_sha256"),
            "status": call.get("status"),
            "exit_code": call.get("exit_code"),
        }
        duration = call.get("duration_s")
        if isinstance(duration, (int, float)) and not isinstance(duration, bool):
            fields["duration_s"] = duration
        events.write("tool_call", **fields)


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, help="Input paper PDF; defaults to task definition")
    parser.add_argument("--task", default="tsuking", help="Task id or task JSON path")
    parser.add_argument(
        "--condition",
        choices=("dns-builder", "blank"),
        default="dns-builder",
        help="dns-builder injects the skill; blank gives only PDF/task, requires model ReAct verification, then defers final feasibility to human review",
    )
    parser.add_argument("--provider", choices=("openai", "command", "agent", "fixture"), default="openai")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--command", help="Local model command; prompt is sent on stdin")
    parser.add_argument("--command-usage-file", help="Optional JSON usage file; path is exported as DNSB_USAGE_FILE (use {attempt})")
    parser.add_argument("--agent", choices=("codex", "claude"), default="codex", help="Native coding-agent CLI for provider=agent")
    parser.add_argument(
        "--agent-mode",
        choices=("workspace", "bundle"),
        default="workspace",
        help=(
            "agent provider contract: workspace lets the coding agent write the isolated "
            "project directly; bundle asks it to return the same JSON bundle as the API "
            "providers (useful for CLIs whose tool host is unavailable)"
        ),
    )
    parser.add_argument("--agent-command", help="Optional native-agent argv template; prompt is sent on stdin")
    parser.add_argument("--agent-sandbox", choices=("read-only", "workspace-write", "danger-full-access"), default="workspace-write", help="Codex sandbox for provider=agent")
    parser.add_argument("--agent-permission-mode", choices=("acceptEdits", "bypassPermissions", "dontAsk"), default="bypassPermissions", help="Claude Code permission mode for provider=agent")
    parser.add_argument("--openai-url", default="https://api.openai.com/v1/responses")
    parser.add_argument("--max-output-tokens", type=int, default=None)
    parser.add_argument("--input-price", type=float, default=None, help="USD per million non-cached input tokens")
    parser.add_argument("--output-price", type=float, default=None, help="USD per million output tokens")
    parser.add_argument("--cached-input-price", type=float, default=None, help="USD per million cached input tokens")
    parser.add_argument("--runtime", choices=("auto", "always", "never"), default="auto", help="Run evaluator-owned mechanism checks; auto records missing checks/daemon as not_run, always fails, never disables them")
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--model-timeout", type=float, default=300)
    parser.add_argument("--tool-timeout", type=float, default=900)
    parser.add_argument(
        "--max-pdf-chars",
        type=int,
        default=45_000,
        help="Maximum paper characters in each model prompt; task-relevant pages are retained when compacting (full PDF remains archived)",
    )
    parser.add_argument("--output", type=Path, help="Episode directory")
    parser.add_argument("--repo-root", type=Path, help="Repository root (default: two levels above this script)")
    parser.add_argument("--dnsb", help="Override dnsb command, e.g. '/path/to/dnsb'")
    parser.add_argument(
        "--allow-model-verify",
        action="store_true",
        help="Run an optional bundle verify_path (workspace agents are always gated; blank always requires it)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = make_parser()
    args = parser.parse_args(argv)
    if args.max_attempts < 1:
        parser.error("--max-attempts must be positive")
    script_root = Path(__file__).resolve()
    repo_root = (args.repo_root or script_root.parents[2]).resolve()
    task, task_path = resolve_task(repo_root, args.task)
    # Keep the resolved task object available to build_once/structural_checks.
    # The command-line string is no longer needed after task resolution.
    args.task = task
    task_id = str(task["task_id"])
    condition = args.condition
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = (args.output or (repo_root / "evaluation-runs" / f"{timestamp}-{task_id}-{safe_label(condition)}")).resolve()
    output.mkdir(parents=True, exist_ok=True)
    for name in ("input", "model", "project", "build-1", "build-2", "artifacts", "logs"):
        (output / name).mkdir(parents=True, exist_ok=True)
    run_id = f"{task_id}-{timestamp}-{sha256_bytes(str(output).encode())[:8]}"
    events = EventLog(output / "events.jsonl", run_id)
    start = time.perf_counter()
    pdf_path = args.pdf or task.get("paper")
    if not isinstance(pdf_path, (str, Path)):
        parser.error("--pdf is required when task has no paper")
    pdf_path = resolve_repo_path(repo_root, str(pdf_path))
    pdf_sha = sha256_file(pdf_path) if pdf_path.is_file() else None
    skill_root = repo_root / "skills" / "dns-builder"
    if args.provider == "fixture":
        run_model = "fixture"
    elif args.provider == "command":
        run_model = args.command or "command"
    elif args.provider == "agent":
        run_model = f"{args.agent}:{args.model}"
    else:
        run_model = args.model
    material_policy = FIXTURE_MATERIAL_POLICY if args.provider == "fixture" else MATERIAL_POLICY
    events.write(
        "run_start",
        runner_version=RUNNER_VERSION,
        material_policy=material_policy,
        task_id=task_id,
        task_definition=str(task_path),
        condition=condition,
        model=run_model,
        model_snapshot=args.model if args.provider in {"openai", "agent"} else None,
        provider=args.provider,
        agent=args.agent if args.provider == "agent" else None,
        agent_mode=args.agent_mode if args.provider == "agent" else None,
        agent_command_sha256=(
            sha256_bytes(args.agent_command.encode("utf-8"))
            if args.provider == "agent" and args.agent_command
            else None
        ),
        skill_id="dns-builder" if condition == "dns-builder" else None,
        skill_sha256=sha256_tree(skill_root) if condition == "dns-builder" and skill_root.is_dir() else None,
        pdf_path=str(pdf_path),
        pdf_sha256=pdf_sha,
        dnsbuilder_commit=git_value(repo_root, "rev-parse", "HEAD"),
        python=sys.version.split()[0],
        host=os.uname().nodename if hasattr(os, "uname") else None,
    )
    final_status = "failure"
    runtime_status = "not_run"
    human_seconds: float | None = None if condition == "blank" else 0
    agent_workspace: Path | None = None
    verification_report_path: Path | None = None
    try:
        pdf_text, pdf_sha, page_count = extract_pdf(pdf_path, output / "input", events, output / "logs", args.tool_timeout)
        events.write("acceptance", stage="pdf-evidence", status="pass", checks=[{"name": "pdf-text", "status": "pass", "pages": page_count, "sha256": pdf_sha}])
        provider = ModelProvider(args, repo_root, task)
        # The blank baseline must not require DNS-BUILDER to be installed or
        # discoverable.  It is reviewed from the project artifact by a human.
        dnsb_argv = [] if condition == "blank" else select_dnsb(repo_root, args.dnsb)
        args.dnsb_agent_bin = str(Path(dnsb_argv[0]).resolve()) if dnsb_argv else None
        if args.provider == "agent":
            # Use an external workspace for both conditions. This prevents
            # incidental parent traversal, but unrestricted shell tools still
            # require an OS sandbox for a formally isolated experiment.
            agent_workspace = Path(tempfile.mkdtemp(prefix=f"dnsb-{condition}-agent-"))
        repair: str | None = None
        config_path: str | None = None
        project_files: dict[str, str] | None = None
        notes = ""
        compose1: Path | None = None
        compose_data1: Any | None = None
        build_error = ""
        successful_attempt: int | None = None
        verify_path: str | None = None
        verification_report_path: Path | None = None
        verification_required = model_verification_required(args, condition)
        model_label = run_model
        for attempt in range(1, args.max_attempts + 1):
            verify_path = None
            verification_report_path = None
            if args.provider == "agent":
                # Each retry starts from a clean agent workspace.  The prior
                # workspace is archived before it is removed so a failed
                # model attempt remains inspectable.
                agent_workspace_path = agent_workspace
                assert agent_workspace_path is not None
                if agent_workspace_path.exists() and any(agent_workspace_path.iterdir()):
                    archived = output / "artifacts" / f"agent-workspace-attempt-{attempt - 1:03d}"
                    archive_hash = archive_agent_workspace(agent_workspace_path, archived)
                    events.write(
                        "artifact",
                        kind="agent_workspace_archive",
                        attempt=attempt - 1,
                        path=str(archived),
                        tree_sha256=archive_hash,
                    )
                    shutil.rmtree(agent_workspace_path)
                agent_workspace_path.mkdir(parents=True, exist_ok=True)
            else:
                agent_workspace_path = None
            if args.provider == "agent" and args.agent_mode == "workspace":
                assert agent_workspace_path is not None
                stage_agent_material(
                    agent_workspace_path,
                    repo_root=repo_root,
                    task=task,
                    pdf_text=pdf_text,
                    condition=condition,
                )
            prompt = build_prompt(
                task=task,
                pdf_text=pdf_text,
                repo_root=repo_root,
                condition=condition,
                repair=repair,
                max_pdf_chars=args.max_pdf_chars,
                workspace_mode=args.provider == "agent" and args.agent_mode == "workspace",
            )
            prompt_path = output / "model" / f"attempt-{attempt:03d}.prompt.txt"
            prompt_path.write_text(prompt, encoding="utf-8")
            model_result = provider.call(
                prompt,
                attempt,
                output / "model",
                agent_workspace_path if args.provider == "agent" else None,
            )
            # The Responses adapter uses this transient file to retrieve the
            # full prompt on later turns without resending it.  It is input
            # plumbing, not part of the delivered DNS project; remove it
            # before the workspace is copied into the episode artifact.
            if args.provider == "agent" and agent_workspace_path is not None:
                remove_transient_agent_material(agent_workspace_path)
            response_path = output / "model" / f"attempt-{attempt:03d}.response.txt"
            response_path.write_text(model_result.text, encoding="utf-8")
            usage = model_result.usage
            event_fields: dict[str, Any] = {
                "provider": args.provider,
                "model": model_label,
                "attempt": attempt,
                "retry": attempt > 1,
                "request_id": model_result.request_id,
                "duration_s": round(model_result.duration_s, 6),
                "usage": usage,
                "usage_source": model_result.usage_source,
                "prompt_path": str(prompt_path),
                "response_path": str(response_path),
                "prompt_bytes": prompt_path.stat().st_size,
                "prompt_sha256": sha256_file(prompt_path),
                "response_bytes": len(model_result.text.encode("utf-8")),
                "response_sha256": sha256_bytes(model_result.text.encode("utf-8")),
                "prompt_chars": len(prompt),
                "response_chars": len(model_result.text),
                "skill_prompt_chars": len(skill_material(repo_root, task)) if condition == "dns-builder" else 0,
                "pdf_chars": len(pdf_text),
                "pdf_prompt_chars": len(compact_pdf_for_prompt(pdf_text, args.max_pdf_chars, task.get("paper_needles"))),
                "status": "pass" if model_result.error is None else "fail",
            }
            if model_result.raw_event_path:
                event_fields["raw_event_path"] = str(model_result.raw_event_path)
                event_fields["raw_event_sha256"] = sha256_file(model_result.raw_event_path)
            if model_result.raw_stderr_path:
                event_fields["raw_stderr_path"] = str(model_result.raw_stderr_path)
                event_fields["raw_stderr_sha256"] = sha256_file(model_result.raw_stderr_path)
            if model_result.trajectory_path:
                event_fields["trajectory_path"] = str(model_result.trajectory_path)
            if model_result.agent_trace:
                event_fields.update(
                    {
                        "agent": model_result.agent_trace.provider,
                        "agent_session_id": model_result.agent_trace.session_id,
                        "agent_json_events": model_result.agent_trace.json_events,
                        "agent_malformed_lines": model_result.agent_trace.malformed_lines,
                    }
                )
            if isinstance(model_result.raw, dict) and args.provider == "agent":
                event_fields["agent_exit_code"] = model_result.raw.get("exit_code")
                event_fields["agent_argv_sha256"] = sha256_bytes(
                    shlex.join(model_result.raw.get("argv") or []).encode("utf-8")
                )
            cost = usage_cost(usage, args)
            if model_result.agent_trace:
                reported_cost = model_result.agent_trace.extra.get("total_cost_usd")
                if isinstance(reported_cost, (int, float)) and not isinstance(reported_cost, bool):
                    cost = float(reported_cost)
            if cost is not None:
                event_fields["cost_usd"] = cost
            if model_result.error:
                event_fields["error"] = model_result.error
            events.write("model_call", **event_fields)
            if model_result.agent_trace:
                record_agent_trace(
                    model_result.agent_trace,
                    raw_path=model_result.raw_event_path,
                    attempt=attempt,
                    events=events,
                )
            if args.provider == "agent":
                raw_workspace_manifest = output / "artifacts" / f"agent-workspace-{attempt}-raw-manifest.json"
                raw_manifest_result = run_manifest(
                    agent_workspace_path,
                    raw_workspace_manifest,
                    label=f"agent-raw-workspace-manifest-{attempt}",
                    args=args,
                    events=events,
                    log_dir=output / "logs",
                )
                events.write(
                    "artifact",
                    kind="agent_workspace_raw_manifest",
                    attempt=attempt,
                    path=str(raw_workspace_manifest),
                    status="pass" if raw_manifest_result.ok else "fail",
                )
            if model_result.error:
                build_error = f"model provider failed on attempt {attempt}: {model_result.error}"
                repair = build_error
                continue
            try:
                if args.provider == "agent" and args.agent_mode == "workspace":
                    if condition == "blank":
                        config_path = None
                    else:
                        config_path = "main.yml"
                    workspace_ok, workspace_checks = validate_agent_workspace(
                        agent_workspace_path,
                        config_path,
                        require_config=condition != "blank",
                        require_verification=verification_required,
                        reject_temporary_images=condition == "blank",
                    )
                    events.write(
                        "acceptance",
                        stage=f"agent-workspace-attempt-{attempt}",
                        status="pass" if workspace_ok else "fail",
                        checks=workspace_checks,
                        path=str(agent_workspace_path),
                    )
                    if not workspace_ok:
                        raise ValueError(
                            "agent workspace failed safety checks: "
                            + json.dumps(workspace_checks, ensure_ascii=False)
                        )
                    verify_path = discover_verification_script(agent_workspace_path)
                    # Archive the externally located workspace for either
                    # condition; the live temporary path is cleaned up later.
                    if (output / "project").exists():
                        shutil.rmtree(output / "project")
                    shutil.copytree(agent_workspace_path, output / "project", symlinks=True)
                    # Direct agents own the files; an empty mapping is retained
                    # solely to preserve the existing assertion and metadata
                    # shape used by bundle providers.
                    project_files = {}
                    notes = model_result.text[-MAX_REPAIR_CHARS:]
                else:
                    bundle = extract_json_object(model_result.text)
                    if condition == "blank":
                        config_path, project_files, verify_path, notes = validate_blank_bundle(bundle)
                    else:
                        config_path, project_files, verify_path, notes = validate_bundle(bundle, task)
                    (output / "model" / f"attempt-{attempt:03d}.response.json").write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
                    write_project(output / "project", project_files)
                if verification_required:
                    if not verify_path:
                        raise ValueError("model verification entrypoint is required")
                    report_path, report_ok, report_detail = inspect_verification_report(output / "project")
                    if not report_ok:
                        raise ValueError(f"model verification report is not passing: {report_detail}")
                    verification_report_path = report_path
                    if report_path is not None:
                        original_report = output / "artifacts" / f"model-verification-report-attempt-{attempt:03d}.json"
                        shutil.copy2(report_path, original_report)
                        events.write(
                            "artifact",
                            kind="model_verification_report_before_rerun",
                            attempt=attempt,
                            path=str(original_report),
                            status="pass",
                            sha256=sha256_file(original_report),
                        )
                evidence_added = write_evidence_file(
                    output / "project",
                    task=task,
                    pdf_path=pdf_path,
                    pdf_sha256=pdf_sha,
                    page_count=page_count,
                    notes=notes,
                    include_references=condition != "blank",
                )
                events.write(
                    "acceptance",
                    stage=f"evidence-attempt-{attempt}",
                    status="pass",
                    checks=[{"name": "provenance-file", "status": "pass", "runner_added": evidence_added}],
                    path=str(output / "project" / "evidence.md"),
                )
            except Exception as exc:
                build_error = (
                    f"agent workspace validation failed on attempt {attempt}: {exc}"
                    if args.provider == "agent" and args.agent_mode == "workspace"
                    else f"bundle validation failed on attempt {attempt}: {exc}"
                )
                repair = build_error
                events.write(
                    "acceptance",
                    stage=(
                        f"agent-workspace-attempt-{attempt}"
                        if args.provider == "agent" and args.agent_mode == "workspace"
                        else f"bundle-attempt-{attempt}"
                    ),
                    status="fail",
                    checks=[
                        {
                            "name": "workspace"
                            if args.provider == "agent" and args.agent_mode == "workspace"
                            else "bundle",
                            "status": "fail",
                            "detail": str(exc),
                        }
                    ],
                )
                continue
            if condition == "blank":
                if verification_required:
                    react_ok, react_checks = audit_agent_react(
                        model_result.agent_trace,
                        verify_path,
                        require=True,
                    )
                    events.write(
                        "acceptance",
                        stage="model-react",
                        status="pass" if react_ok else "fail",
                        checks=react_checks,
                    )
                    if not react_ok:
                        build_error = "model did not execute the verification entrypoint through a successful ReAct tool call"
                        repair = build_error
                        continue
                    verification_status, verification_checks, verification_report_path = run_model_verification(
                        project_dir=output / "project",
                        verify_path=verify_path or "",
                        compose_path=None,
                        args=args,
                        events=events,
                        log_dir=output / "logs",
                    )
                    if verification_status != "pass":
                        build_error = "model verification rerun failed: " + json.dumps(verification_checks, ensure_ascii=False)
                        repair = build_error
                        continue
                project_manifest = output / "artifacts" / f"blank-project-attempt-{attempt}-manifest.json"
                project_manifest_result = run_manifest(
                    output / "project",
                    project_manifest,
                    label=f"blank-project-manifest-{attempt}",
                    args=args,
                    events=events,
                    log_dir=output / "logs",
                )
                events.write(
                    "artifact",
                    kind="blank_project_manifest",
                    attempt=attempt,
                    path=str(project_manifest),
                    status="pass" if project_manifest_result.ok else "fail",
                )
                if not project_manifest_result.ok:
                    build_error = "blank project manifest generation failed"
                    repair = build_error
                    continue
                successful_attempt = attempt
                break
            ok, compose1, compose_data1, build_error = build_once(project_dir=output / "project", config_path=config_path or "main.yml", build_dir=output / "build-1", attempt=attempt, args=args, events=events, log_dir=output / "logs", dnsb_argv=dnsb_argv)
            if ok:
                if args.provider == "agent" and args.agent_mode == "workspace":
                    attempt_manifest = output / "artifacts" / f"agent-workspace-{attempt}-manifest.json"
                    manifest_result = run_manifest(
                        output / "project",
                        attempt_manifest,
                        label=f"agent-workspace-manifest-{attempt}",
                        args=args,
                        events=events,
                        log_dir=output / "logs",
                    )
                    events.write(
                        "artifact",
                        kind="agent_workspace_manifest",
                        attempt=attempt,
                        path=str(attempt_manifest),
                        status="pass" if manifest_result.ok else "fail",
                    )
                successful_attempt = attempt
                events.write("acceptance", stage="build", status="pass", checks=[{"name": "dnsb-build", "status": "pass"}, {"name": "compose", "status": "pass"}], compose_path=str(compose1))
                break
            events.write("acceptance", stage=f"build-attempt-{attempt}", status="fail", checks=[{"name": "build", "status": "fail", "detail": build_error}])
            repair = build_error
            compose1 = None
            compose_data1 = None
        else:
            raise RuntimeError(f"all {args.max_attempts} model attempts failed: {build_error or 'unknown error'}")
        if condition == "blank":
            review_path = write_human_review_template(output, task)
            events.write(
                "artifact",
                kind="human_review_template",
                path=str(review_path),
                status="pass",
            )
            events.write(
                "acceptance",
                stage="human-review",
                status="pending",
                checks=[
                    {
                        "name": "human-feasibility-review",
                        "status": "pending",
                        "detail": (
                            "model ReAct verification and independent verifier rerun passed; human review is the final paper-faithfulness and portability decision"
                            if verification_required
                            else "offline fixture has no model/ReAct verification; human review is diagnostic only"
                        ),
                    }
                ],
                review_path=str(review_path),
            )
            final_status = "pending_review"
            raise PendingHumanReview()
        assert config_path is not None and project_files is not None and compose1 is not None and compose_data1 is not None
        if verification_required:
            react_ok, react_checks = audit_agent_react(
                model_result.agent_trace,
                verify_path,
                require=True,
            )
            events.write(
                "acceptance",
                stage="model-react",
                status="pass" if react_ok else "fail",
                checks=react_checks,
            )
            if not react_ok:
                raise RuntimeError(
                    "model did not execute the verification entrypoint through a successful ReAct tool call"
                )
            verification_status, verification_checks, verification_report_path = run_model_verification(
                project_dir=output / "project",
                verify_path=verify_path or "",
                compose_path=compose1,
                args=args,
                events=events,
                log_dir=output / "logs",
            )
            if verification_status != "pass":
                raise RuntimeError(
                    "model verification rerun failed: "
                    + json.dumps(verification_checks, ensure_ascii=False)
                )
        elif args.allow_model_verify and verify_path:
            verification_status, verification_checks, verification_report_path = run_model_verification(
                project_dir=output / "project",
                verify_path=verify_path,
                compose_path=compose1,
                args=args,
                events=events,
                log_dir=output / "logs",
            )
            if verification_status != "pass":
                raise RuntimeError(
                    "optional model verification rerun failed: "
                    + json.dumps(verification_checks, ensure_ascii=False)
                )
        runtime_status, runtime_checks = run_runtime(compose1, task, args, events, output / "logs")
        # A clean second build is the reproducibility gate.  It never reuses build-1's output directory.
        ok2, compose2, compose_data2, rebuild_error = build_once(project_dir=output / "project", config_path=config_path, build_dir=output / "build-2", attempt=2, args=args, events=events, log_dir=output / "logs", dnsb_argv=dnsb_argv)
        if not ok2 or compose2 is None or compose_data2 is None:
            events.write("acceptance", stage="reproducibility", status="fail", checks=[{"name": "second-build", "status": "fail", "detail": rebuild_error}])
            raise RuntimeError(rebuild_error or "second build failed")
        manifest1_path = output / "artifacts" / "build-1-manifest.json"
        manifest2_path = output / "artifacts" / "build-2-manifest.json"
        manifest1_result = run_manifest(compose1.parent, manifest1_path, label="manifest-build-1", args=args, events=events, log_dir=output / "logs")
        manifest2_result = run_manifest(compose2.parent, manifest2_path, label="manifest-build-2", args=args, events=events, log_dir=output / "logs")
        if not manifest1_result.ok or not manifest2_result.ok:
            events.write("acceptance", stage="reproducibility", status="fail", checks=[{"name": "manifest-build-1", "status": "pass" if manifest1_result.ok else "fail"}, {"name": "manifest-build-2", "status": "pass" if manifest2_result.ok else "fail"}])
            raise RuntimeError("manifest generation failed for one or both clean builds")
        manifest1 = json.loads(manifest1_path.read_text(encoding="utf-8")) if manifest1_path.exists() else {}
        manifest2 = json.loads(manifest2_path.read_text(encoding="utf-8")) if manifest2_path.exists() else {}
        semantic1, semantic_hash1 = semantic_snapshot(compose1.parent, compose_data1)
        semantic2, semantic_hash2 = semantic_snapshot(compose2.parent, compose_data2)
        (output / "artifacts" / "semantic-1.json").write_text(json.dumps(semantic1, ensure_ascii=False, indent=2), encoding="utf-8")
        (output / "artifacts" / "semantic-2.json").write_text(json.dumps(semantic2, ensure_ascii=False, indent=2), encoding="utf-8")
        exact = manifest1.get("tree_sha256") == manifest2.get("tree_sha256")
        semantic_match = semantic_hash1 == semantic_hash2
        repro = {"manifest_hash_1": manifest1.get("tree_sha256"), "manifest_hash_2": manifest2.get("tree_sha256"), "semantic_hash_1": semantic_hash1, "semantic_hash_2": semantic_hash2, "exact_match": exact, "semantic_match": semantic_match}
        (output / "artifacts" / "reproducibility.json").write_text(json.dumps(repro, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        repro_status = "pass" if semantic_match else "fail"
        events.write("acceptance", stage="reproducibility", status=repro_status, checks=[{"name": "second-build", "status": "pass"}, {"name": "semantic-match", "status": repro_status, "semantic_hash_1": semantic_hash1, "semantic_hash_2": semantic_hash2}, {"name": "exact-manifest", "status": "pass" if exact else "info"}], artifacts=str(output / "artifacts" / "reproducibility.json"))
        if not semantic_match:
            raise RuntimeError("semantic snapshots differ across clean builds")
        if runtime_status == "fail":
            final_status = "failure"
        elif runtime_status == "not_run":
            final_status = "partial"
        else:
            final_status = "success"
    except PendingHumanReview:
        final_status = "pending_review"
    except Exception as exc:
        final_status = "failure"
        # Keep a failed blank episode reviewable.  A human may explicitly
        # classify an episode with no completed project as ``infeasible``;
        # ``review_episode.py`` still rejects a positive feasible decision
        # until both model gates pass.
        if condition == "blank":
            review_path = output / "artifacts" / "human-review.json"
            if not review_path.exists():
                review_path = write_human_review_template(output, task)
                events.write("artifact", kind="human_review_template", path=str(review_path), status="pass")
                events.write(
                    "acceptance",
                    stage="human-review",
                    status="pending",
                    checks=[
                        {
                            "name": "human-feasibility-review",
                            "status": "pending",
                            "detail": "terminal blank failure requires an explicit infeasible or feasible human classification",
                        }
                    ],
                    review_path=str(review_path),
                )
        events.write("runner_error", error=str(exc), traceback=traceback.format_exc(limit=8))
    finally:
        if agent_workspace is not None:
            shutil.rmtree(agent_workspace, ignore_errors=True)
    wall = time.perf_counter() - start
    events.write(
        "run_end",
        status=final_status,
        wall_seconds=round(wall, 6),
        model_latency_seconds=round(events.model_latency_seconds, 6),
        tool_seconds=round(events.tool_seconds, 6),
        model_verification_seconds=round(events.model_verification_seconds, 6),
        model_input_tokens=events.model_usage["input_tokens"],
        model_output_tokens=events.model_usage["output_tokens"],
        model_reasoning_tokens=events.model_usage["reasoning_tokens"],
        cached_input_tokens=events.model_usage["cached_input_tokens"],
        model_total_tokens=events.model_usage["total_tokens"],
        human_seconds=human_seconds,
        runtime_status=runtime_status,
    )
    summary_script = repo_root / "skills" / "dns-builder" / "scripts" / "summarize_events.py"
    summary_path = output / "summary.json"
    try:
        subprocess.run([sys.executable, str(summary_script), "--events", str(output / "events.jsonl"), "--out", str(summary_path)], cwd=repo_root, timeout=30, check=False)
    except Exception:
        pass
    metadata = {
        "run_id": run_id,
        "status": final_status,
        "task_id": task_id,
        "condition": condition,
        "provider": args.provider,
        "agent": args.agent if args.provider == "agent" else None,
        "agent_mode": args.agent_mode if args.provider == "agent" else None,
        "model": run_model,
        "pdf_sha256": pdf_sha,
        "output": str(output),
        "runner_version": RUNNER_VERSION,
        "material_policy": material_policy,
        "artifacts": {
            "events": str(output / "events.jsonl"),
            "summary": str(summary_path),
            "episode_manifest": str(output / "artifacts" / "episode-manifest.json"),
            "human_review": str(output / "artifacts" / "human-review.json") if condition == "blank" else None,
            "verification_report": str(verification_report_path) if verification_report_path else None,
        },
    }
    (output / "run.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_episode_manifest(output)
    print(json.dumps(metadata, ensure_ascii=False, indent=2))
    return 0 if final_status in {"success", "partial", "pending_review"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
