#!/usr/bin/env python3
"""Compare a DNS-BUILDER episode with a blank-information baseline.

The runner intentionally writes one immutable directory per episode.  This
small post-processing command joins a ``dns-builder`` episode with a matching
``blank`` episode without rereading provider logs or estimating tokens. It
keeps missing usage as ``null`` and reports numeric deltas as
``dns-builder - blank``.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


REQUIRED_MATERIAL_POLICY = "generic-only-v1"
MINIMUM_RUNNER_VERSION = 6

NUMERIC_FIELDS = (
    "wall_seconds",
    "end_to_end_seconds",
    "model_latency_seconds",
    "tool_seconds",
    "model_verification_seconds",
    "human_seconds",
    "cost_usd",
    "model_input_tokens",
    "model_output_tokens",
    "model_reasoning_tokens",
    "cached_input_tokens",
    "model_total_tokens",
    "model_calls",
    "tool_calls",
    "agent_events",
    "agent_turns",
    "agent_tool_calls",
    "react_tool_calls",
    "retries",
)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _load_episode(path: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    summary = _read_json(path / "summary.json")
    runs = summary.get("runs")
    if not isinstance(runs, list) or len(runs) != 1 or not isinstance(runs[0], dict):
        raise ValueError(f"summary must contain exactly one run: {path / 'summary.json'}")
    run = runs[0]
    manifest_path = path / "artifacts" / "episode-manifest.json"
    manifest = _read_json(manifest_path) if manifest_path.is_file() else {}
    reproducibility_path = path / "artifacts" / "reproducibility.json"
    reproducibility = _read_json(reproducibility_path) if reproducibility_path.is_file() else {}
    return run, manifest, reproducibility


def _stage_status(run: dict[str, Any], stage: str) -> str | None:
    acceptance = run.get("acceptance")
    if not isinstance(acceptance, dict):
        return None
    value = acceptance.get(stage)
    return value.get("status") if isinstance(value, dict) else None


def _stage_checks(run: dict[str, Any], stage: str) -> list[dict[str, Any]]:
    acceptance = run.get("acceptance")
    if not isinstance(acceptance, dict):
        return []
    value = acceptance.get(stage)
    checks = value.get("checks") if isinstance(value, dict) else None
    return [item for item in checks if isinstance(item, dict)] if isinstance(checks, list) else []


def _check_by_name(checks: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    for check in checks:
        if check.get("name") == name:
            return check
    return None


def _verification_report(path: Path) -> dict[str, Any]:
    """Read the model-owned report when an episode has one.

    Blank projects do not go through DNS-BUILDER's structural/runtime gates,
    so their only attack evidence may be the report produced by the model's
    own verifier.  Missing or malformed reports stay explicit as ``None``.
    """

    candidates = (
        path / "project" / "verification-report.json",
        path / "project" / "verification_report.json",
        path / "artifacts" / "model-verification-report-attempt-001.json",
    )
    for candidate in candidates:
        if not candidate.is_file():
            continue
        try:
            value = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            return value
    return {}


def _compose_services(episode: Path) -> list[str]:
    """Extract top-level service names without requiring PyYAML.

    Generated Compose files are ordinary YAML and service names are the only
    keys at exactly two spaces below ``services``.  This small parser keeps
    the comparison CLI dependency-free and is deliberately conservative.
    """

    candidates = [
        episode / "project" / "docker-compose.yml",
        episode / "project" / "compose.yaml",
        episode / "project" / "compose.yml",
    ]
    candidates.extend(sorted((episode / "build-1" / "output").glob("*/docker-compose.yml")))
    for candidate in candidates:
        if not candidate.is_file():
            continue
        names: list[str] = []
        in_services = False
        for raw in candidate.read_text(encoding="utf-8", errors="replace").splitlines():
            if raw.strip() == "services:":
                in_services = True
                continue
            if not in_services:
                continue
            match = re.match(r"^  ([A-Za-z0-9_.-]+):(?:\s|$)", raw)
            if match:
                names.append(match.group(1))
                continue
            if raw and not raw.startswith(" "):
                break
        if names:
            return names
    return []


def _report_checks(report: dict[str, Any]) -> list[dict[str, Any]]:
    checks = report.get("checks")
    return [item for item in checks if isinstance(item, dict)] if isinstance(checks, list) else []


def _report_check(report: dict[str, Any], *names: str) -> dict[str, Any] | None:
    checks = _report_checks(report)
    wanted = set(names)
    for check in checks:
        if check.get("name") in wanted:
            return check
    return None


def _last_json_object_from_text(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, str):
        return None
    for line in reversed(value.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _runtime_evidence(run: dict[str, Any], episode: Path) -> dict[str, Any]:
    """Normalize attack/runtime evidence across the two conditions."""

    runtime_checks = _stage_checks(run, "runtime")
    report = _verification_report(episode)
    report_checks = _report_checks(report)
    auth = _check_by_name(runtime_checks, "authoritative-referral")
    chain = _check_by_name(runtime_checks, "resolver-chain")
    path_check = _check_by_name(runtime_checks, "resolver-path")
    services = _check_by_name(runtime_checks, "services-started")
    if auth is None:
        auth = _report_check(report, "authoritative-referral", "auth-referral", "failure_rcode_and_authority")
    if chain is None:
        chain = _report_check(report, "resolver-chain", "chained-answer", "resolver-chain")
    if path_check is None:
        path_check = _report_check(report, "resolver-path", "resolver_path_16_hops", "path-logs")
    if services is None:
        services = _report_check(report, "services-started", "all_services_running")

    auth_metrics = auth.get("metrics") if isinstance(auth, dict) else None
    if not isinstance(auth_metrics, dict):
        auth_metrics = {}
    chain_metrics = chain.get("metrics") if isinstance(chain, dict) else None
    if not isinstance(chain_metrics, dict):
        chain_metrics = {}
    # The TsuKing verifier keeps the raw probe output in its command log even
    # when the task-level acceptance projection omits one field.  Recover the
    # compact JSON metric so comparison artifacts retain the observed RCODE,
    # section counts, bytes, and timeout result.
    commands = report.get("commands") if isinstance(report, dict) else None
    if isinstance(commands, list):
        for command in commands:
            if not isinstance(command, dict):
                continue
            label = str(command.get("label") or "")
            metric = _last_json_object_from_text(command.get("output"))
            if metric is None:
                continue
            if label == "authoritative-referral":
                for key, value in metric.items():
                    auth_metrics.setdefault(key, value)
            elif label == "resolver-chain":
                for key, value in metric.items():
                    chain_metrics.setdefault(key, value)
    if isinstance(chain, dict) and chain.get("detail") and "timeout" in str(chain.get("detail")).lower():
        chain_metrics.setdefault("result", "timeout")

    # A model-owned report can use either the structured runtime shape above
    # or a simple {passed, detail} check.  Preserve both rather than guessing
    # byte counts from prose.
    service_detail = services.get("detail") if isinstance(services, dict) else None
    runtime_labels = {
        key: value
        for key, value in (run.get("tool_seconds_by_label") or {}).items()
        if isinstance(key, str) and key.startswith("runtime-")
    }
    service_names = _compose_services(episode)
    runtime_service_names = [
        name for name in service_names if not name.startswith("dnsb-image-builder-")
    ]
    referral_semantics = (
        auth_metrics.get("rcode") == 0
        and auth_metrics.get("answer_count") == 0
        and isinstance(auth_metrics.get("authority_count"), (int, float))
        and auth_metrics.get("authority_count", 0) >= 1
        and isinstance(auth_metrics.get("additional_count"), (int, float))
        and auth_metrics.get("additional_count", 0) >= auth_metrics.get("authority_count", 0)
    )
    chain_failure = (
        chain_metrics.get("result") == "timeout"
        or (isinstance(chain_metrics.get("rcode"), (int, float)) and chain_metrics.get("rcode") != 0)
    )
    return {
        "runtime_status": _stage_status(run, "runtime"),
        "service_count": len(runtime_service_names) or None,
        "service_names": runtime_service_names or None,
        "compose_service_count": len(service_names) or None,
        "services_detail": service_detail,
        "authoritative_referral": {
            "status": auth.get("status") if isinstance(auth, dict) else None,
            "metrics": auth_metrics or None,
        },
        "resolver_chain": {
            "status": chain.get("status") if isinstance(chain, dict) else None,
            "metrics": chain_metrics or None,
        },
        "resolver_path": {
            "status": path_check.get("status") if isinstance(path_check, dict) else None,
            "detail": path_check.get("detail") if isinstance(path_check, dict) else None,
        },
        "runtime_tool_seconds_by_label": runtime_labels,
        "paper_semantics": {
            "authoritative_referral_shape": bool(referral_semantics),
            "resolver_chain_failure": bool(chain_failure),
            "evidence_source": "runner-runtime" if _stage_status(run, "runtime") else ("model-verification-report" if report else None),
        },
        "verification_report_status": report.get("status") if report else None,
        "verification_check_count": len(report_checks) if report else 0,
    }


def _runtime_metric_objects(run: dict[str, Any], episode: Path) -> list[dict[str, Any]]:
    """Collect structured metrics without interpreting prose as measurements."""

    objects: list[dict[str, Any]] = []
    for check in _stage_checks(run, "runtime"):
        metrics = check.get("metrics")
        if isinstance(metrics, dict):
            objects.append(metrics)
    report = _verification_report(episode)
    metrics = report.get("metrics") if isinstance(report, dict) else None
    if isinstance(metrics, dict):
        objects.append(metrics)
    for check in _report_checks(report):
        metrics = check.get("metrics")
        if isinstance(metrics, dict):
            objects.append(metrics)
    return objects


def _first(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return None


def _attack_performance(run: dict[str, Any], episode: Path) -> dict[str, Any]:
    """Normalize task-specific attack observations for cross-condition reports."""

    task_id = str(run.get("task_id") or "")
    objects = _runtime_metric_objects(run, episode)
    flat: dict[str, Any] = {}
    for obj in objects:
        for key, value in obj.items():
            if key not in flat:
                flat[key] = value
    # The client probes intentionally nest endpoint observations.  Preserve
    # their complete JSON under ``raw`` while exposing comparable scalars.
    if task_id == "camp-ddfo":
        camp = next((obj for obj in objects if "primary_trigger" in obj), {})
        primary = camp.get("primary_trigger") if isinstance(camp.get("primary_trigger"), dict) else {}
        resolver = camp.get("resolver_trigger") if isinstance(camp.get("resolver_trigger"), dict) else {}
        probes = camp.get("delegation_probes") if isinstance(camp.get("delegation_probes"), list) else []
        return {
            "attack": "CAMP-DD-FO",
            "delegation_depth": _first(camp, "delegation_depth_expected") or len(probes) or None,
            "fanout_width": _first(camp, "fanout_width_expected"),
            "delegation_probe_count": len(probes) or None,
            # A deep-delegation probe is successful when it returns a valid
            # NOERROR authority referral.  The answer section is normally
            # empty because the queried name is below the delegated zone;
            # counting only answer records would report a passing CAMP chain
            # as zero successful probes.
            "delegation_probe_successes": sum(
                1
                for item in probes
                if isinstance(item, dict)
                and item.get("authority_count", 0) >= 1
                and item.get("rcode") == 0
                and not item.get("timeout")
            ),
            "primary_response_bytes": primary.get("response_bytes"),
            "primary_amplification_factor": primary.get("amplification_factor"),
            "resolver_latency_ms": resolver.get("latency_ms"),
            "resolver_rcode": resolver.get("rcode"),
            "resolver_timeout": resolver.get("timeout"),
            "raw": camp or flat or None,
        }
    if task_id == "keytrap":
        report = _verification_report(episode)
        payload_count = report.get("dnssec_payload_records") if isinstance(report, dict) else None
        metric = next((obj for obj in objects if "latency_ms" in obj or "timeout" in obj), flat)
        return {
            "attack": "KeyTrap",
            "dnssec_payload_records": payload_count,
            "dnssec_payload_present": isinstance(payload_count, (int, float)) and payload_count >= 2,
            "validation_latency_ms": metric.get("latency_ms"),
            "resolver_rcode": metric.get("rcode"),
            "resolver_timeout": metric.get("timeout"),
            "query_bytes": metric.get("query_bytes"),
            "response_bytes": metric.get("response_bytes"),
            "raw": metric or flat or None,
        }
    if task_id == "nxns":
        nxns = next((obj for obj in objects if "authoritative" in obj), {})
        auth = nxns.get("authoritative") if isinstance(nxns.get("authoritative"), dict) else {}
        resolver = nxns.get("resolver") if isinstance(nxns.get("resolver"), dict) else {}
        return {
            "attack": "NXNS",
            "authority_ns_count": auth.get("authority_count"),
            "authority_query_bytes": auth.get("query_bytes"),
            "authority_response_bytes": auth.get("response_bytes"),
            "authority_amplification_factor": (
                auth.get("response_bytes") / auth.get("query_bytes")
                if isinstance(auth.get("response_bytes"), (int, float))
                and isinstance(auth.get("query_bytes"), (int, float))
                and auth.get("query_bytes")
                else None
            ),
            "resolver_query_bytes": resolver.get("query_bytes"),
            "resolver_response_bytes": resolver.get("response_bytes"),
            "resolver_latency_ms": resolver.get("latency_ms"),
            "resolver_rcode": resolver.get("rcode"),
            "resolver_timeout": resolver.get("timeout"),
            "raw": nxns or flat or None,
        }
    # TsuKing and future tasks retain the generic runtime projection.
    return _runtime_evidence(run, episode)


def _true_success(run: dict[str, Any], *, condition: str) -> bool:
    """Require the full gate set before counting a reproduction as real."""

    if run.get("status") != "success":
        return False
    if _stage_status(run, "model-react") != "pass" or _stage_status(run, "model-verification") != "pass":
        return False
    if condition == "dns-builder":
        return (
            _stage_status(run, "build") == "pass"
            and _stage_status(run, "runtime") == "pass"
            and _stage_status(run, "reproducibility") == "pass"
        )
    return run.get("human_review_status") == "feasible"


def _failure_reason(episode: Path, run: dict[str, Any]) -> str | None:
    """Return an auditable reason for a non-success episode.

    Comparison numbers remain useful as diagnostics, but a failed blank run
    must not look like a cheap successful baseline.  Prefer the explicit
    human-review note, then the runner's terminal error, then the first
    failed acceptance stage so reports can explain why the sample is excluded.
    """

    review_path = episode / "artifacts" / "human-review.json"
    if review_path.is_file():
        try:
            review = _read_json(review_path)
        except (OSError, ValueError):
            review = {}
        notes = review.get("notes")
        if isinstance(notes, str) and notes.strip():
            return notes.strip()
    events_path = episode / "events.jsonl"
    if events_path.is_file():
        try:
            events = [
                json.loads(line)
                for line in events_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        except (OSError, json.JSONDecodeError):
            events = []
        for event in reversed(events):
            if isinstance(event, dict) and event.get("event") == "runner_error":
                error = event.get("error")
                if isinstance(error, str) and error.strip():
                    return error.strip()
    acceptance = run.get("acceptance")
    if isinstance(acceptance, dict):
        for stage, value in reversed(list(acceptance.items())):
            if not isinstance(value, dict) or value.get("status") != "fail":
                continue
            checks = value.get("checks")
            details: list[str] = []
            if isinstance(checks, list):
                for check in checks:
                    if not isinstance(check, dict) or check.get("status") != "fail":
                        continue
                    detail = check.get("detail") or check.get("name")
                    if isinstance(detail, str) and detail:
                        details.append(detail)
            suffix = f": {'; '.join(details)}" if details else ""
            return f"acceptance stage {stage} failed{suffix}"
    status = run.get("status")
    if status not in {None, "success"}:
        return f"episode status={status}"
    return None


def _delta(left: Any, right: Any) -> int | float | None:
    if isinstance(left, bool) or isinstance(right, bool):
        return None
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        value = left - right
        return round(value, 6) if isinstance(value, float) else value
    return None


def _numeric_deltas(left: dict[str, Any], right: dict[str, Any]) -> dict[str, int | float | None]:
    return {
        key: _delta(left.get(key), right.get(key))
        for key in sorted(set(left) & set(right))
        if isinstance(left.get(key), (int, float))
        and not isinstance(left.get(key), bool)
        and isinstance(right.get(key), (int, float))
        and not isinstance(right.get(key), bool)
    }


def _generic_material_run(metadata: dict[str, Any]) -> bool:
    """Reject fixture, legacy, and pre-boundary-fix runs as real results."""

    version = metadata.get("runner_version")
    return (
        metadata.get("material_policy") == REQUIRED_MATERIAL_POLICY
        and metadata.get("provider") in {"agent", "command", "openai"}
        and isinstance(version, (str, int))
        and not isinstance(version, bool)
        and str(version).isdigit()
        and int(version) >= MINIMUM_RUNNER_VERSION
    )


def compare(skill_dir: Path, blank_dir: Path) -> dict[str, Any]:
    skill, skill_manifest, skill_repro = _load_episode(skill_dir)
    blank, blank_manifest, blank_repro = _load_episode(blank_dir)
    if skill.get("condition") != "dns-builder":
        raise ValueError(f"--skill episode is not condition=dns-builder: {skill_dir}")
    if blank.get("condition") != "blank":
        raise ValueError(f"--blank episode is not condition=blank: {blank_dir}")
    if skill.get("task_id") != blank.get("task_id"):
        raise ValueError("episodes must have the same task_id")
    skill_run = _read_json(skill_dir / "run.json") if (skill_dir / "run.json").is_file() else {}
    blank_run = _read_json(blank_dir / "run.json") if (blank_dir / "run.json").is_file() else {}
    skill_model_react = _stage_status(skill, "model-react")
    skill_model_verification = _stage_status(skill, "model-verification")
    blank_model_react = _stage_status(blank, "model-react")
    blank_model_verification = _stage_status(blank, "model-verification")
    model_gate_eligible = all(
        value == "pass"
        for value in (
            skill_model_react,
            skill_model_verification,
            blank_model_react,
            blank_model_verification,
        )
    )
    # The blank condition is only a deliverable when a human has confirmed
    # that the paper semantics are present and the environment is portable.
    # A model-passing generic mock therefore remains diagnostic and cannot
    # make the pair eligible for an efficiency claim.
    # Material provenance is separate from successful tool execution. Legacy
    # answer-assisted runs remain readable but cannot be a generic-only pair.
    material_policies = {
        "dns_builder": skill_run.get("material_policy"),
        "blank": blank_run.get("material_policy"),
    }
    skill_material_eligible = _generic_material_run(skill_run)
    blank_material_eligible = _generic_material_run(blank_run)
    material_eligible = skill_material_eligible and blank_material_eligible
    skill_true = skill_material_eligible and _true_success(skill, condition="dns-builder")
    blank_true = blank_material_eligible and _true_success(blank, condition="blank")
    fairness_eligible = bool(skill_true and blank_true)
    # A reviewed blank episode without the model gate would recreate the old
    # unfair comparison.  Keep pending diagnostic comparisons readable, but
    # refuse to present a human-finalized episode as a valid pair.
    if blank_material_eligible and blank.get("status") == "success" and (
        blank_model_react != "pass"
        or blank_model_verification != "pass"
        or blank.get("human_review_status") != "feasible"
    ):
        raise ValueError(
            "blank episode is human-finalized without passing model-react and model-verification gates"
        )
    metrics: dict[str, Any] = {}
    deltas: dict[str, Any] = {}
    for field in NUMERIC_FIELDS:
        metrics[field] = {"dns_builder": skill.get(field), "blank": blank.get(field)}
        deltas[field] = _delta(skill.get(field), blank.get(field))
    skill_runtime = _runtime_evidence(skill, skill_dir)
    blank_runtime = _runtime_evidence(blank, blank_dir)
    skill_attack = _attack_performance(skill, skill_dir)
    blank_attack = _attack_performance(blank, blank_dir)
    skill_total = skill.get("model_total_tokens")
    blank_total = blank.get("model_total_tokens")
    skill_wall = skill.get("wall_seconds")
    blank_wall = blank.get("wall_seconds")
    relative: dict[str, Any] = {
        "wall_speedup_blank_divided_by_dns_builder": (
            round(blank_wall / skill_wall, 6)
            if isinstance(blank_wall, (int, float)) and isinstance(skill_wall, (int, float)) and skill_wall > 0
            else None
        ),
        "total_token_reduction_fraction": (
            round(1 - skill_total / blank_total, 6)
            if isinstance(blank_total, (int, float)) and isinstance(skill_total, (int, float)) and blank_total > 0
            else None
        ),
        "input_token_reduction_fraction": (
            round(1 - skill.get("model_input_tokens") / blank.get("model_input_tokens"), 6)
            if isinstance(blank.get("model_input_tokens"), (int, float))
            and isinstance(skill.get("model_input_tokens"), (int, float))
            and blank.get("model_input_tokens") > 0
            else None
        ),
    }
    return {
        "schema_version": 2,
        "task_id": skill.get("task_id") or blank.get("task_id"),
        "condition_pair": ["dns-builder", "blank"],
        "episodes": {
            "dns_builder": {"directory": str(skill_dir.resolve()), "run_id": skill.get("run_id")},
            "blank": {"directory": str(blank_dir.resolve()), "run_id": blank.get("run_id")},
        },
        "pdf_sha256": {
            "dns_builder": skill_run.get("pdf_sha256"),
            "blank": blank_run.get("pdf_sha256"),
        },
        "status": {"dns_builder": skill.get("status"), "blank": blank.get("status")},
        "failure_reason": {
            "dns_builder": _failure_reason(skill_dir, skill),
            "blank": _failure_reason(blank_dir, blank),
        },
        "feasibility": {
            "dns_builder": "feasible" if skill.get("status") == "success" else "not_accepted",
            "blank": blank.get("human_review_status") or "pending_review",
        },
        "true_success": {
            "dns_builder": skill_true,
            "blank": blank_true,
            "pair": bool(skill_true and blank_true),
            "definition": {
                "dns_builder": "non-fixture generic-only runner>=6 + success + model ReAct + independent model verification + build + independent runtime + reproducibility",
                "blank": "non-fixture generic-only runner>=6 + success + model ReAct + independent model verification + human feasibility=feasible",
            },
        },
        "diagnostic_success": {
            "dns_builder": bool(skill.get("status") in {"success", "partial"}),
            "blank": bool(
                blank_model_react == "pass" and blank_model_verification == "pass"
            ),
            "detail": "A diagnostic success can have artifacts or a passing local verifier without satisfying the full paper-faithful true-success definition.",
        },
        "metrics": metrics,
        "delta_dns_builder_minus_blank": deltas,
        "cost_reporting": {
            "dns_builder_usd": skill.get("cost_usd"),
            "blank_usd": blank.get("cost_usd"),
            "available": isinstance(skill.get("cost_usd"), (int, float)) and isinstance(blank.get("cost_usd"), (int, float)),
            "reason": (
                "provider usage is present, but no input/output/cached price snapshot was supplied to the runner; "
                "rerun with --input-price, --cached-input-price, and --output-price to compute USD"
            ),
        },
        "relative_efficiency": relative,
        "attack_performance": {
            "task_specific": {
                "dns_builder": skill_attack,
                "blank": blank_attack,
            },
            "dns_builder": skill_runtime,
            "blank": blank_runtime,
            "comparison": {
                "task_specific_numeric_delta_dns_builder_minus_blank": _numeric_deltas(skill_attack, blank_attack),
                "amplification_factor_delta": _delta(
                    (skill_runtime.get("authoritative_referral", {}).get("metrics") or {}).get("amplification_factor"),
                    (blank_runtime.get("authoritative_referral", {}).get("metrics") or {}).get("amplification_factor"),
                ),
                "same_paper_referral_shape": (
                    skill_runtime.get("paper_semantics", {}).get("authoritative_referral_shape")
                    and blank_runtime.get("paper_semantics", {}).get("authoritative_referral_shape")
                ),
                "both_chain_failure": (
                    skill_runtime.get("paper_semantics", {}).get("resolver_chain_failure")
                    and blank_runtime.get("paper_semantics", {}).get("resolver_chain_failure")
                ),
            },
        },
        "acceptance": {
            "dns_builder": skill.get("acceptance", {}),
            "blank": blank.get("acceptance", {}),
        },
        "fairness": {
            "eligible": fairness_eligible,
            "required_stages": [
                "model-react", "model-verification", "human-feasibility=feasible",
                "material-policy=generic-only-v1", "non-fixture-runner>=6",
                "dns-builder:build", "dns-builder:runtime", "dns-builder:reproducibility",
            ],
            "material_policy": material_policies,
            "runner_version": {
                "dns_builder": skill_run.get("runner_version"),
                "blank": blank_run.get("runner_version"),
            },
            "provider": {
                "dns_builder": skill_run.get("provider"),
                "blank": blank_run.get("provider"),
            },
            "material_eligible": material_eligible,
            "statuses": {
                "dns_builder": {
                    "model-react": skill_model_react,
                    "model-verification": skill_model_verification,
                },
                "blank": {
                    "model-react": blank_model_react,
                    "model-verification": blank_model_verification,
                    "human-feasibility": blank.get("human_review_status"),
                },
            },
            "model_gate_eligible": model_gate_eligible,
            "detail": (
                "diagnostic only: material provenance is fixture-only, legacy, missing, or predates the runner boundary fix"
                if not material_eligible
                else (
                    "both conditions passed full success gates and non-fixture generic-only material provenance"
                    if fairness_eligible
                    else "diagnostic only: one or both conditions lack a full success gate or blank human feasibility"
                )
            ),
        },
        "reproducibility": {
            "dns_builder": skill_repro,
            "blank": blank_repro,
        },
        "artifacts": {
            "dns_builder": {
                "file_count": skill_manifest.get("file_count"),
                "manifest_sha256": _sha256(skill_dir / "artifacts" / "episode-manifest.json"),
            },
            "blank": {
                "file_count": blank_manifest.get("file_count"),
                "manifest_sha256": _sha256(blank_dir / "artifacts" / "episode-manifest.json"),
            },
        },
    }


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skill", type=Path, required=True, help="dns-builder episode directory")
    parser.add_argument("--blank", type=Path, required=True, help="blank episode directory")
    parser.add_argument("--out", type=Path, help="write comparison JSON here")
    args = parser.parse_args()
    payload = compare(args.skill.resolve(), args.blank.resolve())
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
