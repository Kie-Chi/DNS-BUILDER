#!/usr/bin/env bash
set -euo pipefail

compose=(docker compose -f examples/bugs/dnssec-fault/output/dnssec-fault-pdns/docker-compose.yml)
client=("${compose[@]}" exec -T client)

run() {
  echo "### $*"
  "${client[@]}" dig +time=3 +tries=1 +dnssec "$@"
}

# Direct PowerDNS Authoritative checks.
cn_soa=$(run @10.53.0.8 cn SOA)
grep -q 'status: NOERROR' <<<"$cn_soa"
grep -q 'RRSIG.*SOA' <<<"$cn_soa"
cn_key=$(run @10.53.0.8 cn DNSKEY)
grep -q 'DNSKEY' <<<"$cn_key"
cn_ds=$(run @10.53.0.8 dlv.cn DS)
grep -Eq '[[:space:]]DS[[:space:]]' <<<"$cn_ds"

# Recursive validation through the isolated root.
positive=$(run @10.53.0.5 www.dlv.cn A)
grep -q 'flags: .* ad' <<<"$positive"
grep -q 'RRSIG' <<<"$positive"
positive2=$(run @10.53.0.5 www.target.com A)
grep -q 'flags: .* ad' <<<"$positive2"
grep -q 'RRSIG' <<<"$positive2"
negative=$(run @10.53.0.5 missing.dlv.cn A)
grep -q 'status: NXDOMAIN' <<<"$negative"
grep -q 'flags: .* ad' <<<"$negative"
grep -q 'NSEC3' <<<"$negative"
grep -q 'RRSIG.*NSEC3' <<<"$negative"

echo 'DNSSEC/PowerDNS topology verification passed.'
