#!/usr/bin/env python3
"""Normalize Codex/Claude Code JSONL streams for DNS-BUILDER episodes.

The native stream is always kept verbatim by the runner.  This module only
creates a small, dependency-free ATIF-shaped projection and a provider-neutral
summary.  It deliberately keeps hashes for arguments/results instead of
copying potentially sensitive command output into ``events.jsonl``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping


TOKEN_FIELDS = (
    "input_tokens",
    "output_tokens",
    "reasoning_tokens",
    "cached_input_tokens",
    "total_tokens",
)


def empty_usage() -> dict[str, int | None]:
    return {key: None for key in TOKEN_FIELDS}


def _number(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    return None


def _first_number(mapping: Mapping[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = _number(mapping.get(key))
        if value is not None:
            return value
    return None


def normalize_usage(raw: Any) -> dict[str, int | None]:
    """Normalize common OpenAI/Codex/Anthropic usage spellings."""

    usage = raw if isinstance(raw, Mapping) else {}
    result = empty_usage()
    result["input_tokens"] = _first_number(usage, "input_tokens", "prompt_tokens")
    result["output_tokens"] = _first_number(
        usage, "output_tokens", "completion_tokens"
    )
    result["total_tokens"] = _first_number(usage, "total_tokens")
    result["reasoning_tokens"] = _first_number(
        usage,
        "reasoning_tokens",
        "reasoning_output_tokens",
        "reasoning_output_token_count",
    )
    result["cached_input_tokens"] = _first_number(
        usage,
        "cached_input_tokens",
        "cache_read_input_tokens",
        "cached_tokens",
    )
    if result["total_tokens"] is None:
        input_tokens = result["input_tokens"]
        output_tokens = result["output_tokens"]
        if input_tokens is not None and output_tokens is not None:
            result["total_tokens"] = input_tokens + output_tokens
    return result


def _merge_usage(left: dict[str, int | None], right: Mapping[str, Any]) -> None:
    normalized = normalize_usage(right)
    for key in TOKEN_FIELDS:
        value = normalized.get(key)
        if value is not None:
            left[key] = value if left[key] is None else int(left[key]) + value


def _usage_is_present(usage: Mapping[str, Any]) -> bool:
    return any(_number(usage.get(key)) is not None for key in TOKEN_FIELDS) or any(
        _number(usage.get(key)) is not None
        for key in (
            "prompt_tokens",
            "completion_tokens",
            "reasoning_output_tokens",
            "cache_read_input_tokens",
            "cache_creation_input_tokens",
        )
    )


def _sha(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        data = value
    elif isinstance(value, str):
        data = value.encode("utf-8", errors="replace")
    else:
        data = json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _string(value: Any) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)


def _event_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    text = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _duration(start: Any, end: Any) -> float | None:
    first = _event_time(start)
    last = _event_time(end)
    if first is None or last is None:
        return None
    seconds = (last - first).total_seconds()
    return round(seconds, 6) if seconds >= 0 else None


def _text_from_content(content: Any) -> tuple[str, str | None, list[dict[str, Any]]]:
    if isinstance(content, str):
        return content, None, []
    if not isinstance(content, list):
        return _string(content), None, []
    text: list[str] = []
    reasoning: list[str] = []
    tools: list[dict[str, Any]] = []
    for block in content:
        if not isinstance(block, Mapping):
            text.append(_string(block))
            continue
        kind = block.get("type")
        if kind == "tool_use":
            tools.append(dict(block))
        elif kind in {"thinking", "reasoning", "analysis"}:
            value = block.get("text", block.get("thinking", ""))
            if value:
                reasoning.append(_string(value))
        elif kind == "redacted_thinking":
            # Encrypted Anthropic reasoning is intentionally not copied into
            # the normalized trajectory.
            continue
        elif isinstance(block.get("text"), str):
            text.append(block["text"])
        else:
            text.append(_string(block))
    return "\n\n".join(part for part in text if part), (
        "\n\n".join(part for part in reasoning if part) or None
    ), tools


def _observation(call_id: str, output: Any) -> dict[str, Any] | None:
    if output is None:
        return None
    return {"results": [{"source_call_id": call_id or None, "content": _string(output)}]}


@dataclass
class AgentTrace:
    provider: str
    text: str = ""
    usage: dict[str, int | None] = field(default_factory=empty_usage)
    usage_source: str = "unavailable"
    session_id: str | None = None
    model: str | None = None
    version: str | None = None
    json_events: int = 0
    malformed_lines: int = 0
    steps: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def trajectory(self, raw_path: str | None = None) -> dict[str, Any]:
        final_extra = dict(self.extra)
        final_extra["provider"] = self.provider
        final_extra["json_events"] = self.json_events
        final_extra["malformed_lines"] = self.malformed_lines
        if raw_path:
            final_extra["raw_event_path"] = raw_path
        return {
            "schema_version": "ATIF-v1.7",
            "session_id": self.session_id or "unknown",
            "agent": {
                "name": self.provider,
                "version": self.version or "unknown",
                "model_name": self.model,
                "extra": final_extra or None,
            },
            "steps": self.steps,
            "final_metrics": {
                "total_prompt_tokens": self.usage.get("input_tokens"),
                "total_completion_tokens": self.usage.get("output_tokens"),
                "total_cached_tokens": self.usage.get("cached_input_tokens"),
                "total_cost_usd": self.extra.get("total_cost_usd"),
                "total_steps": len(self.steps),
                "extra": {
                    "reasoning_output_tokens": self.usage.get("reasoning_tokens"),
                    "total_tokens": self.usage.get("total_tokens"),
                },
            },
        }


def _codex_item_step(item: Mapping[str, Any], timestamp: Any, model: str | None) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    kind = str(item.get("type") or "")
    item_id = str(item.get("id") or "")
    if kind in {"agent_message", "message"}:
        text = item.get("text", item.get("message", ""))
        step = {
            "step_id": 0,
            "timestamp": timestamp,
            "source": "agent",
            "message": _string(text),
            "model_name": model,
        }
        return step, None
    if kind in {"command_execution", "function_call", "custom_tool_call", "mcp_tool_call", "web_search_call"} or "tool" in kind:
        tool_name = str(item.get("name") or kind)
        arguments = item.get("arguments", item.get("input", item.get("command", {})))
        output = item.get("aggregated_output", item.get("output", item.get("result")))
        call_id = item_id
        call = {
            "call_id": call_id,
            "tool_name": tool_name,
            "arguments": arguments if isinstance(arguments, Mapping) else {"value": arguments},
            "argument_sha256": _sha(arguments),
            "output_sha256": _sha(output),
            "status": item.get("status"),
            "exit_code": item.get("exit_code"),
            "output": output,
            "timestamp": timestamp,
            "duration_s": None,
        }
        step = {
            "step_id": 0,
            "timestamp": timestamp,
            "source": "agent",
            "message": "",
            "model_name": model,
            "tool_calls": [
                {
                    "tool_call_id": call_id,
                    "function_name": tool_name,
                    "arguments": call["arguments"],
                    "extra": {
                        "raw_arguments_sha256": call["argument_sha256"],
                        "status": call["status"],
                    },
                }
            ],
            "observation": _observation(call_id, output),
        }
        return step, call
    return None, None


def _parse_codex(events: list[dict[str, Any]], *, model_hint: str | None) -> AgentTrace:
    trace = AgentTrace(provider="codex", model=model_hint)
    pending: dict[str, dict[str, Any]] = {}
    completed: dict[str, dict[str, Any]] = {}
    final_text: list[str] = []
    last_total_usage: dict[str, Any] | None = None
    for event in events:
        etype = event.get("type")
        if etype == "thread.started":
            trace.session_id = event.get("thread_id") or trace.session_id
        elif etype == "session_meta":
            payload = event.get("payload") or {}
            if isinstance(payload, Mapping):
                trace.session_id = payload.get("id") or trace.session_id
                trace.version = payload.get("cli_version") or trace.version
                trace.model = payload.get("model") or trace.model
        elif etype == "turn_context":
            payload = event.get("payload") or {}
            if isinstance(payload, Mapping):
                trace.model = payload.get("model") or trace.model
        elif etype == "turn.completed":
            usage = event.get("usage")
            if isinstance(usage, Mapping) and _usage_is_present(usage):
                last_total_usage = dict(usage)
        elif etype == "event_msg":
            payload = event.get("payload") or {}
            if isinstance(payload, Mapping) and payload.get("type") == "token_count":
                info = payload.get("info") or {}
                if isinstance(info, Mapping):
                    usage = info.get("total_token_usage")
                    if isinstance(usage, Mapping):
                        last_total_usage = dict(usage)
                        if info.get("total_cost") is not None:
                            trace.extra["total_cost_usd"] = info.get("total_cost")
        elif etype == "response_item":
            item = event.get("payload") or {}
            if not isinstance(item, Mapping):
                continue
            kind = item.get("type")
            if kind == "message":
                content = item.get("content", [])
                text = _text_from_content(content)[0]
                if text:
                    final_text.append(text)
                step = {
                    "step_id": 0,
                    "timestamp": event.get("timestamp"),
                    "source": "agent" if item.get("role") == "assistant" else "user",
                    "message": text,
                    "model_name": trace.model,
                }
                trace.steps.append(step)
            elif kind in {"function_call", "custom_tool_call"}:
                call_id = str(item.get("call_id") or item.get("id") or "")
                raw_args = item.get("arguments", item.get("input"))
                try:
                    args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                except json.JSONDecodeError:
                    args = {"input": raw_args}
                if not isinstance(args, Mapping):
                    args = {"value": args}
                pending[call_id] = {
                    "call_id": call_id,
                    "tool_name": item.get("name") or kind,
                    "arguments": dict(args),
                    "argument_sha256": _sha(raw_args),
                    "output": None,
                    "output_sha256": None,
                    "status": item.get("status"),
                    "timestamp": event.get("timestamp"),
                    "duration_s": None,
                }
            elif kind in {"function_call_output", "custom_tool_call_output"}:
                call_id = str(item.get("call_id") or "")
                call = pending.pop(call_id, None) or {
                    "call_id": call_id,
                    "tool_name": item.get("name") or kind,
                    "arguments": {},
                    "argument_sha256": None,
                    "timestamp": event.get("timestamp"),
                }
                output = item.get("output")
                call["output"] = output
                call["output_sha256"] = _sha(output)
                call["duration_s"] = _duration(call.get("timestamp"), event.get("timestamp"))
                completed[call_id] = call
                trace.tool_calls.append(call)
                trace.steps.append(
                    {
                        "step_id": 0,
                        "timestamp": call.get("timestamp") or event.get("timestamp"),
                        "source": "agent",
                        "message": "",
                        "model_name": trace.model,
                        "tool_calls": [
                            {
                                "tool_call_id": call_id,
                                "function_name": call.get("tool_name") or kind,
                                "arguments": call.get("arguments", {}),
                                "extra": {
                                    "raw_arguments_sha256": call.get("argument_sha256")
                                },
                            }
                        ],
                        "observation": _observation(call_id, output),
                    }
                )
            else:
                step, call = _codex_item_step(item, event.get("timestamp"), trace.model)
                if step:
                    trace.steps.append(step)
                    if call:
                        completed[call.get("call_id", "")] = call
                        if call.get("output"):
                            final_text.append(_string(call["output"]))
        elif etype in {"item.completed", "item.started"}:
            item = event.get("item") or {}
            if not isinstance(item, Mapping):
                continue
            item_id = str(item.get("id") or "")
            # Keep the completed item as the semantic step.  item.started is
            # retained in raw JSONL but does not duplicate the trajectory.
            if etype == "item.completed":
                step, call = _codex_item_step(item, event.get("timestamp"), trace.model)
                if step:
                    trace.steps.append(step)
                    if call:
                        if item_id in pending:
                            call["duration_s"] = _duration(pending[item_id].get("timestamp"), event.get("timestamp"))
                        completed[item_id] = call
                        trace.tool_calls.append(call)
                    elif step.get("message"):
                        final_text.append(step["message"])
            elif item_id and item.get("type") in {"command_execution", "function_call", "custom_tool_call", "mcp_tool_call"}:
                pending[item_id] = {"timestamp": event.get("timestamp")}
        elif etype in {"error", "turn.failed"}:
            trace.extra["error"] = event.get("message") or event.get("error")

    # Current Codex (0.16x) reports cumulative usage in turn.completed; older
    # releases report the same shape in event_msg/token_count. Prefer that
    # authoritative total over summing intermediate deltas.
    if last_total_usage:
        trace.usage = normalize_usage(last_total_usage)
        trace.usage_source = "provider"
    trace.text = "\n\n".join(text for text in final_text if text).strip()
    trace.steps = [dict(step, step_id=index) for index, step in enumerate(trace.steps, 1)]
    # A command may be represented by both response_item and item.completed in
    # mixed CLI versions; retain one tool record per call id.
    unique: dict[str, dict[str, Any]] = {}
    for call in trace.tool_calls:
        call_id = str(call.get("call_id") or len(unique))
        unique[call_id] = call
    for call_id, pending_call in pending.items():
        if call_id in unique:
            continue
        unique[call_id] = {
            "call_id": call_id,
            "tool_name": pending_call.get("tool_name") or "unknown",
            "arguments": pending_call.get("arguments", {}),
            "argument_sha256": pending_call.get("argument_sha256"),
            "output": None,
            "output_sha256": None,
            "status": "in_progress",
            "timestamp": pending_call.get("timestamp"),
            "duration_s": None,
        }
    trace.tool_calls = list(unique.values())
    return trace


def _parse_claude(events: list[dict[str, Any]], *, model_hint: str | None) -> AgentTrace:
    trace = AgentTrace(provider="claude", model=model_hint)
    pending: dict[str, dict[str, Any]] = {}
    latest_usage_by_message: dict[str, Mapping[str, Any]] = {}
    final_result_usage: Mapping[str, Any] | None = None
    final_text: list[str] = []
    seen_assistant_messages: set[str] = set()
    for event in events:
        etype = event.get("type")
        if etype == "system":
            trace.session_id = event.get("session_id") or event.get("sessionId") or trace.session_id
            trace.version = event.get("version") or trace.version
            trace.model = event.get("model") or trace.model
            if event.get("subtype") == "init" and isinstance(event.get("tools"), list):
                trace.extra["tool_definitions"] = len(event["tools"])
        elif etype == "assistant":
            message = event.get("message") or {}
            if not isinstance(message, Mapping):
                continue
            msg_id = str(message.get("id") or event.get("uuid") or "")
            usage = message.get("usage")
            if isinstance(usage, Mapping) and _usage_is_present(usage) and msg_id:
                latest_usage_by_message[msg_id] = usage
            trace.model = message.get("model") or trace.model
            text, reasoning, tools = _text_from_content(message.get("content"))
            # Partial Claude events can repeat a message id. Preserve one
            # semantic ATIF step while the raw stream remains lossless.
            if msg_id and msg_id in seen_assistant_messages:
                continue
            if msg_id:
                seen_assistant_messages.add(msg_id)
            calls: list[dict[str, Any]] = []
            for block in tools:
                call_id = str(block.get("id") or block.get("tool_use_id") or "")
                args = block.get("input", {})
                call = {
                    "call_id": call_id,
                    "tool_name": block.get("name") or "",
                    "arguments": args if isinstance(args, Mapping) else {"value": args},
                    "argument_sha256": _sha(args),
                    "output": None,
                    "output_sha256": None,
                    "status": None,
                    "timestamp": event.get("timestamp"),
                    "duration_s": None,
                }
                pending[call_id] = call
                calls.append(call)
                trace.tool_calls.append(call)
            if text:
                final_text.append(text)
            step: dict[str, Any] = {
                "step_id": 0,
                "timestamp": event.get("timestamp"),
                "source": "agent",
                "message": text,
                "model_name": trace.model,
            }
            if reasoning:
                step["reasoning_content"] = reasoning
            if calls:
                step["tool_calls"] = [
                    {
                        "tool_call_id": call["call_id"],
                        "function_name": call["tool_name"],
                        "arguments": call["arguments"],
                        "extra": {"raw_arguments_sha256": call["argument_sha256"]},
                    }
                    for call in calls
                ]
            trace.steps.append(step)
        elif etype == "user":
            message = event.get("message") or {}
            if not isinstance(message, Mapping):
                continue
            content = message.get("content")
            if isinstance(content, str):
                if content.strip():
                    trace.steps.append({
                        "step_id": 0,
                        "timestamp": event.get("timestamp"),
                        "source": "user",
                        "message": content,
                    })
            elif isinstance(content, list):
                user_text: list[str] = []
                for block in content:
                    if not isinstance(block, Mapping):
                        user_text.append(_string(block))
                        continue
                    if block.get("type") == "tool_result":
                        call_id = str(block.get("tool_use_id") or "")
                        call = pending.pop(call_id, None)
                        output = block.get("content")
                        if call is None:
                            call = {
                                "call_id": call_id,
                                "tool_name": block.get("name") or "",
                                "arguments": {},
                                "argument_sha256": None,
                                "timestamp": event.get("timestamp"),
                                "duration_s": None,
                            }
                            trace.tool_calls.append(call)
                        call["output"] = output
                        call["output_sha256"] = _sha(output)
                        call["status"] = "error" if block.get("is_error") else "completed"
                        call["duration_s"] = _duration(call.get("timestamp"), event.get("timestamp"))
                        continue
                    if block.get("type") == "text" and isinstance(block.get("text"), str):
                        user_text.append(block["text"])
                    else:
                        user_text.append(_string(block))
                if user_text:
                    trace.steps.append({
                        "step_id": 0,
                        "timestamp": event.get("timestamp"),
                        "source": "user",
                        "message": "\n\n".join(user_text),
                    })
        elif etype == "result":
            trace.session_id = event.get("session_id") or event.get("sessionId") or trace.session_id
            trace.model = event.get("model") or trace.model
            if event.get("subtype") not in (None, "success"):
                trace.extra["error"] = event.get("error") or event.get("subtype")
            if isinstance(event.get("usage"), Mapping):
                final_result_usage = event["usage"]
            if event.get("total_cost_usd") is not None:
                trace.extra["total_cost_usd"] = event.get("total_cost_usd")
            result_text = event.get("result")
            if isinstance(result_text, str) and result_text.strip():
                final_text.append(result_text)

    if final_result_usage is not None:
        trace.usage = normalize_usage(final_result_usage)
        # Anthropic's final result usage may expose cache creation separately;
        # retain it in the trajectory while cached_input_tokens means reads.
        for key in ("cache_creation_input_tokens", "cache_read_input_tokens"):
            if key in final_result_usage:
                trace.extra[key] = final_result_usage[key]
        trace.usage_source = "provider"
    elif latest_usage_by_message:
        aggregate = empty_usage()
        for usage in latest_usage_by_message.values():
            _merge_usage(aggregate, usage)
            if "cache_creation_input_tokens" in usage:
                trace.extra["cache_creation_input_tokens"] = trace.extra.get("cache_creation_input_tokens", 0) + int(usage.get("cache_creation_input_tokens") or 0)
        trace.usage = aggregate
        trace.usage_source = "provider"
    trace.text = "\n\n".join(text for text in final_text if text).strip()
    by_call = {str(call.get("call_id")): call for call in trace.tool_calls}
    for step in trace.steps:
        calls = step.get("tool_calls")
        if not isinstance(calls, list):
            continue
        results = []
        for spec in calls:
            if not isinstance(spec, Mapping):
                continue
            call = by_call.get(str(spec.get("tool_call_id") or ""))
            if call and call.get("output") is not None:
                results.append(
                    {
                        "source_call_id": call.get("call_id"),
                        "content": _string(call.get("output")),
                    }
                )
        if results:
            step["observation"] = {"results": results}
    trace.steps = [dict(step, step_id=index) for index, step in enumerate(trace.steps, 1)]
    return trace


def parse_stream(provider: str, raw: str, *, model_hint: str | None = None) -> AgentTrace:
    """Parse a CLI JSONL stream; non-JSON lines remain counted as malformed."""

    events: list[dict[str, Any]] = []
    malformed = 0
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            malformed += 1
            continue
        if isinstance(value, dict):
            events.append(value)
        else:
            malformed += 1
    trace = _parse_codex(events, model_hint=model_hint) if provider == "codex" else _parse_claude(events, model_hint=model_hint)
    trace.json_events = len(events)
    trace.malformed_lines = malformed
    return trace
