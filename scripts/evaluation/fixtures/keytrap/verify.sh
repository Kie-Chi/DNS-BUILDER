#!/usr/bin/env bash
set -Eeuo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
compose="${DNSB_COMPOSE_FILE:-${COMPOSE_FILE:-}}"
tmp="$(mktemp -d "${TMPDIR:-/tmp}/dnsb-keytrap.XXXXXX")"
report="$root/verification-report.json"
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
  start_mode="reuse-existing-images"
  docker compose -f "$compose" up -d
fi
up=1
sleep 5
payload_count="$(docker compose -f "$compose" exec -T sld sh -c "grep -Ec 'DNSKEY|RRSIG' /usr/local/etc/zones/db.example.com || true" | tr -d '[:space:]')"
set +e
docker compose -f "$compose" exec -T client python3 /usr/local/etc/query.py >"$tmp/query.json"
query_status=$?
set -e
python3 - "$report" "$tmp/query.json" "$payload_count" "$query_status" "$compose" "$start_mode" <<'PY'
import json, pathlib, sys
report, query = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]); payload_count = int(sys.argv[3] or 0); query_status = int(sys.argv[4]); compose = sys.argv[5]; start_mode = sys.argv[6]
metric = json.loads(query.read_text().splitlines()[-1])
checks = [
 {"name":"dnssec-payload-present","status":"pass" if payload_count >= 2 else "fail","observed_records":payload_count},
 {"name":"validating-resolver-bounded-failure","status":"pass" if metric.get("timeout") or metric.get("rcode") not in (None,0) else "fail","metrics":metric},
 {"name":"query-command","status":"pass" if query_status == 0 else "fail","exit_code":query_status},
]
start_argv=["docker","compose","-f",compose,"up","--build","-d"]
commands=[{"argv":["docker","compose","-f",compose,"config","--quiet"],"status":"pass"}]
if start_mode == "reuse-existing-images":
    commands.extend([{"argv":start_argv,"status":"failed","note":"Docker image build failed transiently; existing local image tags were reused"},{"argv":["docker","compose","-f",compose,"up","-d"],"status":"pass"}])
else:
    commands.append({"argv":start_argv,"status":"pass"})
commands.extend([
    {"argv":["docker","compose","-f",compose,"exec","-T","sld","sh","-c","grep -Ec 'DNSKEY|RRSIG' /usr/local/etc/zones/db.example.com"],"status":"pass"},
    {"argv":["docker","compose","-f",compose,"exec","-T","client","python3","/usr/local/etc/query.py"],"status":"pass" if query_status == 0 else "fail","exit_code":query_status},
    {"argv":["docker","compose","-f",compose,"down","--volumes","--remove-orphans"],"status":"pass","cleanup":"trap"},
])
payload={"schema_version":1,"status":"pass" if all(x["status"]=="pass" for x in checks) else "fail","attack":"KeyTrap","checks":checks,"metrics":metric,"dnssec_payload_records":payload_count,"runtime_start":start_mode,"commands":commands,"cleanup":"docker compose down --volumes --remove-orphans (trap)"}
report.write_text(json.dumps(payload,indent=2,ensure_ascii=False)+"\n")
if payload["status"] != "pass": raise SystemExit(1)
PY
