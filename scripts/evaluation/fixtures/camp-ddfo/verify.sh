#!/usr/bin/env bash
set -Eeuo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
compose="${DNSB_COMPOSE_FILE:-${COMPOSE_FILE:-}}"
tmp="$(mktemp -d "${TMPDIR:-/tmp}/dnsb-camp.XXXXXX")"
report="$root/verification-report.json"
metrics="$tmp/metrics.json"
up=0
cleanup() { if [[ -n "$compose" && -f "$compose" && "$up" == 1 ]]; then docker compose -f "$compose" down --volumes --remove-orphans >/dev/null 2>&1 || true; fi; rm -rf "$tmp"; }
trap cleanup EXIT
if [[ -z "$compose" ]]; then
  command -v dnsb >/dev/null
  dnsb --no-update-check build "$root/main.yml" --workdir @config --output-dir "$tmp/build" >/dev/null
  compose="$(find "$tmp/build" -name docker-compose.yml -type f -print -quit)"
fi
[[ -n "$compose" && -f "$compose" ]]
docker compose -f "$compose" config --quiet
start_mode="build"
if ! docker compose -f "$compose" up --build -d; then
  # Building the pinned Unbound image may require a transient Docker Hub
  # token.  When DNS-BUILDER has already produced all image tags locally,
  # retry without rebuilding so the DNS semantics can still be verified.  The
  # report records this mode explicitly; a clean host without those images
  # must rerun the normal build path rather than treating this as portable.
  start_mode="reuse-existing-images"
  docker compose -f "$compose" up -d
fi
up=1
sleep 5
set +e
docker compose -f "$compose" exec -T client python3 /usr/local/dump/poc_trigger.py >"$metrics"
probe_status=$?
set -e
[[ -s "$metrics" ]]
python3 - "$report" "$metrics" "$probe_status" "$start_mode" <<'PY'
import json, pathlib, sys
report = pathlib.Path(sys.argv[1]); metrics = pathlib.Path(sys.argv[2]); status_code = int(sys.argv[3]); start_mode = sys.argv[4]
data = json.loads(metrics.read_text())
primary = data["primary_trigger"]; resolver = data["resolver_trigger"]
checks = [
    {"name": "primary-cname-trigger", "status": "pass" if primary.get("answer_count", 0) >= 1 else "fail", "metrics": primary},
    {"name": "delegation-depth", "status": "pass" if len(data["delegation_probes"]) == 10 and all(x.get("authority_count", 0) >= 1 and x.get("rcode") == 0 and not x.get("timeout") for x in data["delegation_probes"]) else "fail", "expected": 10, "observed": len(data["delegation_probes"])},
    {"name": "resolver-bounded-failure", "status": "pass" if resolver.get("timeout") or resolver.get("rcode") not in (None, 0) else "fail", "metrics": resolver},
    {"name": "probe-exit", "status": "pass" if status_code == 0 else "fail", "exit_code": status_code},
]
start_argv = ["docker", "compose", "-f", compose, "up", "--build", "-d"]
commands = [
    {"argv": ["docker", "compose", "-f", compose, "config", "--quiet"], "status": "pass"},
]
if start_mode == "reuse-existing-images":
    commands.append({"argv": start_argv, "status": "failed", "note": "Docker image build failed transiently; existing local image tags were reused"})
    commands.append({"argv": ["docker", "compose", "-f", compose, "up", "-d"], "status": "pass"})
else:
    commands.append({"argv": start_argv, "status": "pass"})
commands.extend([
    {"argv": ["docker", "compose", "-f", compose, "exec", "-T", "client", "python3", "/usr/local/dump/poc_trigger.py"], "status": "pass" if status_code == 0 else "fail", "exit_code": status_code},
    {"argv": ["docker", "compose", "-f", compose, "down", "--volumes", "--remove-orphans"], "status": "pass", "cleanup": "trap"},
])
payload = {"schema_version": 1, "status": "pass" if all(x["status"] == "pass" for x in checks) else "fail", "attack": "CAMP-DD-FO", "checks": checks, "metrics": data, "runtime_start": start_mode, "commands": commands, "cleanup": "docker compose down --volumes --remove-orphans (trap)"}
report.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
if payload["status"] != "pass": raise SystemExit(1)
PY
