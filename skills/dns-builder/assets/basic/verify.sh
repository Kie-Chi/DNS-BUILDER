#!/usr/bin/env bash
set -euo pipefail

script_dir=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
compose_file="$script_dir/output/basic/docker-compose.yml"

# Docker's service DNS name keeps this smoke test independent of allocated IPs.
answer=$(docker compose -f "$compose_file" exec -T client sh -c \
  'dig +time=3 +tries=1 @resolver www.example.com A +short' | tr -d "\r")
if [[ "$answer" != "1.2.3.4" ]]; then
  echo "unexpected answer: $answer" >&2
  exit 1
fi

echo "basic DNS delegation verification passed: $answer"
