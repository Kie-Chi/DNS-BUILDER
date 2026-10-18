from pathlib import Path

from scripts.evaluation.dnsb_agent_runner import validate_agent_workspace


def test_blank_workspace_rejects_cross_episode_image(tmp_path: Path) -> None:
    (tmp_path / "compose.yaml").write_text(
        "services:\n  resolver:\n    image: dnsb-blank-agent-old123-focal:latest\n",
        encoding="utf-8",
    )
    (tmp_path / "verify.sh").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (tmp_path / "verification-report.json").write_text(
        '{"status":"pass","checks":[{"name":"x","status":"pass","command":["true"]}]}\n',
        encoding="utf-8",
    )

    ok, checks = validate_agent_workspace(
        tmp_path,
        None,
        require_config=False,
        require_verification=True,
        reject_temporary_images=True,
    )

    assert not ok
    image_check = next(item for item in checks if item["name"] == "self-contained-image-references")
    assert image_check["status"] == "fail"
    assert image_check["references"][0]["path"] == "compose.yaml"


def test_dns_builder_workspace_keeps_image_check_informational(tmp_path: Path) -> None:
    (tmp_path / "main.yml").write_text("project: demo\n", encoding="utf-8")
    ok, checks = validate_agent_workspace(tmp_path, "main.yml", reject_temporary_images=False)

    assert ok
    image_check = next(item for item in checks if item["name"] == "self-contained-image-references")
    assert image_check["status"] == "pass"
