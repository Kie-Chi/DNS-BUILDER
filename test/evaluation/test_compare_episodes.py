from __future__ import annotations

import json

import pytest

from scripts.evaluation.compare_episodes import compare


def write_episode(root, condition: str, *, total_tokens: int | None) -> None:
    root.mkdir()
    (root / "artifacts").mkdir()
    run = {
        "run_id": f"run-{condition}",
        "task_id": "tsuking",
        "condition": condition,
        "status": "partial",
        "wall_seconds": 10 if condition == "dns-builder" else 12,
        "model_latency_seconds": 8,
        "tool_seconds": 2,
        "model_input_tokens": total_tokens,
        "model_output_tokens": 4,
        "model_reasoning_tokens": None,
        "cached_input_tokens": None,
        "model_total_tokens": total_tokens,
        "model_calls": 1,
        "tool_calls": 2,
        "agent_events": 3,
        "agent_tool_calls": 0,
        "retries": 0,
        "acceptance": {"build": {"status": "pass"}},
    }
    (root / "summary.json").write_text(json.dumps({"runs": [run]}))
    (root / "run.json").write_text(
        json.dumps({
            "pdf_sha256": "pdf",
            "material_policy": "generic-only-v1",
            "runner_version": "6",
            "provider": "agent",
        })
    )
    (root / "artifacts" / "episode-manifest.json").write_text(
        json.dumps({"file_count": 3, "files": []})
    )
    (root / "artifacts" / "reproducibility.json").write_text(
        json.dumps({"semantic_match": True})
    )


def test_compare_preserves_missing_usage_and_computes_delta(tmp_path) -> None:
    skill = tmp_path / "skill"
    blank = tmp_path / "blank"
    write_episode(skill, "dns-builder", total_tokens=20)
    write_episode(blank, "blank", total_tokens=None)

    result = compare(skill, blank)

    assert result["pdf_sha256"] == {"dns_builder": "pdf", "blank": "pdf"}
    assert result["delta_dns_builder_minus_blank"]["wall_seconds"] == -2
    assert result["metrics"]["model_total_tokens"] == {
        "dns_builder": 20,
        "blank": None,
    }
    assert result["delta_dns_builder_minus_blank"]["model_total_tokens"] is None
    assert result["feasibility"] == {
        "dns_builder": "not_accepted",
        "blank": "pending_review",
    }
    assert result["fairness"]["eligible"] is False


def test_compare_marks_paired_react_gate(tmp_path) -> None:
    skill = tmp_path / "skill"
    blank = tmp_path / "blank"
    write_episode(skill, "dns-builder", total_tokens=20)
    write_episode(blank, "blank", total_tokens=21)
    for root in (skill, blank):
        summary = json.loads((root / "summary.json").read_text())
        summary["runs"][0]["status"] = "success"
        summary["runs"][0]["acceptance"].update(
            {
                "model-react": {"status": "pass"},
                "model-verification": {"status": "pass"},
            }
        )
        if root is blank:
            summary["runs"][0]["human_review_status"] = "feasible"
        else:
            summary["runs"][0]["acceptance"].update({
                "runtime": {"status": "pass"},
                "reproducibility": {"status": "pass"},
            })
        (root / "summary.json").write_text(json.dumps(summary))
    result = compare(skill, blank)
    assert result["fairness"]["eligible"] is True
    assert result["fairness"]["material_eligible"] is True


def test_compare_keeps_legacy_answer_assisted_pair_diagnostic(tmp_path) -> None:
    skill = tmp_path / "skill"
    blank = tmp_path / "blank"
    write_episode(skill, "dns-builder", total_tokens=20)
    write_episode(blank, "blank", total_tokens=21)
    for root in (skill, blank):
        summary = json.loads((root / "summary.json").read_text())
        run = summary["runs"][0]
        run["status"] = "success"
        run["acceptance"].update(
            {
                "model-react": {"status": "pass"},
                "model-verification": {"status": "pass"},
            }
        )
        if root is blank:
            run["human_review_status"] = "feasible"
        else:
            run["acceptance"].update({
                "runtime": {"status": "pass"},
                "reproducibility": {"status": "pass"},
            })
        (root / "summary.json").write_text(json.dumps(summary))
    (skill / "run.json").write_text(json.dumps({"pdf_sha256": "pdf"}))

    result = compare(skill, blank)

    assert result["fairness"]["model_gate_eligible"] is True
    assert result["fairness"]["eligible"] is False
    assert result["fairness"]["material_eligible"] is False
    assert result["true_success"]["dns_builder"] is False
    assert result["true_success"]["pair"] is False
    assert "material provenance" in result["fairness"]["detail"]


def test_compare_requires_independent_runtime_for_pair(tmp_path) -> None:
    skill = tmp_path / "skill"
    blank = tmp_path / "blank"
    write_episode(skill, "dns-builder", total_tokens=20)
    write_episode(blank, "blank", total_tokens=21)
    for root in (skill, blank):
        summary = json.loads((root / "summary.json").read_text())
        run = summary["runs"][0]
        run["status"] = "success"
        run["acceptance"].update({
            "model-react": {"status": "pass"},
            "model-verification": {"status": "pass"},
        })
        if root is blank:
            run["human_review_status"] = "feasible"
        else:
            run["acceptance"].update({
                "runtime": {"status": "not_run"},
                "reproducibility": {"status": "pass"},
            })
        (root / "summary.json").write_text(json.dumps(summary))

    result = compare(skill, blank)

    assert result["fairness"]["model_gate_eligible"] is True
    assert result["fairness"]["material_eligible"] is True
    assert result["fairness"]["eligible"] is False
    assert result["true_success"]["pair"] is False


def test_compare_keeps_legacy_finalized_blank_readable(tmp_path) -> None:
    skill = tmp_path / "skill"
    blank = tmp_path / "blank"
    write_episode(skill, "dns-builder", total_tokens=20)
    write_episode(blank, "blank", total_tokens=21)
    (blank / "run.json").write_text(json.dumps({"pdf_sha256": "pdf"}))
    summary = json.loads((blank / "summary.json").read_text())
    summary["runs"][0].update({"status": "success", "human_review_status": "feasible"})
    (blank / "summary.json").write_text(json.dumps(summary))

    result = compare(skill, blank)

    assert result["fairness"]["material_eligible"] is False
    assert result["fairness"]["eligible"] is False
    assert result["true_success"]["blank"] is False


def test_compare_rejects_new_blank_finalized_without_model_gates(tmp_path) -> None:
    skill = tmp_path / "skill"
    blank = tmp_path / "blank"
    write_episode(skill, "dns-builder", total_tokens=20)
    write_episode(blank, "blank", total_tokens=21)
    summary = json.loads((blank / "summary.json").read_text())
    summary["runs"][0].update({"status": "success", "human_review_status": "feasible"})
    (blank / "summary.json").write_text(json.dumps(summary))

    with pytest.raises(ValueError, match="human-finalized"):
        compare(skill, blank)


def test_compare_rejects_pre_boundary_fix_runner(tmp_path) -> None:
    skill = tmp_path / "skill"
    blank = tmp_path / "blank"
    write_episode(skill, "dns-builder", total_tokens=20)
    write_episode(blank, "blank", total_tokens=21)
    metadata = json.loads((skill / "run.json").read_text())
    metadata["runner_version"] = "5"
    (skill / "run.json").write_text(json.dumps(metadata))

    result = compare(skill, blank)

    assert result["fairness"]["material_eligible"] is False
    assert result["fairness"]["eligible"] is False


def test_compare_never_counts_fixture_as_true_success(tmp_path) -> None:
    skill = tmp_path / "skill"
    blank = tmp_path / "blank"
    write_episode(skill, "dns-builder", total_tokens=None)
    write_episode(blank, "blank", total_tokens=21)
    summary = json.loads((skill / "summary.json").read_text())
    summary["runs"][0]["status"] = "success"
    summary["runs"][0]["acceptance"].update({
        "model-react": {"status": "pass"},
        "model-verification": {"status": "pass"},
        "runtime": {"status": "pass"},
        "reproducibility": {"status": "pass"},
    })
    (skill / "summary.json").write_text(json.dumps(summary))
    metadata = json.loads((skill / "run.json").read_text())
    metadata["provider"] = "fixture"
    (skill / "run.json").write_text(json.dumps(metadata))

    result = compare(skill, blank)

    assert result["fairness"]["material_eligible"] is False
    assert result["true_success"]["dns_builder"] is False
    assert result["true_success"]["pair"] is False
