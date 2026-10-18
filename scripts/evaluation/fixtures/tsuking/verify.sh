#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
WORK="$ROOT/.verify-work"
REPORT="$ROOT/verification-report.json"
COMPOSE="${DNSB_COMPOSE_FILE:-$WORK/output/tsuking-chain/docker-compose.yml}"
DNSB_BIN="${DNSB_BIN:-$ROOT/../../../.venv/bin/dnsb}"
mkdir -p "$WORK"
rm -f "$WORK/commands.jsonl"

record() {
  local label="$1" rc="$2"; shift 2
python3 - "$WORK/commands.jsonl" "$label" "$rc" "$@" <<'PY'
import json, pathlib, sys
path, label, rc, *argv = sys.argv[1:]
payload = {"label": label, "argv": argv, "exit_code": int(rc)}
log = pathlib.Path(path).with_name(label + ".log")
payload["output"] = log.read_text(errors="replace")[-12000:] if log.exists() else ""
with open(path, "a", encoding="utf-8") as stream:
    stream.write(json.dumps(payload, ensure_ascii=False) + "\n")
PY
}

run() {
  local label="$1"; shift
  local log="$WORK/$label.log" rc
  set +e
  "$@" >"$log" 2>&1
  rc=$?
  set -e
  record "$label" "$rc" "$@"
  return "$rc"
}

write_report() {
  local status="$1"
  python3 - "$REPORT" "$REPORT.tmp" "$status" "$WORK/commands.jsonl" <<'PY'
import json, pathlib, sys
report, checks_path, status, commands = sys.argv[1:]
items = []
path = pathlib.Path(commands)
if path.exists():
    items = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
try:
    data = json.load(open(checks_path))
except FileNotFoundError:
    data = {"checks": []}
data["status"] = status
data["commands"] = items
json.dump(data, open(report, "w"), indent=2)
PY
}

add_check() {
  python3 - "$REPORT.tmp" "$1" "$2" "$3" <<'PY'
import json, sys
path, name, status, detail = sys.argv[1:]
try: data=json.load(open(path))
except FileNotFoundError: data={"status":"running","checks":[]}
data.setdefault("checks", []).append({"name":name,"status":status,"detail":detail})
json.dump(data, open(path,"w"), indent=2)
PY
}

cleanup() {
  if [ -f "$COMPOSE" ]; then
    run cleanup docker compose -f "$COMPOSE" down --volumes --remove-orphans || true
  fi
}
trap cleanup EXIT INT TERM

run build "$DNSB_BIN" --no-update-check build "$ROOT/main.yml" --workdir @config --output-dir "$WORK" || {
  add_check build fail "dnsb build failed"
  write_report fail
  exit 1
}
add_check build pass "dnsb build completed"
run compose-config docker compose -f "$COMPOSE" config --quiet || {
  add_check compose-config fail "docker compose config failed"
  write_report fail
  exit 1
}
add_check compose-config pass "Compose configuration is valid"
run compose-up docker compose -f "$COMPOSE" up --build -d || {
  add_check compose-up fail "docker compose up failed"
  write_report fail
  exit 1
}
running="$(docker compose -f "$COMPOSE" ps --status running --services | grep -v '^dnsb-image-builder-' | wc -l | tr -d ' ')"
if [ "$running" -lt 35 ]; then
  add_check services-started fail "running services=$running, expected at least 35"
  write_report fail
  exit 1
fi
add_check services-started pass "running services=$running (auth, victim, traffic, 16 fl, 16 rl)"

if run authoritative-referral docker compose -f "$COMPOSE" exec -T auth python3 - <<'PY'
import json
from dnslib import DNSRecord
q=DNSRecord.question('x.example.com','A')
wire=q.send('auth',53,timeout=3)
r=DNSRecord.parse(wire)
metric={'query_bytes':len(q.pack()),'response_bytes':len(wire),'amplification_factor':round(len(wire)/len(q.pack()),3),'answer_count':len(r.rr),'authority_count':len(r.auth),'additional_count':len(r.ar),'rcode':r.header.rcode}
print(json.dumps(metric,sort_keys=True))
assert r.header.rcode == 0 and len(r.rr) == 0 and len(r.auth) >= 1 and len(r.ar) >= len(r.auth), metric
PY
then add_check authoritative-referral pass "NOERROR referral with no A answer and glue; metric is in command log"
else add_check authoritative-referral fail "auth did not produce the paper referral"; write_report fail; exit 1; fi

if run resolver-chain docker compose -f "$COMPOSE" exec -T auth python3 - <<'PY'
import json, socket
from dnslib import DNSRecord
q=DNSRecord.question('x.example.com','A')
try:
    wire=q.send('fl-0',53,timeout=3)
    r=DNSRecord.parse(wire)
    metric={'rcode':r.header.rcode,'answer_count':len(r.rr),'authority_count':len(r.auth),'additional_count':len(r.ar)}
    print(json.dumps(metric,sort_keys=True))
    assert r.header.rcode != 0, metric
except socket.timeout:
    print(json.dumps({'result':'timeout'}))
PY
then add_check resolver-chain pass "fl-0 query ended in bounded SERVFAIL/error/timeout"
else add_check resolver-chain fail "fl-0 did not exhibit the expected referral-chain failure"; write_report fail; exit 1; fi

if run path-logs docker compose -f "$COMPOSE" logs --no-color auth rl-0-0 fl-0; then
  grep -Eq 'tsuking-chain-fl-0.*x\.example\.com|tsuking-fl-0.*x\.example\.com' "$WORK/path-logs.log" || { add_check resolver-path fail "fl-0 logs contain no query evidence"; write_report fail; exit 1; }
  grep -Eq 'tsuking-chain-rl-0-0.*x\.example\.com|tsuking-rl-0-0.*x\.example\.com' "$WORK/path-logs.log" || { add_check resolver-path fail "rl-0-0 logs contain no query evidence"; write_report fail; exit 1; }
  add_check resolver-path pass "logs preserve fl-0 -> rl-0-0 -> auth query path"
else
  add_check resolver-path fail "could not collect resolver logs"; write_report fail; exit 1
fi

trap - EXIT INT TERM
cleanup
add_check cleanup pass "compose down completed"
write_report pass
echo "TsuKing verification passed: $REPORT"
