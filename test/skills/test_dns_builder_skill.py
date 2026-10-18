from __future__ import annotations

import asyncio
import copy
import importlib.util
import json
import os
import re
import shutil
import socketserver
import sqlite3
import struct
import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import dns.dnssec
import dns.flags
import dns.message
import dns.name
import dns.query
import dns.rdata
import dns.rdatatype
import dns.zone
import pytest
import yaml

from dnsbuilder.builder import Builder
from dnsbuilder.config import Config
from dnsbuilder.io import DNSBPath, create_app_fs
from dnsbuilder.registry import initialize_registries
from dnsbuilder.utils.merge import deep_merge


REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = REPO_ROOT / "skills/dns-builder"


def yaml_blocks(name: str) -> list[dict]:
    text = (SKILL_ROOT / "references" / name).read_text()
    return [yaml.safe_load(block) for block in re.findall(r"```yaml\n(.*?)\n```", text, flags=re.S)]


def python_function(document: str, name: str):
    source = (SKILL_ROOT / "references" / document).read_text()
    blocks = re.findall(r"```python\n(.*?)\n```", source, flags=re.S)
    matches = [block for block in blocks if re.search(rf"^def {re.escape(name)}\(", block, flags=re.M)]
    assert len(matches) == 1, (document, name)
    namespace = {}
    exec(compile(matches[0], document, "exec"), namespace)
    return namespace[name]


def mounted_text(output: Path, service: str, destination: str) -> str:
    compose = yaml.safe_load((output / 'docker-compose.yml').read_text())
    for mount in compose['services'][service].get('volumes', []):
        source, target, *_mode = mount.split(':')
        if target == destination:
            return (output / source).read_text()
    raise AssertionError(f'Missing mount: {service}:{destination}')


def basic_config() -> dict:
    return yaml.safe_load((SKILL_ROOT / "assets/basic/main.yml").read_text())


def build_config(root: Path, data: dict):
    initialize_registries(load_plugins=False)
    root.mkdir(parents=True, exist_ok=True)
    config_path = root / "main.yml"
    config_path.write_text(yaml.safe_dump(data, sort_keys=False))
    fs = create_app_fs(chroot=DNSBPath(root), cache_root=DNSBPath(root / ".dnsb_cache"))
    config = Config(str(config_path), fs=fs)
    output = root / "generated" / config.name
    builder = Builder(config, fs=fs, output_dir=DNSBPath(output))
    context = asyncio.run(builder.run(need_context=True))
    return output, context


def test_skill_ships_only_basic_assets_and_uses_stable_references() -> None:
    files = {
        path.relative_to(SKILL_ROOT).as_posix()
        for path in SKILL_ROOT.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    }
    expected = {"SKILL.md", "agents/openai.yaml", "assets/basic/main.yml", "assets/basic/verify.sh"}
    expected.update(f"references/{name}.md" for name in (
        "configuration", "dnssec", "evaluation", "example-patterns", "reproduction",
        "runtime", "source-map", "topology", "zone-mutation",
    ))
    expected.update(f"scripts/{name}.py" for name in ("manifest", "measure_command", "summarize_events"))
    assert files == expected
    assert not any(path.is_symlink() for path in SKILL_ROOT.rglob("*"))
    for path in SKILL_ROOT.rglob("*.md"):
        text = path.read_text()
        assert not re.search(r"(?:examples/bugs|assets)/(?:nxns|tsuking|keytrap|camp)(?:[/._-]|$)", text)
        assert "scripts/evaluation/fixtures/" not in text
        for reference in re.findall(r"`((?:doc|examples|src|test)/[^`]+)`", text):
            assert (REPO_ROOT / reference).exists(), f"Missing repository reference: {reference}"


def test_skill_relative_markdown_links_resolve() -> None:
    for path in SKILL_ROOT.rglob("*.md"):
        for target in re.findall(r"\]\(([^)]+)\)", path.read_text()):
            if "://" in target:
                continue
            name, _, anchor = target.partition("#")
            linked = (path.parent / name).resolve() if name else path
            assert linked.is_file(), f"Broken skill link: {path}: {target}"
            if anchor:
                assert f'id="{anchor}"' in linked.read_text(), f"Missing anchor: {path}: {target}"


def test_configuration_teaching_example_builds(tmp_path: Path) -> None:
    output, _context = build_config(tmp_path, yaml_blocks("configuration.md")[0])
    compose = yaml.safe_load((output / "docker-compose.yml").read_text())
    assert {"auth", "resolver", "client"}.issubset(compose["services"])
    assert "stub-zone:" in (output / "resolver/contents/generated_zones.conf").read_text()
    assert "192.0.2.10" in (output / "auth/contents/db.example.com").read_text()


def test_dynamic_topology_next_hops_and_manifest_build(tmp_path: Path) -> None:
    blocks = yaml_blocks("topology.md")
    data = deep_merge(blocks[0], blocks[3])
    output, context = build_config(tmp_path, data)
    manifest = json.loads((output / "topology.json").read_text())
    assert set(manifest["nodes"]) == {"entry", "upstream", "auth"}
    assert "resolver-template" not in context.service_ips
    assert "resolver-template" not in manifest["nodes"]
    entry = (output / "entry/contents/generated_zones.conf").read_text()
    upstream = (output / "upstream/contents/generated_zones.conf").read_text()
    assert "forward-zone:" in entry
    assert f"forward-addr: {manifest['nodes']['upstream']['ipv4_address']}" in entry
    assert "stub-zone:" in upstream
    assert f"stub-addr: {manifest['nodes']['auth']['ipv4_address']}" in upstream


def test_dynamic_topology_rejects_missing_next_hop(tmp_path: Path) -> None:
    data = copy.deepcopy(yaml_blocks("topology.md")[0])
    data["vars"]["links"]["entry"]["targets"] = ["missing"]
    with pytest.raises(ValueError, match="Missing next hop"):
        build_config(tmp_path, data)


def test_topology_compiler_rejects_untyped_dns_edge(tmp_path: Path) -> None:
    data = copy.deepcopy(yaml_blocks("topology.md")[0])
    data["vars"]["links"]["entry"]["kind"] = "A"
    with pytest.raises(ValueError, match="Unsupported next-hop kind"):
        build_config(tmp_path, data)


def test_dynamic_authority_generation_builds(tmp_path: Path) -> None:
    data = deep_merge(yaml_blocks("configuration.md")[0], yaml_blocks("topology.md")[1])
    output, _context = build_config(tmp_path, data)
    parent = (output / "auth/contents/db.example.com").read_text()
    for label in ("alpha", "beta"):
        assert f"auth-{label}.servers.net." in parent
        assert (output / f"auth-{label}/contents/db.{label}.example.com").is_file()


def test_explicit_delegation_glue_uses_allocated_next_hop(tmp_path: Path) -> None:
    data = deep_merge(yaml_blocks("configuration.md")[0], yaml_blocks("topology.md")[2])
    output, context = build_config(tmp_path, data)
    parent = dns.zone.from_text((output / "auth/contents/db.example.com").read_text(), origin="example.com.")
    ns = parent.get_rdataset("child", "NS")
    glue = parent.get_rdataset("ns.child", "A")
    assert {record.target.to_text() for record in ns} == {"ns.child"}
    assert {record.address for record in glue} == {context.service_ips["child-auth"]}


def test_runtime_target_mapping_serializes_resolved_addresses(tmp_path: Path) -> None:
    data = deep_merge(yaml_blocks("configuration.md")[0], yaml_blocks("runtime.md")[2])
    output, context = build_config(tmp_path, data)
    text = mounted_text(output, 'probe', '/usr/local/etc/targets.json')
    targets = json.loads(text)
    assert targets == {"resolver": context.service_ips["resolver"]}
    assert "${" not in text
    compose = yaml.safe_load((output / "docker-compose.yml").read_text())
    assert "vars" not in compose["services"]["probe"]


def test_documented_internal_network_patch_uses_actual_output(tmp_path: Path) -> None:
    data = deep_merge(yaml_blocks("configuration.md")[0], yaml_blocks("runtime.md")[4])
    output, _context = build_config(tmp_path, data)
    compose = yaml.safe_load((output / "docker-compose.yml").read_text())
    assert compose["networks"]["app_net"]["internal"] is True
    assert set(compose["services"]) >= {"auth", "resolver", "client"}


def test_resolver_template_selection_builds_only_selected_instance(tmp_path: Path) -> None:
    data = deep_merge(yaml_blocks("configuration.md")[0], yaml_blocks("example-patterns.md")[0])
    data["images"]["alternate-resolver-image"] = {"ref": "unbound:1.19.0"}
    data["vars"]["resolver_implementation"] = "candidate-b"
    output, context = build_config(tmp_path, data)
    compose = yaml.safe_load((output / "docker-compose.yml").read_text())
    assert "resolver" in compose["services"]
    assert "candidate-a" not in context.service_ips
    assert "candidate-b" not in context.service_ips


def fake_signing_tools():
    class Tools:
        def __init__(self):
            self.signings = []

        def preflight(self, commands):
            pass

        def run(self, tool, arguments, cwd):
            if tool == "dnssec-keygen":
                is_ksk = "KSK" in arguments
                tag = 10001 if is_ksk else 10002
                name = f"K{arguments[-1]}.+013+{tag}"
                flags = 257 if is_ksk else 256
                (cwd / f"{name}.key").write_text(f"{arguments[-1]} IN DNSKEY {flags} 3 13 AQIDBA==\n")
                (cwd / f"{name}.private").write_text("Private-key-format: v1.3\n")
                return SimpleNamespace(stdout=name)
            assert tool == "dnssec-signzone"
            origin = arguments[arguments.index("-o") + 1]
            zone_path = Path(arguments[-1])
            content = zone_path.read_text()
            self.signings.append({"origin": origin, "input": content, "arguments": list(arguments)})
            text = "\n".join(line for line in content.splitlines() if not line.startswith("$INCLUDE"))
            text += f"\n{origin} 300 IN DNSKEY 257 3 13 AQIDBA==\n"
            text += f"{origin} 300 IN NSEC3PARAM 1 0 0 abcd\n"
            parsed = dns.zone.from_text(text, origin=origin, relativize=False)
            if origin != '.' and parsed.get_rdataset(f"www.{origin}", "A") is not None:
                text += f"www.{origin} 3600 IN RRSIG A 13 3 3600 20300101000000 20200101000000 10002 {origin} AQIDBA==\n"
            Path(f"{zone_path}.signed").write_text(text)
            if origin != ".":
                (cwd / f"dsset-{origin}").write_text(f"{origin} 300 IN DS 10001 13 2 {'ab' * 32}\n")
            return SimpleNamespace(stdout="signed")

    return Tools()


def test_dnssec_documented_hooks_reach_final_artifacts(tmp_path: Path, monkeypatch) -> None:
    from dnsbuilder.builder import build as build_module

    monkeypatch.setattr(build_module, "create_dnssec_tool_runner", lambda config: fake_signing_tools())
    data = deep_merge(basic_config(), yaml_blocks("dnssec.md")[0])
    blocks = yaml_blocks("zone-mutation.md")
    data = deep_merge(data, blocks[0])
    data = deep_merge(data, blocks[2])
    data = deep_merge(data, blocks[3])
    output, _context = build_config(tmp_path, data)

    signed = dns.zone.from_text((output / "auth/contents/db.example.com").read_text(), origin="example.com.")
    unsigned = dns.zone.from_text((output / "auth/contents/db.example.com.unsigned").read_text(), origin="example.com.")
    assert {record.address for record in signed.get_rdataset("www", "A")} == {"192.0.2.20"}
    assert {record.address for record in unsigned.get_rdataset("www", "A")} == {"1.2.3.4"}
    assert signed.get_rdataset("teaching-note", "TXT") is not None
    assert signed.get_rdataset("www", dns.rdatatype.RRSIG, dns.rdatatype.A) is not None
    report = json.loads((output / "zone-mutation.json").read_text())
    assert report["covering_rrsig_unchanged"] is True
    assert report["before_sha256"] != report["after_sha256"]
    assert (output / "resolver/contents/root.key").is_file()
    assert "trust-anchor-file" in mounted_text(output, 'resolver', '/usr/local/etc/unbound/validation.conf.server')
    parent = dns.zone.from_text((output / "tld/contents/db.com").read_text(), origin="com.")
    assert parent.get_rdataset("example", "DS") is not None


def test_mid_hook_validates_and_replaces_child_ds(tmp_path: Path) -> None:
    from dnsbuilder.utils.zone import ZoneName

    fs = create_app_fs(chroot=DNSBPath(tmp_path), cache_root=DNSBPath(tmp_path / ".dnsb_cache"))
    text = f"example.com. 300 IN DS 10001 13 2 {'ab' * 32}\n"
    fs.mkdir(DNSBPath(tmp_path / "resource/records"), parents=True, exist_ok=True)
    fs.write_text(DNSBPath(tmp_path / "resource/records/example.com.ds"), text)
    script = yaml_blocks("zone-mutation.md")[1]["builds"]["auth"]["dnssec"]["hooks"]["mid"]
    exec(script, {"zone": ZoneName("example.com"), "service_name": "auth", "fs": fs, "workdir": DNSBPath(tmp_path)})
    assert fs.read_text(DNSBPath("key:/auth/example.com.ds")) == text


def test_mid_hook_propagates_ds_into_final_parent(tmp_path: Path, monkeypatch) -> None:
    from dnsbuilder.builder import build as build_module

    monkeypatch.setattr(build_module, "create_dnssec_tool_runner", lambda config: fake_signing_tools())
    data = deep_merge(basic_config(), yaml_blocks("dnssec.md")[0])
    data = deep_merge(data, yaml_blocks("zone-mutation.md")[1])
    source = tmp_path / "resource/records/example.com.ds"
    source.parent.mkdir(parents=True)
    digest = "cd" * 32
    source.write_text(f"example.com. 300 IN DS 10001 13 2 {digest}\n")

    output, _context = build_config(tmp_path, data)

    parent = dns.zone.from_text((output / "tld/contents/db.com").read_text(), origin="com.")
    records = parent.get_rdataset("example", "DS")
    assert records is not None
    assert {record.digest.hex() for record in records} == {digest}


def test_mid_hook_rejects_ds_at_wrong_owner(tmp_path: Path) -> None:
    from dnsbuilder.utils.zone import ZoneName

    fs = create_app_fs(chroot=DNSBPath(tmp_path), cache_root=DNSBPath(tmp_path / ".dnsb_cache"))
    source = tmp_path / "resource/records/example.com.ds"
    source.parent.mkdir(parents=True)
    source.write_text(f"child.example.com. 300 IN DS 10001 13 2 {'ab' * 32}\n")
    script = yaml_blocks("zone-mutation.md")[1]["builds"]["auth"]["dnssec"]["hooks"]["mid"]
    with pytest.raises(ValueError, match="expected child apex"):
        exec(script, {"zone": ZoneName("example.com"), "service_name": "auth", "fs": fs, "workdir": DNSBPath(tmp_path)})


def test_manifest_changes_with_source_not_mtime(tmp_path: Path) -> None:
    path = SKILL_ROOT / "scripts/manifest.py"
    spec = importlib.util.spec_from_file_location("skill_manifest", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source = tmp_path / "source.yml"
    source.write_text("name: teaching\n")
    first = module.tree_hash(module.collect(tmp_path, module.DEFAULT_IGNORES, None))
    source.touch()
    second = module.tree_hash(module.collect(tmp_path, module.DEFAULT_IGNORES, None))
    assert first == second
    source.write_text("name: changed\n")
    assert module.tree_hash(module.collect(tmp_path, module.DEFAULT_IGNORES, None)) != first


def test_skill_frontmatter_and_direct_instruction_style() -> None:
    skill = (SKILL_ROOT / "SKILL.md").read_text()
    metadata = yaml.safe_load(skill.split("---", 2)[1])
    assert metadata["name"] == "dns-builder"
    assert 1 <= len(metadata["description"]) <= 1024
    excluded = ("防御", "答案", "污染", "隐藏", "白名单", "评测", "思考", "反思", "自主复现", "不提供")
    paths = [*SKILL_ROOT.rglob("*.md"), SKILL_ROOT / "agents/openai.yaml"]
    for path in paths:
        prose = re.sub(r"```.*?```", "", path.read_text(), flags=re.S)
        assert not any(word in prose for word in excluded), path
        assert "\u00a7" not in prose and "\u00a4" not in prose


def test_pattern_index_covers_all_reviewed_scenarios() -> None:
    content = (SKILL_ROOT / "references/example-patterns.md").read_text()
    scenarios = {
        "BadCache", "Birthday / Rebirthday", "CAMP", "Cuckoo", "Disbalance",
        "DNSBomb", "DNSPun", "DNSSEC fault", "DNSSEC downgrade", "FragForward",
        "Inject", "Kaminsky", "KeyTrap", "Loopy", "Maginot", "NRDelegation",
        "NXNS", "Phoenix", "TsuKing", "TsuName", "TuDoor",
    }
    rows = set(re.findall(r"^\| ([^|]+?) \|", content, flags=re.M))
    assert scenarios <= rows
    for anchor in ("nxns", "tsuking", "camp", "keytrap"):
        assert f'id="{anchor}"' in content


def test_documented_fragments_have_valid_syntax() -> None:
    def check_hooks(node, filename):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in {"setup", "modify", "restrict", "post", "pre", "mid"} and isinstance(value, str):
                    compile(value, filename, "exec")
                check_hooks(value, filename)
        elif isinstance(node, list):
            for value in node:
                check_hooks(value, filename)

    for path in SKILL_ROOT.rglob("*.md"):
        for language, block in re.findall(r"```(yaml|python|bash)\n(.*?)\n```", path.read_text(), flags=re.S):
            if language == "yaml":
                parsed = yaml.safe_load(block)
                assert isinstance(parsed, dict), path
                check_hooks(parsed, str(path))
            elif language == "python":
                compile(block, str(path), "exec")
            else:
                result = subprocess.run(["bash", "-n"], input=block, text=True, capture_output=True, timeout=10)
                assert result.returncode == 0, f"{path}: {result.stderr}"


def test_grouped_forwarders_expand_templates_and_resolve_targets(tmp_path: Path) -> None:
    data = deep_merge(yaml_blocks("configuration.md")[0], yaml_blocks("topology.md")[4])
    output, context = build_config(tmp_path, data)
    compose = yaml.safe_load((output / "docker-compose.yml").read_text())
    assert "ingress-template" not in compose["services"]
    assert "egress-template" not in context.service_ips
    for group in ("blue", "green"):
        ingress = (output / f"ingress-{group}/contents/generated_zones.conf").read_text()
        assert ingress.count("forward-addr:") == 2
        for index in range(2):
            name = f"egress-{group}-{index}"
            assert f"forward-addr: {context.service_ips[name]}" in ingress
            egress = (output / name / "contents/generated_zones.conf").read_text()
            assert f"stub-addr: {context.service_ips['auth']}" in egress


def test_source_routes_use_allocated_ips_as_keys_and_values(tmp_path: Path) -> None:
    data = deep_merge(yaml_blocks("configuration.md")[0], yaml_blocks("topology.md")[5])
    data["builds"]["resolver"]["address"] = "10.88.0.77"
    data["builds"]["secondary"] = {
        "image": "auth-image", "ref": "std:auth", "address": "10.88.0.91",
        "behavior": "example.net master www A 192.0.2.20",
    }
    data["vars"]["endpoint_routes"] = {"resolver": ["auth", "secondary"], "secondary": ["auth"]}
    data["vars"]["route_sources"] = ["resolver", "secondary"]
    output, context = build_config(tmp_path, data)
    raw = mounted_text(output, "endpoint", "/usr/local/etc/routes.json")
    assert "${" not in raw
    assert json.loads(raw) == {
        "10.88.0.77": [context.service_ips["auth"], "10.88.0.91"],
        "10.88.0.91": [context.service_ips["auth"]],
    }
    compose = yaml.safe_load((output / "docker-compose.yml").read_text())
    assert "vars" not in compose["services"]["endpoint"]


@pytest.mark.parametrize("routes", [{"missing": ["auth"]}, {"resolver": ["missing"]}])
def test_source_routes_require_existing_services(tmp_path: Path, routes: dict) -> None:
    data = deep_merge(yaml_blocks("configuration.md")[0], yaml_blocks("topology.md")[5])
    data["vars"]["endpoint_routes"] = routes
    data["vars"]["route_sources"] = list(routes)
    with pytest.raises(ValueError, match="unavailable service"):
        build_config(tmp_path, data)


def test_explicit_ns_fanout_preserves_names_without_automatic_glue(tmp_path: Path) -> None:
    data = deep_merge(yaml_blocks("configuration.md")[0], yaml_blocks("topology.md")[6])
    names = ["ns-a.example.net.", "ns-b.example.net."]
    data["vars"] = {"delegation": {"parent_zone": "example.com", "child_label": "child", "ns_names": names}}
    output, _context = build_config(tmp_path, data)
    text = (output / "auth/contents/db.example.com").read_text()
    zone = dns.zone.from_text(text, origin="example.com.", relativize=False)
    assert {rr.target.to_text() for rr in zone.get_rdataset("child.example.com.", "NS")} == set(names)
    for name in names:
        assert text.count(name) == 1


@pytest.mark.parametrize("names", [["ns.example.net.", "NS.EXAMPLE.NET."], ["relative"]])
def test_static_fanout_checks_dns_name_identity(tmp_path: Path, names: list) -> None:
    data = deep_merge(yaml_blocks("configuration.md")[0], yaml_blocks("topology.md")[6])
    data["vars"] = {"delegation": {"parent_zone": "example.com", "child_label": "child", "ns_names": names}}
    with pytest.raises(ValueError, match="distinct absolute NS names"):
        build_config(tmp_path, data)


def add_signed_child(data: dict) -> None:
    data["builds"]["auth"]["behavior"] += "\nexample.com master child NS child-auth"
    data["builds"]["child-auth"] = {
        "image": "bind", "ref": "std:auth",
        "behavior": "child.example.com master www A 192.0.2.30",
    }


def test_final_post_mutation_survives_parent_resigning(tmp_path: Path, monkeypatch) -> None:
    from dnsbuilder.builder import build as build_module

    tools = fake_signing_tools()
    monkeypatch.setattr(build_module, "create_dnssec_tool_runner", lambda config: tools)
    data = deep_merge(basic_config(), yaml_blocks("dnssec.md")[0])
    data = deep_merge(data, yaml_blocks("zone-mutation.md")[2])
    data = deep_merge(data, yaml_blocks("zone-mutation.md")[3])
    add_signed_child(data)
    data["builds"]["auth"]["dnssec"]["hooks"]["mid"] = (
        "from dnsbuilder.io import DNSBPath\n"
        "path = DNSBPath(f'temp:/services/{service_name}/zones/{zone.filename}')\n"
        "fs.write_text(path, fs.read_text(path) + '\\nmid-marker.example.com. 300 IN TXT \\\"temporary\\\"\\n')\n"
    )
    output, _context = build_config(tmp_path, data)
    signings = [entry for entry in tools.signings if entry["origin"] == "example.com."]
    assert len(signings) == 2
    assert "child.example.com." in signings[1]["input"]
    assert " IN DS " in signings[1]["input"]
    text = (output / "auth/contents/db.example.com").read_text()
    zone = dns.zone.from_text(text, origin="example.com.")
    assert "mid-marker" not in text
    assert {rr.address for rr in zone.get_rdataset("www", "A")} == {"192.0.2.20"}
    assert zone.get_rdataset("child", "DS") is not None
    assert json.loads((output / "zone-mutation.json").read_text())["covering_rrsig_unchanged"] is True


def test_mid_ds_of_an_intermediate_zone_is_regenerated(tmp_path: Path, monkeypatch) -> None:
    from dnsbuilder.builder import build as build_module

    monkeypatch.setattr(build_module, "create_dnssec_tool_runner", lambda config: fake_signing_tools())
    data = deep_merge(basic_config(), yaml_blocks("dnssec.md")[0])
    data = deep_merge(data, yaml_blocks("zone-mutation.md")[1])
    add_signed_child(data)
    source = tmp_path / "resource/records/example.com.ds"
    source.parent.mkdir(parents=True)
    source.write_text(f"example.com. 300 IN DS 10001 13 2 {'cd' * 32}\n")
    output, _context = build_config(tmp_path, data)
    parent = dns.zone.from_text((output / "tld/contents/db.com").read_text(), origin="com.")
    assert {record.digest.hex() for record in parent.get_rdataset("example", "DS")} == {"ab" * 32}


@pytest.mark.parametrize("has_child", [False, True])
def test_pre_dnskey_import_survives_first_signing_and_resigning(tmp_path: Path, monkeypatch, has_child: bool) -> None:
    from dnsbuilder.builder import build as build_module

    tools = fake_signing_tools()
    monkeypatch.setattr(build_module, "create_dnssec_tool_runner", lambda config: tools)
    data = deep_merge(basic_config(), yaml_blocks("dnssec.md")[0])
    data = deep_merge(data, yaml_blocks("zone-mutation.md")[4])
    if has_child:
        add_signed_child(data)
    source = tmp_path / "resource/records/additional-dnskeys.rr"
    source.parent.mkdir(parents=True)
    source.write_text("example.com. 300 IN DNSKEY 256 3 13 BQYHCA==\n")
    output, _context = build_config(tmp_path, data)
    zone = dns.zone.from_text((output / "auth/contents/db.example.com").read_text(), origin="example.com.")
    keys = zone.get_rdataset("@", "DNSKEY")
    assert any(key.flags == 256 and key.key == bytes([5, 6, 7, 8]) for key in keys)
    signings = [entry for entry in tools.signings if entry["origin"] == "example.com."]
    assert len(signings) == (2 if has_child else 1)
    assert all("BQYHCA==" in entry["input"] for entry in signings)


def test_post_import_replaces_only_the_selected_rrsig_set(tmp_path: Path, monkeypatch) -> None:
    from dnsbuilder.builder import build as build_module

    monkeypatch.setattr(build_module, "create_dnssec_tool_runner", lambda config: fake_signing_tools())
    data = deep_merge(basic_config(), yaml_blocks("dnssec.md")[0])
    data = deep_merge(data, yaml_blocks("zone-mutation.md")[5])
    add_signed_child(data)
    source = tmp_path / "resource/records/target-signatures.rr"
    source.parent.mkdir(parents=True)
    source.write_text("www.example.com. 3600 IN RRSIG A 13 3 3600 20300101000000 20200101000000 20002 example.com. BQYHCA==\n")
    output, _context = build_config(tmp_path, data)
    zone = dns.zone.from_text((output / "auth/contents/db.example.com").read_text(), origin="example.com.")
    assert {rr.key_tag for rr in zone.get_rdataset("www", "RRSIG", "A")} == {20002}
    assert {rr.address for rr in zone.get_rdataset("www", "A")} == {"1.2.3.4"}
    assert zone.get_rdataset("@", "DNSKEY") is not None
    assert zone.get_rdataset("child", "DS") is not None


@pytest.mark.parametrize("owner, covered", [("other.example.com.", "A"), ("www.example.com.", "NS")])
def test_rrsig_import_checks_owner_and_covered_type(tmp_path: Path, owner: str, covered: str) -> None:
    from dnsbuilder.utils.zone import ZoneName

    fs = create_app_fs(chroot=DNSBPath(tmp_path), cache_root=DNSBPath(tmp_path / ".dnsb_cache"))
    source = tmp_path / "resource/records/target-signatures.rr"
    source.parent.mkdir(parents=True)
    source.write_text(f"{owner} 3600 IN RRSIG {covered} 13 3 3600 20300101000000 20200101000000 20002 example.com. BQYHCA==\n")
    config = yaml_blocks("zone-mutation.md")[5]["builds"]["auth"]
    script = config["dnssec"]["hooks"]["post"]
    with pytest.raises(ValueError, match="selected owner"):
        exec(script, {"zone": ZoneName("example.com"), "service_name": "auth", "fs": fs, "workdir": DNSBPath(tmp_path), "config": config})


@pytest.mark.parametrize("refresh_metadata", [False, True])
def test_powerdns_metadata_refresh_uses_the_final_zone(tmp_path: Path, monkeypatch, refresh_metadata: bool) -> None:
    from dnsbuilder.builder import build as build_module

    monkeypatch.setattr(build_module, "create_dnssec_tool_runner", lambda config: fake_signing_tools())
    data = deep_merge(basic_config(), yaml_blocks("dnssec.md")[0])
    data["images"]["powerdns"] = {"ref": "pdns_auth:5.0.1"}
    data["builds"]["auth"]["image"] = "powerdns"
    data["builds"]["auth"]["dnssec"] = {"enable": True, "hooks": {"post": (
        "from dnsbuilder.io import DNSBPath\n"
        "path = DNSBPath(f'temp:/services/{service_name}/zones/{zone.filename}')\n"
        "content = fs.read_text(path).replace('1 0 0 abcd', '1 0 0 dcba')\n"
        "content += f'\\n{zone.fqdn} 300 IN RRSIG NSEC3PARAM 13 2 300 20300101000000 20200101000000 10002 example.com. AQIDBA==\\n'\n"
        "fs.write_text(path, content)\n"
    )}}
    if refresh_metadata:
        data = deep_merge(data, yaml_blocks("dnssec.md")[2])
    output, _context = build_config(tmp_path, data)
    final_zone = (output / "auth/contents/db.example.com").read_text()
    assert "NSEC3PARAM 1 0 0 dcba" in final_zone
    connection = sqlite3.connect(output / "auth/contents/pdns-dnssec/bind-dnssec-db.sqlite3")
    try:
        metadata = dict(connection.execute("SELECT kind, content FROM domainmetadata WHERE domain = 'example.com'").fetchall())
    finally:
        connection.close()
    assert metadata["PRESIGNED"] == "1"
    assert metadata["NSEC3PARAM"] == ("1 0 0 dcba" if refresh_metadata else "1 0 0 abcd")


@pytest.mark.skipif(
    not all(shutil.which(tool) for tool in ("dnssec-keygen", "dnssec-signzone", "dnssec-dsfromkey", "dnssec-verify", "named-checkzone")),
    reason="BIND DNSSEC utilities are required",
)
def test_documented_signing_commands_and_hooks_with_real_bind_tools(tmp_path: Path, monkeypatch) -> None:
    tools = {
        "dnssec-keygen": "BIND_DNSSEC_KEYGEN",
        "dnssec-signzone": "BIND_DNSSEC_SIGNZONE",
        "dnssec-dsfromkey": "BIND_DNSSEC_DSFROMKEY",
        "named-checkzone": "BIND_DNSSEC_CHECKZONE",
    }
    for tool, variable in tools.items():
        monkeypatch.setenv(variable, shutil.which(tool))
    monkeypatch.setenv("DNSSEC_AUTO_INSTALL", "0")
    document = (SKILL_ROOT / "references/dnssec.md").read_text()
    commands = re.findall(r"```bash\n(.*?)\n```", document, flags=re.S)
    subprocess.run(["bash", "-euo", "pipefail", "-c", commands[0]], cwd=tmp_path, text=True, capture_output=True, check=True, timeout=30)

    data = deep_merge(basic_config(), yaml_blocks("dnssec.md")[0])
    data = deep_merge(data, yaml_blocks("dnssec.md")[1])
    data = deep_merge(data, yaml_blocks("zone-mutation.md")[0])
    extra_dir = tmp_path / "resource/keys/additional"
    extra_dir.mkdir(parents=True)
    generated = subprocess.run(
        ["dnssec-keygen", "-q", "-K", str(extra_dir), "-a", "ECDSAP256SHA256", "-n", "ZONE", "example.com."],
        text=True, capture_output=True, check=True, timeout=30,
    )
    extra_key = extra_dir / f"{generated.stdout.strip()}.key"
    extra_zone = dns.zone.from_text("$TTL 300\n" + extra_key.read_text(), origin="example.com.", relativize=False, check_origin=False)
    extra_keys = extra_zone.get_rdataset("example.com.", "DNSKEY")
    records = tmp_path / "resource/records/additional-dnskeys.rr"
    records.parent.mkdir(parents=True)
    records.write_text(extra_keys.to_text(name=extra_zone.origin, relativize=False) + "\n")
    data["builds"]["auth"]["dnssec"]["hooks"]["pre"] += "\n" + yaml_blocks("zone-mutation.md")[4]["builds"]["auth"]["dnssec"]["hooks"]["pre"]
    output, _context = build_config(tmp_path, data)
    for service, origin, label in (
        ("root", ".", "root"), ("tld", "com.", "com"), ("auth", "example.com.", "example.com"),
        ("net", "net.", "net"), ("servers", "servers.net.", "servers.net"),
    ):
        zone_path = output / service / "contents" / f"db.{label}"
        for tool in ("named-checkzone", "dnssec-verify"):
            command = [tool, origin, str(zone_path)] if tool == "named-checkzone" else [tool, "-o", origin, str(zone_path)]
            result = subprocess.run(command, text=True, capture_output=True, timeout=30)
            assert result.returncode == 0, result.stdout + result.stderr

    keys_dir = tmp_path / "resource/keys/example"
    expected_keys = set()
    for key_file in keys_dir.glob("*.key"):
        parsed = dns.zone.from_text("$TTL 300\n" + key_file.read_text(), origin="example.com.", check_origin=False)
        expected_keys.update(parsed.get_rdataset("@", "DNSKEY"))
    signed_path = output / "auth/contents/db.example.com"
    original = dns.zone.from_text(signed_path.read_text(), origin="example.com.")
    assert set(original.get_rdataset("@", "DNSKEY")) == expected_keys | set(extra_keys)
    inventory = python_function("dnssec.md", "inspect_signature_links")(original, "www", "A", time.time())
    assert inventory and all(row["candidate_keys"] > 0 and row["signer_matches"] and row["current_window"] for row in inventory)
    parent = dns.zone.from_text((output / "tld/contents/db.com").read_text(), origin="com.")
    expected_ds = dns.zone.from_text("$TTL 300\n" + (keys_dir / "example.com.ds").read_text(), origin="example.com.", check_origin=False)
    assert set(expected_ds.get_rdataset("@", "DS")) <= set(parent.get_rdataset("example", "DS"))

    manual_input = tmp_path / "resource/zones/example.com.zone"
    manual_input.parent.mkdir(parents=True)
    shutil.copyfile(output / "auth/contents/db.example.com.unsigned", manual_input)
    subprocess.run(
        ["bash", "-euo", "pipefail", "-c", commands[1]], cwd=tmp_path,
        env={**os.environ, "keys_dir": str(keys_dir)}, text=True, capture_output=True, check=True, timeout=30,
    )
    assert (tmp_path / "run/example.com.signed").is_file()

    data = deep_merge(data, yaml_blocks("zone-mutation.md")[2])
    data = deep_merge(data, yaml_blocks("zone-mutation.md")[3])
    output, _context = build_config(tmp_path, data)
    mutated = output / "auth/contents/db.example.com"
    result = subprocess.run(["named-checkzone", "example.com.", str(mutated)], text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    result = subprocess.run(["dnssec-verify", "-o", "example.com.", str(mutated)], text=True, capture_output=True, timeout=30)
    assert result.returncode != 0
    zone = dns.zone.from_text(mutated.read_text(), origin="example.com.")
    assert {rr.address for rr in zone.get_rdataset("www", "A")} == {"192.0.2.20"}
    assert zone.get_rdataset("www", "RRSIG", "A") is not None


@pytest.mark.parametrize("network, reverse", [("10.92.0.0/24", False), ("10.93.0.0/24", True)])
def test_route_compilation_survives_renaming_reordering_and_network_changes(tmp_path: Path, network: str, reverse: bool) -> None:
    data = deep_merge(yaml_blocks("configuration.md")[0], yaml_blocks("topology.md")[5])
    data["inet"] = network
    builds = data["builds"]
    builds["authority"] = builds.pop("auth")
    builds["recursive"] = builds.pop("resolver")
    builds["recursive"]["behavior"] = "example.com stub authority"
    builds["peer"] = copy.deepcopy(builds["recursive"])
    builds["client"]["environment"]["RESOLVER"] = "${srv.recursive.ip}"
    data["vars"]["route_sources"] = ["recursive", "peer"]
    data["vars"]["endpoint_routes"] = {"peer": ["authority"], "recursive": ["authority"]}
    if reverse:
        data["builds"] = dict(reversed(list(builds.items())))
    output, context = build_config(tmp_path, data)
    routes = json.loads(mounted_text(output, "endpoint", "/usr/local/etc/routes.json"))
    assert routes == {context.service_ips[name]: [context.service_ips["authority"]] for name in ("recursive", "peer")}
    assert all(address.startswith(network.rsplit(".", 1)[0] + ".") for address in routes)
    config = (output / "recursive/contents/generated_zones.conf").read_text()
    assert f"stub-addr: {context.service_ips['authority']}" in config


@pytest.mark.parametrize("sources, routes", [
    (["resolver", "auth"], {"resolver": ["auth"]}),
    (["resolver"], {"resolver": ["auth"], "auth": ["resolver"]}),
    (["resolver", "resolver"], {"resolver": ["auth"]}),
])
def test_route_source_coverage_is_checked_independently(tmp_path: Path, sources: list, routes: dict) -> None:
    data = deep_merge(yaml_blocks("configuration.md")[0], yaml_blocks("topology.md")[5])
    data["vars"].update(route_sources=sources, endpoint_routes=routes)
    with pytest.raises(ValueError, match="coverage mismatch"):
        build_config(tmp_path, data)


@pytest.mark.parametrize("targets", [[], "auth", ["auth", "auth"]])
def test_route_target_lists_are_explicit_and_distinct(tmp_path: Path, targets) -> None:
    data = deep_merge(yaml_blocks("configuration.md")[0], yaml_blocks("topology.md")[5])
    data["vars"]["endpoint_routes"]["resolver"] = targets
    with pytest.raises(ValueError, match="distinct route targets"):
        build_config(tmp_path, data)


def flow_plan():
    roles = {"entry": "relay", "left": "resolver", "right": "resolver", "sink": "terminal"}
    edges = {"entry": ["left", "right"], "left": ["sink"], "right": ["sink"]}
    steps = [["relay", "resolver"], ["resolver", "terminal"], ["resolver", "relay"]]
    return roles, edges, steps


def test_generic_role_flow_accepts_a_branching_dag() -> None:
    roles, edges, steps = flow_plan()
    check = python_function("topology.md", "check_acyclic_flow")
    assert check(roles, edges, "entry", ["sink"], steps) == sorted(roles)
    renamed = {name: f"renamed-{index}" for index, name in enumerate(reversed(roles))}
    new_roles = {renamed[name]: role for name, role in roles.items()}
    new_edges = {renamed[source]: [renamed[target] for target in targets] for source, targets in edges.items()}
    assert check(new_roles, new_edges, renamed["entry"], [renamed["sink"]], steps) == sorted(new_roles)


@pytest.mark.parametrize("case, message", [
    ("missing", "Missing next hop"), ("unknown", "Invalid role transition"),
    ("wrong-role", "Invalid role transition"), ("cycle", "Unexpected cycle"),
    ("terminal", "Terminal has outgoing"), ("unreachable", "Unreachable nodes"),
    ("duplicate", "Invalid target list"), ("unknown-source", "Invalid entry"),
])
def test_generic_role_flow_rejects_incomplete_or_misdirected_paths(case: str, message: str) -> None:
    roles, edges, steps = flow_plan()
    if case == "missing":
        del edges["left"]
    elif case == "unknown":
        edges["left"] = ["absent"]
    elif case == "wrong-role":
        edges["entry"] = ["sink"]
    elif case == "cycle":
        edges["left"] = ["entry"]
    elif case == "terminal":
        edges["sink"] = ["entry"]
    elif case == "unreachable":
        roles["orphan"] = "relay"
        edges["orphan"] = ["left"]
    elif case == "duplicate":
        edges["entry"] = ["left", "left"]
    elif case == "unknown-source":
        edges["absent"] = ["sink"]
    with pytest.raises(ValueError, match=message):
        python_function("topology.md", "check_acyclic_flow")(roles, edges, "entry", ["sink"], steps)


@pytest.mark.parametrize("length, depth", [(2, 3), (3, 2), (1, 0)])
def test_resolution_plan_keeps_label_depth_and_reference_count_independent(length: int, depth: int) -> None:
    labels = [f"l{index}" for index in range(depth)]
    names = [".".join([*labels, f"n{index}", "example.net."]) for index in range(length)]
    required = [(name, kind) for name in names for kind in ("A", "AAAA")]
    positive = [(name.upper(), "a") for name in names]
    negative = [(name, "AAAA") for name in names]
    check = python_function("topology.md", "check_resolution_plan")
    check(required, positive, negative)
    with pytest.raises(ValueError, match="Missing resolution paths"):
        check(required, positive[:-1], negative)


@pytest.mark.parametrize("required, positive, negative, message", [
    ([("relative", "A")], [], [], "absolute owner"),
    ([("host.example.", "A")], [("host.example.", "A")], [("HOST.example.", "a")], "Conflicting"),
    ([("host.example.", "AAAA")], [("host.example.", "A")], [], "Missing resolution"),
])
def test_resolution_plan_distinguishes_types_and_explicit_negative_responses(required, positive, negative, message) -> None:
    with pytest.raises(ValueError, match=message):
        python_function("topology.md", "check_resolution_plan")(required, positive, negative)


def test_referral_fragment_preserves_query_and_declares_response_fields() -> None:
    make_referral = python_function("runtime.md", "make_referral")
    query = dns.message.make_query("www.child.example.", "AAAA", want_dnssec=True)
    query.flags |= dns.flags.AD
    targets = ["ns.child.example.", "ns.other.example."]
    addresses = {targets[0]: ["192.0.2.10", "2001:db8::10"]}
    reply = make_referral(query, "child.example.", targets, addresses, ttl=45)
    decoded = dns.message.from_wire(reply.to_wire())
    assert decoded.id == query.id and decoded.question == query.question
    assert decoded.flags & dns.flags.RD
    assert not decoded.flags & (dns.flags.AA | dns.flags.RA | dns.flags.AD)
    assert decoded.rcode() == 0 and not decoded.answer
    assert decoded.authority[0].name.to_text() == "child.example."
    assert {record.target.to_text() for record in decoded.authority[0]} == set(targets)
    assert {rrset.rdtype for rrset in decoded.additional} == {dns.rdatatype.A, dns.rdatatype.AAAA}
    assert all(rrset.name.to_text() == targets[0] and rrset.ttl == 45 for rrset in decoded.additional)
    assert not make_referral(query, "child.example.", targets, {}).additional


@pytest.mark.parametrize("case, message", [
    ("relative", "absolute cut"), ("empty", "nonempty NS"),
    ("duplicate", "Duplicate NS"), ("owner", "Address owner"), ("cut", "outside the delegated"),
])
def test_referral_fragment_rejects_mismatched_names(case: str, message: str) -> None:
    query = dns.message.make_query("www.child.example.", "A")
    cut, targets, addresses = "child.example.", ["ns.child.example."], {}
    if case == "relative":
        targets = ["relative"]
    elif case == "empty":
        targets = []
    elif case == "duplicate":
        targets += ["NS.child.example."]
    elif case == "owner":
        addresses = {"other.child.example.": ["192.0.2.10"]}
    elif case == "cut":
        cut = "elsewhere.example."
    with pytest.raises(ValueError, match=message):
        python_function("runtime.md", "make_referral")(query, cut, targets, addresses)


def test_referral_serialization_distinguishes_udp_truncation_from_complete_data() -> None:
    query = dns.message.make_query("www.child.example.", "A")
    targets = [f"ns-{index}.child.example." for index in range(40)]
    reply = python_function("runtime.md", "make_referral")(query, "child.example.", targets, {})
    complete = reply.to_wire(max_size=65535)
    truncated = reply.to_wire(max_size=512, prefer_truncation=True)
    assert len(complete) > 512 and len(truncated) <= 512
    assert dns.message.from_wire(truncated).flags & dns.flags.TC
    decoded = dns.message.from_wire(complete)
    assert sum(len(rrset) for rrset in decoded.authority) == len(targets)


@pytest.mark.parametrize("transport", ["udp", "tcp"])
def test_referral_fragment_roundtrips_over_loopback_dns(transport: str) -> None:
    make_referral = python_function("runtime.md", "make_referral")

    def read_exact(connection, size):
        result = bytearray()
        while len(result) < size:
            chunk = connection.recv(size - len(result))
            if not chunk:
                raise EOFError('Incomplete DNS frame')
            result.extend(chunk)
        return bytes(result)

    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            if transport == "udp":
                wire, connection = self.request
            else:
                connection = self.request
                connection.settimeout(2)
                size = struct.unpack("!H", read_exact(connection, 2))[0]
                wire = read_exact(connection, size)
            query = dns.message.from_wire(wire)
            response = make_referral(query, "child.example.", ["ns.child.example."], {"ns.child.example.": ["192.0.2.10"]})
            wire = response.to_wire()
            if transport == "udp":
                connection.sendto(wire, self.client_address)
            else:
                connection.sendall(struct.pack("!H", len(wire)) + wire)

    server_type = socketserver.UDPServer if transport == "udp" else socketserver.TCPServer
    with server_type(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        thread.start()
        try:
            query = dns.message.make_query("www.child.example.", "A")
            query_function = dns.query.udp if transport == "udp" else dns.query.tcp
            reply = query_function(query, "127.0.0.1", port=server.server_address[1], timeout=2)
            assert reply.id == query.id and reply.question == query.question
            assert reply.authority[0].name.to_text() == "child.example."
            assert reply.additional[0][0].address == "192.0.2.10"
        finally:
            server.shutdown()
            thread.join(timeout=3)
            assert not thread.is_alive()


@pytest.mark.parametrize("block_index, filename, record, hook", [
    (1, "example.com.ds", f"example.com. 300 IN DS 10001 13 2 {'ab' * 32}\n", "mid"),
    (4, "additional-dnskeys.rr", "example.com. 300 IN DNSKEY 256 3 13 AQIDBA==\n", "pre"),
    (5, "target-signatures.rr", "www.example.com. 300 IN RRSIG A 13 3 300 20300101000000 20200101000000 10002 example.com. AQIDBA==\n", "post"),
])
def test_record_import_checks_foreign_records_instead_of_filtering_them(tmp_path: Path, block_index: int, filename: str, record: str, hook: str) -> None:
    from dnsbuilder.utils.zone import ZoneName

    fs = create_app_fs(chroot=DNSBPath(tmp_path), cache_root=DNSBPath(tmp_path / ".dnsb_cache"))
    source = tmp_path / "resource/records" / filename
    source.parent.mkdir(parents=True)
    source.write_text(record + "foreign.example.net. 300 IN A 192.0.2.44\n")
    config = yaml_blocks("zone-mutation.md")[block_index]["builds"]["auth"]
    with pytest.raises(ValueError, match="Expected one"):
        exec(config["dnssec"]["hooks"][hook], {"zone": ZoneName("example.com"), "service_name": "auth", "fs": fs, "workdir": DNSBPath(tmp_path), "config": config})


def signed_metadata_zone():
    """Build metadata-only records; cryptographic validation is tested with BIND."""
    key_text = "256 3 13 AQIDBA=="
    key = dns.rdata.from_text("IN", "DNSKEY", key_text)
    tag = dns.dnssec.key_id(key)
    text = (
        "$TTL 300\n"
        "@ IN SOA ns.example.com. hostmaster.example.com. 1 3600 600 86400 300\n"
        "@ IN NS ns.example.com.\n"
        f"@ IN DNSKEY {key_text}\n@ IN DNSKEY {key_text}\n"
        "www IN A 192.0.2.10\n"
        f"www IN RRSIG A 13 3 300 20300101000000 20200101000000 {tag} example.com. AQIDBA==\n"
        f"@ IN RRSIG DNSKEY 13 2 300 20300101000000 20200101000000 {tag} example.com. AQIDBA==\n"
    )
    return dns.zone.from_text(text, origin="example.com.", relativize=False)


def test_signature_inventory_uses_distinct_keys_and_selected_covered_type() -> None:
    parsed = signed_metadata_zone()
    inventory = python_function("dnssec.md", "inspect_signature_links")(parsed, "www.example.com.", "A", 1767225600)
    assert len(inventory) == 1
    assert inventory[0]["candidate_keys"] == 1
    assert inventory[0]["signer_matches"] and inventory[0]["current_window"]
    assert inventory[0]["labels"] == 3
    assert inventory[0]["original_ttl"] == inventory[0]["observed_ttl"] == 300
    with pytest.raises(ValueError, match="Missing data"):
        python_function("dnssec.md", "inspect_signature_links")(parsed, "www.example.com.", "AAAA", 1767225600)


@pytest.mark.parametrize("changes, field, expected, now", [
    ({"key_tag": 0}, "candidate_keys", 0, 1767225600),
    ({"algorithm": 14}, "candidate_keys", 0, 1767225600),
    ({"signer": dns.name.from_text("elsewhere.example.")}, "signer_matches", False, 1767225600),
    ({"expiration": 1735689600}, "current_window", False, 1767225600),
    ({"inception": 1798761600}, "current_window", False, 1767225600),
    ({"inception": 4294967290, "expiration": 10}, "current_window", True, 4294967300),
])
def test_signature_inventory_reports_mismatch_and_time_window(changes: dict, field: str, expected, now: int) -> None:
    parsed = signed_metadata_zone()
    signatures = parsed.get_rdataset("www.example.com.", "RRSIG", "A")
    changed = next(iter(signatures)).replace(**changes)
    signatures.clear()
    signatures.add(changed, 300)
    inventory = python_function("dnssec.md", "inspect_signature_links")(parsed, "www.example.com.", "A", now)
    assert inventory[0][field] == expected


@pytest.mark.parametrize("changes", [{"flags": 0}, {"protocol": 2}])
def test_signature_inventory_checks_zone_key_flag_and_protocol(changes: dict) -> None:
    parsed = signed_metadata_zone()
    keys = parsed.get_rdataset("example.com.", "DNSKEY")
    changed = next(iter(keys)).replace(**changes)
    keys.clear()
    keys.add(changed, 300)
    signatures = parsed.get_rdataset("www.example.com.", "RRSIG", "A")
    signature = next(iter(signatures)).replace(key_tag=dns.dnssec.key_id(changed))
    signatures.clear()
    signatures.add(signature, 300)
    inventory = python_function("dnssec.md", "inspect_signature_links")(parsed, "www.example.com.", "A", 1767225600)
    assert inventory[0]["candidate_keys"] == 0


@pytest.mark.parametrize("updates, missing, expected", [
    ({}, [], "pass"), ({}, ["path"], "not_run"), ({}, ["mechanism"], "not_run"),
    ({"cleanup": "fail"}, [], "fail"), ({"ready": "fail"}, ["mechanism"], "fail"),
    ({"path": "not_run"}, [], "not_run"),
])
def test_required_phase_statuses_are_independent(updates: dict, missing: list, expected: str) -> None:
    required = ["structure", "ready", "endpoint", "path", "mechanism", "cleanup"]
    checks = dict.fromkeys(required, "pass")
    checks.update(updates)
    checks["query"] = "pass"
    for name in missing:
        del checks[name]
    assert python_function("reproduction.md", "summarize_checks")(checks, required) == expected


def test_phase_summary_requires_explicit_check_names_and_statuses() -> None:
    summarize = python_function("reproduction.md", "summarize_checks")
    with pytest.raises(ValueError, match="Declare required"):
        summarize({}, [])
    with pytest.raises(ValueError, match="Invalid check status"):
        summarize({"mechanism": "SERVFAIL"}, ["mechanism"])
    assert summarize({}, ["mechanism"]) == "not_run"
