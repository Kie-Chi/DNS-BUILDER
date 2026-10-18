from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.evaluation.dnsb_agent_runner import (
    COMMON_SKILL_FILES,
    GENERIC_REFERENCE_FILES,
    build_prompt,
    read_reference,
    stage_agent_material,
    task_material_paths,
    validate_bundle,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
TASK_FILES = sorted((REPO_ROOT / "scripts/evaluation/tasks").glob("*.json"))


def sentinel_task() -> dict:
    return {
        "task_id": "teaching",
        "title": "Paper-grounded reproduction",
        "instructions": "PUBLIC_REQUIREMENT_FROM_INPUT",
        "dns_builder_instructions": "HIDDEN_ANSWER_INSTRUCTIONS",
        "workspace_material_notice": "HIDDEN_COPY_INSTRUCTIONS",
        "source_project": "scripts/evaluation/fixtures/HIDDEN_PROJECT",
        "config_path": "HIDDEN_CONFIG.yml",
        "expected": {"min_services": 987654321, "required_services": ["HIDDEN_NODE"]},
        "runtime": {"checks": [{"command": ["HIDDEN_TRIGGER"]}]},
        "fixture_config_path": "HIDDEN_FIXTURE_CONFIG.yml",
        "fixture_expected": {"required_services": ["HIDDEN_FIXTURE_NODE"]},
        "fixture_runtime": {"checks": [{"command": ["HIDDEN_FIXTURE_TRIGGER"]}]},
        "human_review": {"criteria": ["HIDDEN_RUBRIC"]},
        "reference_files": ["doc/config/auto.md"],
    }


@pytest.mark.parametrize("condition", ["dns-builder", "blank"])
def test_staged_task_hides_solution_and_acceptance(tmp_path: Path, condition: str) -> None:
    task = sentinel_task()
    material = stage_agent_material(
        tmp_path,
        repo_root=REPO_ROOT,
        task=task,
        pdf_text="Supplied paper evidence\fSecond page",
        condition=condition,
    )

    public = json.loads((material / "task.json").read_text())
    assert public == {key: task[key] for key in ("task_id", "title", "instructions")}
    assert (material / "paper.txt").read_text() == "Supplied paper evidence\fSecond page"
    references = material / "references"
    if condition == "blank":
        assert not references.exists()
    else:
        actual = {
            path.relative_to(references).as_posix()
            for path in references.rglob("*") if path.is_file()
        }
        assert actual == set(task_material_paths(task))
        assert actual.issubset(GENERIC_REFERENCE_FILES)
        for relative in actual:
            assert (references / relative).read_bytes() == (REPO_ROOT / relative).read_bytes()
        assert not any(path.startswith(("examples/", "export/", "scripts/evaluation/fixtures/")) for path in actual)


@pytest.mark.parametrize("condition", ["dns-builder", "blank"])
@pytest.mark.parametrize("workspace_mode", [True, False])
def test_prompt_uses_common_requirement_not_answer_hints(condition: str, workspace_mode: bool) -> None:
    prompt = build_prompt(
        task=sentinel_task(),
        pdf_text="Supplied paper evidence",
        repo_root=REPO_ROOT,
        condition=condition,
        max_pdf_chars=10_000,
        workspace_mode=workspace_mode,
    )

    assert "PUBLIC_REQUIREMENT_FROM_INPUT" in prompt
    assert "HIDDEN_" not in prompt
    assert "987654321" not in prompt
    assert "copy the starter directory" not in prompt
    if condition == "blank":
        assert "===== skills/dns-builder/" not in prompt


@pytest.mark.parametrize("key", ["reference_files", "agent_material_files", "skill_reference_files"])
@pytest.mark.parametrize(
    "path",
    [
        "skills/dns-builder/assets/nxns/main.yml",
        "skills/dns-builder/references/tsuking.md",
        "examples/bugs/camp/camp-dd-fo.yml",
        "scripts/evaluation/fixtures/keytrap/main.yml",
        "export/answer.yaml",
        "evaluation-runs/old/project/main.yml",
        "doc/../../examples/bugs/nxns/main.yml",
        "/tmp/answer.yml",
    ],
)
def test_material_allowlist_fails_closed(key: str, path: str) -> None:
    with pytest.raises(ValueError, match="generic-only allowlist"):
        task_material_paths({key: [path]})


@pytest.mark.parametrize("task_path", TASK_FILES, ids=lambda path: path.stem)
def test_task_definitions_only_reference_generic_material(task_path: Path) -> None:
    task = json.loads(task_path.read_text())
    paths = task_material_paths(task)
    assert set(COMMON_SKILL_FILES).issubset(paths)
    assert set(paths).issubset(GENERIC_REFERENCE_FILES)
    assert task["source_project"] == f"scripts/evaluation/fixtures/{task['task_id']}"
    assert (REPO_ROOT / task["source_project"] / task["fixture_config_path"]).is_file()
    assert not set(task) & {
        "expected", "runtime", "config_path", "independent_runtime",
        "dns_builder_instructions", "workspace_material_notice",
        "agent_material_files", "skill_reference_files",
    }


def test_staging_rejects_allowlisted_symlink_outside_checkout(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    outside = tmp_path / "outside.md"
    outside.write_text("HIDDEN_ANSWER")
    for relative in COMMON_SKILL_FILES:
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("Generic material")
    skill = repo / "skills/dns-builder/SKILL.md"
    skill.unlink()
    skill.symlink_to(outside)

    with pytest.raises(ValueError, match="escapes the repository"):
        stage_agent_material(
            tmp_path / "workspace",
            repo_root=repo,
            task={},
            pdf_text="Paper",
            condition="dns-builder",
        )
    with pytest.raises(ValueError, match="escapes the repository"):
        read_reference(repo, "skills/dns-builder/SKILL.md")


@pytest.mark.parametrize("key", ["reference_files", "agent_material_files", "skill_reference_files"])
@pytest.mark.parametrize("value", ["", False, {}, "doc/config/auto.md"])
def test_material_allowlist_rejects_non_list_values(key: str, value) -> None:
    with pytest.raises(ValueError, match="must be a list"):
        task_material_paths({key: value})


def test_staging_rejects_symlink_to_hidden_file_inside_checkout(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    for relative in COMMON_SKILL_FILES:
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("Generic material")
    hidden = repo / "scripts/evaluation/fixtures/answer.txt"
    hidden.parent.mkdir(parents=True)
    hidden.write_text("HIDDEN_ANSWER")
    skill = repo / "skills/dns-builder/SKILL.md"
    skill.unlink()
    skill.symlink_to(hidden)

    with pytest.raises(ValueError, match="symlink alias"):
        read_reference(repo, "skills/dns-builder/SKILL.md")
    with pytest.raises(ValueError, match="symlink alias"):
        stage_agent_material(
            tmp_path / "workspace", repo_root=repo, task={},
            pdf_text="Paper", condition="dns-builder",
        )


@pytest.mark.parametrize("condition", ["dns-builder", "blank"])
def test_bundle_prompt_contains_valid_json_contract(condition: str) -> None:
    prompt = build_prompt(
        task=sentinel_task(), pdf_text="Paper", repo_root=REPO_ROOT,
        condition=condition, max_pdf_chars=10_000,
    )
    contract = prompt.split("The object must have this shape:\n", 1)[1].split("\n\nThe files map", 1)[0]
    assert json.loads(contract)["verify_path"] == "verify.sh"
    assert "mandatory verifier and passing" not in prompt


def test_model_bundle_does_not_inherit_hidden_config_filename() -> None:
    config_path, files, _verify_path, _notes = validate_bundle(
        {"files": {"main.yml": "name: teaching\n"}}, sentinel_task(),
    )
    assert config_path == "main.yml"
    assert set(files) == {"main.yml"}
