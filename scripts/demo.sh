#!/usr/bin/env bash
# Supported local fictional demo. No provider credentials are forwarded.
set -euo pipefail
cd "$(dirname "$0")/.."
: "${COMMERCE_DEMO_PASSWORD:?Set a fictional COMMERCE_DEMO_PASSWORD of at least 16 characters}"
if ((${#COMMERCE_DEMO_PASSWORD}<16)); then echo 'Fictional password requires at least 16 characters' >&2; exit 2; fi
export COMMERCE_DEMO_MODE="${COMMERCE_DEMO_MODE:-rules}"
case "$COMMERCE_DEMO_MODE" in rules|mock-specialists) ;; *) echo 'Only rules or mock-specialists permitted' >&2; exit 2;; esac
export COMMERCE_DEMO_PORT=8133 COMMERCE_DEMO_ORIGIN=http://127.0.0.1:8133
app=(docker compose --env-file /dev/null -p decisionops-github-demo -f compose.demo.yaml)
case "${1:-}" in
  build) "${app[@]}" build --pull=false init web ;;
  build-cached) "${app[@]}" -f compose.demo.cached.yaml build --pull=false init web ;;
  start) "${app[@]}" up -d --no-build --wait --wait-timeout 100 ;;
  health) curl --noproxy '*' --fail --silent --max-time 5 http://127.0.0.1:8133/health; echo; "${app[@]}" ps --all ;;
  stop) "${app[@]}" down ;;
  reset)
    if [[ "${COMMERCE_DEMO_RESET:-}" != decisionops-github-demo ]]; then echo 'Set COMMERCE_DEMO_RESET=decisionops-github-demo to delete ONLY this fictional database' >&2; exit 2; fi
    "${app[@]}" down -v ;;
  *) echo 'Usage: bash scripts/demo.sh build|build-cached|start|health|stop|reset' >&2; exit 2 ;;
esac
