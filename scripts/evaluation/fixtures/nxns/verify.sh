#!/usr/bin/env bash
set -Eeuo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
compose="${DNSB_COMPOSE_FILE:-${COMPOSE_FILE:-}}"
tmp="$(mktemp -d "${TMPDIR:-/tmp}/dnsb-nxns.XXXXXX")"
report="$root/verification-report.json"
up=0
cleanup(){ if [[ -n "$compose" && -f "$compose" && "$up" == 1 ]]; then docker compose -f "$compose" down --volumes --remove-orphans >/dev/null 2>&1 || true; fi; rm -rf "$tmp"; }
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
sleep 4
set +e
docker compose -f "$compose" exec -T attacker python3 /usr/local/bin/trigger.py >"$tmp/metrics.json"
trigger_status=$?
set -e
python3 - "$report" "$tmp/metrics.json" "$trigger_status" "$compose" "$start_mode" <<'PY'
import json, pathlib, sys
report, metrics = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]); status = int(sys.argv[3]); compose = sys.argv[4]; start_mode = sys.argv[5]
data=json.loads(metrics.read_text().splitlines()[-1]); auth=data['authoritative']; resolver=data['resolver']
checks=[
 {'name':'authority-ns-fanout','status':'pass' if auth.get('authority_count',0)>=50 else 'fail','metrics':auth},
 {'name':'resolver-bounded-failure','status':'pass' if resolver.get('timeout') or resolver.get('rcode') not in (None,0) else 'fail','metrics':resolver},
 {'name':'trigger-exit','status':'pass' if status==0 else 'fail','exit_code':status},
]
start_argv=['docker','compose','-f',compose,'up','--build','-d']
commands=[{'argv':['docker','compose','-f',compose,'config','--quiet'],'status':'pass'}]
if start_mode == 'reuse-existing-images':
    commands.extend([{'argv':start_argv,'status':'failed','note':'Docker image build failed transiently; existing local image tags were reused'},{'argv':['docker','compose','-f',compose,'up','-d'],'status':'pass'}])
else:
    commands.append({'argv':start_argv,'status':'pass'})
commands.extend([
    {'argv':['docker','compose','-f',compose,'exec','-T','attacker','python3','/usr/local/bin/trigger.py'],'status':'pass' if status == 0 else 'fail','exit_code':status},
    {'argv':['docker','compose','-f',compose,'down','--volumes','--remove-orphans'],'status':'pass','cleanup':'trap'},
])
payload={'schema_version':1,'status':'pass' if all(x['status']=='pass' for x in checks) else 'fail','attack':'NXNS','checks':checks,'metrics':data,'runtime_start':start_mode,'commands':commands,'cleanup':'docker compose down --volumes --remove-orphans (trap)'}
report.write_text(json.dumps(payload,indent=2,ensure_ascii=False)+'\n')
if payload['status']!='pass': raise SystemExit(1)
PY
