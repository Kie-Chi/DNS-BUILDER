#!/usr/bin/env python3
"""Run a small, auditable Responses API coding agent in one workspace.

The native Codex CLI can inherit desktop-only tools from a host proxy.  This
adapter intentionally exposes only three local tools to the model and emits a
Codex-compatible JSONL stream so ``dnsb_agent_runner.py`` can retain the same
ATIF/usage/audit path. File tools enforce workspace paths; the shell remains
unrestricted host access, not an OS sandbox. Formal isolation requires an
external container or VM with controlled mounts, networking, and Docker/cache.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


MAX_FILE_BYTES = 20 * 1024 * 1024
# The proxy used by the Harbor/SABER adapter does not preserve
# ``previous_response_id``.  Re-sending the full prompt and a long transcript
# on every turn therefore multiplies input tokens and latency.  Keep enough
# recent output for repair, while storing the complete initial prompt in the
# workspace so the model can retrieve it when a detail is needed.
MAX_TOOL_OUTPUT = 10_000
# Keep the replay transcript small enough for the stateless proxy.  A tool
# result is still retained in the emitted event stream at MAX_TOOL_OUTPUT; the
# shorter copy is only the hint sent back to the model on the next request.
MAX_HISTORY_TOOL_OUTPUT = 2_500
# The proxy does not support ``previous_response_id``, so the adapter sends
# a compact transcript on every turn.  Keep these limits configurable for
# bounded evaluation runs: the workspace and the durable context file carry
# the full state, while a shorter transcript prevents repair loops from
# multiplying input tokens.
MAX_HISTORY_CHARS = max(2_000, int(os.environ.get("DNSB_HISTORY_CHARS", "18000")))
PROMPT_ANCHOR_CHARS = max(1_000, int(os.environ.get("DNSB_PROMPT_ANCHOR_CHARS", "12000")))
RESPONSES_TIMEOUT_SECONDS = max(30.0, float(os.environ.get("DNSB_RESPONSES_TIMEOUT", "180")))
RESPONSES_RETRIES = max(1, int(os.environ.get("DNSB_RESPONSES_RETRIES", "3")))
REASONING_EFFORT = os.environ.get("DNSB_REASONING_EFFORT", "low").strip().lower() or "low"
if REASONING_EFFORT not in {"minimal", "low", "medium", "high"}:
    REASONING_EFFORT = "low"
# Keep an unattended episode bounded.  The defaults remain generous for the
# general adapter, while evaluation wrappers can lower them when a model is
# repeatedly inspecting the same failing command (for example, when a local
# tool is unavailable).  This avoids spending the whole model timeout on a
# no-progress ReAct loop and makes the failure reason auditable in the raw
# trajectory.
MAX_TURNS = max(1, int(os.environ.get("DNSB_MAX_TURNS", "120")))
MAX_TOOL_CALLS = max(1, int(os.environ.get("DNSB_MAX_TOOL_CALLS", "300")))


TOOLS = [
    {
        "type": "function",
        "name": "read_file",
        "description": "Read a UTF-8 text file below the current workspace.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "max_bytes": {"type": "integer", "minimum": 1, "maximum": MAX_FILE_BYTES},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "write_file",
        "description": "Write a UTF-8 text file below the current workspace, creating parent directories.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "run_shell",
        "description": "Run a shell command with the workspace as its working directory. Keep all created files below the workspace.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "timeout_seconds": {"type": "number", "minimum": 1, "maximum": 900},
            },
            "required": ["command"],
            "additionalProperties": False,
        },
    },
]


def emit(payload: Mapping[str, Any]) -> None:
    sys.stdout.write(json.dumps(dict(payload), ensure_ascii=False) + "\n")
    sys.stdout.flush()


def clipped(value: Any, limit: int = MAX_TOOL_OUTPUT) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n[tool output truncated at {limit} characters]"


def resolve_inside(root: Path, raw: Any) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("path must be a non-empty string")
    candidate = Path(raw)
    resolved = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError("path escapes the workspace file-tool boundary")
    return resolved


def run_shell(root: Path, command: str, timeout: float) -> dict[str, Any]:
    """Execute a bounded host command; cwd is not a filesystem sandbox."""

    if not isinstance(command, str) or not command.strip():
        raise ValueError("command must be a non-empty string")
    timeout = max(1.0, min(float(timeout), 900.0))
    env = os.environ.copy()
    env["DNSB_AGENT_WORKSPACE"] = str(root)
    env["PWD"] = str(root)
    started = time.perf_counter()
    process = subprocess.Popen(
        ["/bin/zsh", "-lc", command],
        cwd=str(root),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    timed_out = False
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        stdout = exc.stdout or b""
        stderr = exc.stderr or b""
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            process.kill()
        more_out, more_err = process.communicate()
        stdout += more_out or b""
        stderr += more_err or b""
    duration = round(time.perf_counter() - started, 6)
    return {
        "command": command,
        "cwd": str(root),
        "exit_code": 124 if timed_out else int(process.returncode or 0),
        "timed_out": timed_out,
        "duration_seconds": duration,
        "stdout": clipped(stdout.decode("utf-8", errors="replace")),
        "stderr": clipped(stderr.decode("utf-8", errors="replace")),
    }


def execute_tool(root: Path, name: str, arguments: Mapping[str, Any]) -> tuple[int, str, str]:
    """Return (exit_code, display_command, serialized_result)."""

    if name == "read_file":
        path = resolve_inside(root, arguments.get("path"))
        if not path.is_file() or path.is_symlink():
            raise FileNotFoundError(path)
        limit = int(arguments.get("max_bytes") or 200_000)
        limit = max(1, min(limit, MAX_FILE_BYTES))
        data = path.read_bytes()
        text = data[:limit].decode("utf-8", errors="replace")
        if len(data) > limit:
            text += f"\n[read_file truncated at {limit} bytes]"
        result = {"path": path.relative_to(root).as_posix(), "bytes": len(data), "content": text}
        return 0, f"read_file {result['path']}", json.dumps(result, ensure_ascii=False)

    if name == "write_file":
        path = resolve_inside(root, arguments.get("path"))
        content = arguments.get("content")
        if not isinstance(content, str):
            raise ValueError("content must be a string")
        encoded = content.encode("utf-8")
        if len(encoded) > MAX_FILE_BYTES:
            raise ValueError(f"file exceeds {MAX_FILE_BYTES} bytes")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(encoded)
        result = {"path": path.relative_to(root).as_posix(), "bytes": len(encoded), "status": "written"}
        return 0, f"write_file {result['path']}", json.dumps(result, ensure_ascii=False)

    if name == "run_shell":
        result = run_shell(root, str(arguments.get("command", "")), float(arguments.get("timeout_seconds") or 900))
        return int(result["exit_code"]), str(result["command"]), json.dumps(result, ensure_ascii=False)

    raise ValueError(f"unsupported tool: {name}")


def normalize_usage(raw: Any) -> dict[str, int]:
    usage = raw if isinstance(raw, Mapping) else {}
    details = usage.get("input_tokens_details") if isinstance(usage.get("input_tokens_details"), Mapping) else {}
    out_details = usage.get("output_tokens_details") if isinstance(usage.get("output_tokens_details"), Mapping) else {}
    input_tokens = int(usage.get("input_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or 0)
    total_tokens = int(usage.get("total_tokens") or input_tokens + output_tokens)
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "reasoning_tokens": int(out_details.get("reasoning_tokens") or 0),
        "cached_input_tokens": int(details.get("cached_tokens") or 0),
        "total_tokens": total_tokens,
    }


def add_usage(total: dict[str, int], raw: Any) -> dict[str, int]:
    current = normalize_usage(raw)
    for key in total:
        total[key] += current[key]
    return current


def response_request(
    *,
    url: str,
    api_key: str,
    model: str,
    input_items: Any,
    previous_response_id: str | None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": model,
        "input": input_items,
        "tools": TOOLS,
        "tool_choice": "auto",
        "parallel_tool_calls": False,
        "max_output_tokens": 12_000,
        "reasoning": {"effort": REASONING_EFFORT},
        # The Harbor/SABER-compatible models-proxy rejects stored Responses
        # requests (HTTP 400: ``store expected false``).  This adapter already
        # resends the compacted input history on every turn, so persistence is
        # unnecessary and would make the run endpoint-dependent.
        "store": False,
    }
    # The Harbor/SABER-compatible proxy accepts API-key requests but does not
    # support ``previous_response_id`` for those requests.  The caller passes
    # the complete compacted input history instead.
    request = Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    last_error: Exception | None = None
    for attempt in range(1, RESPONSES_RETRIES + 1):
        # ``urlopen(..., timeout=...)`` is an inactivity timeout.  A proxy
        # that keeps an HTTPS response open without completing it can
        # therefore hold an unattended evaluation for many minutes.  Add an
        # absolute per-request deadline so retries and the runner's model
        # timeout remain meaningful.
        alarm_previous = signal.getsignal(signal.SIGALRM)

        def alarm_handler(_signum: int, _frame: Any) -> None:
            raise TimeoutError(
                f"Responses API absolute timeout after {RESPONSES_TIMEOUT_SECONDS:.0f}s"
            )

        signal.signal(signal.SIGALRM, alarm_handler)
        signal.setitimer(signal.ITIMER_REAL, RESPONSES_TIMEOUT_SECONDS)
        try:
            with urlopen(request, timeout=RESPONSES_TIMEOUT_SECONDS) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if exc.code not in {408, 409, 429} and not 500 <= exc.code < 600:
                raise RuntimeError(f"Responses API HTTP {exc.code}: {clipped(detail, 4000)}") from exc
            last_error = RuntimeError(f"Responses API HTTP {exc.code}: {clipped(detail, 4000)}")
        except TimeoutError as exc:
            last_error = RuntimeError(str(exc))
        except URLError as exc:
            last_error = RuntimeError(f"Responses API connection error: {exc}")
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, alarm_previous)
        if attempt < RESPONSES_RETRIES:
            time.sleep(min(8.0, float(2 ** (attempt - 1))))
    raise last_error or RuntimeError("Responses API request failed")


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: responses_workspace_agent.py WORKSPACE MODEL", file=sys.stderr)
        return 2
    root = Path(sys.argv[1]).resolve()
    model = sys.argv[2]
    root.mkdir(parents=True, exist_ok=True)
    prompt = sys.stdin.read()
    if not prompt.strip():
        print("empty prompt", file=sys.stderr)
        return 2
    # Make the complete task/PDF/reference prompt available to later turns
    # without charging it again on every Responses request.  The runner
    # removes this transient file before preserving the final project.
    context_path = root / ".runner-evaluation-context.txt"
    try:
        context_path.write_text(prompt, encoding="utf-8")
    except OSError as exc:
        print(f"could not save prompt context: {exc}", file=sys.stderr)
        return 2
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    base_url = os.environ.get("SABER_OPENAI_BASE_URL", "").strip().rstrip("/")
    if not api_key or not base_url:
        print("OPENAI_API_KEY and SABER_OPENAI_BASE_URL are required", file=sys.stderr)
        return 2
    url = base_url if base_url.endswith("/responses") else base_url + "/responses"
    session_id = f"responses-{uuid.uuid4().hex}"
    emit({"type": "thread.started", "thread_id": session_id})
    total_usage = {key: 0 for key in ("input_tokens", "output_tokens", "reasoning_tokens", "cached_input_tokens", "total_tokens")}
    previous: str | None = None
    # Each entry is one complete assistant function-call turn plus its
    # function_call_output items.  Keeping these as units is important when
    # ``store=false``: the proxy validates that every output has a matching
    # call in the same request and rejects orphaned outputs.
    history_units: list[list[dict[str, Any]]] = []
    if len(prompt) <= PROMPT_ANCHOR_CHARS:
        prompt_anchor = prompt
    else:
        half = PROMPT_ANCHOR_CHARS // 2
        prompt_anchor = (
            prompt[:half]
            + "\n\n[Middle of the original task prompt is in "
            ".runner-evaluation-context.txt; omitted from this turn.]\n\n"
            + prompt[-half:]
        )
    history: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
    tool_calls = 0
    try:
        for turn_index in range(MAX_TURNS):
            emit({"type": "turn.started"})
            if turn_index == 0:
                request_input = history
            else:
                request_input = [
                    {
                        "role": "user",
                        "content": (
                            "Continue from the current workspace state. The complete original "
                            "task and PDF/reference prompt is in `.runner-evaluation-context.txt`; "
                            "read it with `read_file` if a detail is unclear. Do not restart or "
                            "summarize the whole project; inspect the current files, run the next "
                            "bounded check, and repair the project.\n\n"
                            "Stable task anchor:\n"
                            + prompt_anchor
                        ),
                    },
                    *(item for unit in history_units for item in unit),
                ]
            response = response_request(
                url=url,
                api_key=api_key,
                model=model,
                input_items=request_input,
                previous_response_id=previous,
            )
            previous = str(response.get("id") or previous or "")
            add_usage(total_usage, response.get("usage"))
            output_items = response.get("output") if isinstance(response.get("output"), list) else []
            calls: list[dict[str, Any]] = []
            compact_output: list[dict[str, Any]] = []
            for item in output_items:
                if not isinstance(item, Mapping):
                    continue
                if item.get("type") == "message":
                    content = item.get("content") if isinstance(item.get("content"), list) else []
                    text_parts = [str(block.get("text")) for block in content if isinstance(block, Mapping) and isinstance(block.get("text"), str)]
                    text = "\n".join(part for part in text_parts if part)
                    if text:
                        emit({"type": "item.completed", "item": {"id": str(item.get("id") or uuid.uuid4().hex), "type": "agent_message", "text": text}})
                        compact_output.append({"role": "assistant", "content": text})
                elif item.get("type") == "function_call":
                    call_id = str(item.get("call_id") or item.get("id") or uuid.uuid4().hex)
                    name = str(item.get("name") or "")
                    raw_args = item.get("arguments")
                    try:
                        arguments = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                    except json.JSONDecodeError:
                        arguments = {}
                    if not isinstance(arguments, Mapping):
                        arguments = {}
                    calls.append({"call_id": call_id, "name": name, "arguments": dict(arguments)})
                    compact_output.append(
                        {
                            "type": "function_call",
                            "call_id": call_id,
                            "name": name,
                            "arguments": raw_args if isinstance(raw_args, str) else json.dumps(arguments, ensure_ascii=False),
                        }
                    )
            emit({"type": "turn.completed", "usage": total_usage})
            if not calls:
                return 0
            tool_outputs: list[dict[str, Any]] = []
            for call in calls:
                tool_calls += 1
                if tool_calls > MAX_TOOL_CALLS:
                    raise RuntimeError(f"tool call limit exceeded: {MAX_TOOL_CALLS}")
                call_id = call["call_id"]
                name = call["name"]
                arguments = call["arguments"]
                try:
                    exit_code, display_command, result = execute_tool(root, name, arguments)
                    status = "completed" if exit_code == 0 else "failed"
                except Exception as exc:  # keep the ReAct loop alive so the model can repair
                    exit_code = 1
                    display_command = f"{name} {arguments.get('path') or arguments.get('command') or ''}".strip()
                    result = json.dumps({"error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False)
                    status = "failed"
                emit({"type": "item.started", "item": {"id": call_id, "type": "command_execution", "name": name, "command": display_command, "status": "in_progress", "exit_code": None}})
                emit({"type": "item.completed", "item": {"id": call_id, "type": "command_execution", "name": name, "command": display_command, "aggregated_output": clipped(result), "status": status, "exit_code": exit_code}})
                tool_outputs.append({"type": "function_call_output", "call_id": call_id, "output": clipped(result, MAX_HISTORY_TOOL_OUTPUT)})
            history_units.append([*compact_output, *tool_outputs])
            # The proxy cannot use previous_response_id with this API key.  Do
            # keep the original task prompt on every request, but retain only
            # a small recent tool transcript; the workspace itself is the
            # durable state and the next call can inspect it with read_file or
            # run_shell.  This prevents repeated Docker logs from exhausting
            # the context window and keeps response latency bounded.
            while len(history_units) > 1 and sum(
                len(json.dumps(item, ensure_ascii=False))
                for unit in history_units
                for item in unit
            ) > MAX_HISTORY_CHARS:
                history_units.pop(0)
            history = [
                {"role": "user", "content": prompt},
                {"role": "user", "content": "Continue from the current workspace state. The recent tool transcript below is only a hint; inspect files and rerun checks as needed."},
                *(item for unit in history_units for item in unit),
            ]
        raise RuntimeError(f"turn limit exceeded: {MAX_TURNS}")
    except Exception as exc:
        print(f"responses workspace agent failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
