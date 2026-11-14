#!/usr/bin/env bash
# Fictional, local, mocked specialists. No paid calls or provider credentials.
# Reuses locked local build dependencies; does not touch the original demo project.
set -euo pipefail
cd "$(dirname "$0")/.."
export COMMERCE_PORTFOLIO_PORT=8123
export COMMERCE_PORTFOLIO_ORIGIN=http://127.0.0.1:8123
: "${COMMERCE_MULTI_AGENT_PASSWORD:?Set an explicit fictional local password of at least 16 characters}"
if ((${#COMMERCE_MULTI_AGENT_PASSWORD}<16)); then
  echo 'Fictional local password must have at least 16 characters' >&2
  exit 2
fi
export COMMERCE_PORTFOLIO_PASSWORD="$COMMERCE_MULTI_AGENT_PASSWORD"
app=(docker compose --project-directory "$PWD" --env-file /dev/null -p decisionops-multi-agent-demo -f tests/compose/portfolio.yaml -f tests/compose/multi-agent.yaml)
case "${1:-}" in
  build) "${app[@]}" build --pull=false init web ;;
  start) "${app[@]}" up -d --no-build --pull never --wait --wait-timeout 100 ;;
  check)
    curl --noproxy '*' --fail --silent --max-time 5 http://127.0.0.1:8123/health
    echo
    "${app[@]}" ps --all
    ;;
  stop) "${app[@]}" down ;;
  reset)
    if [[ "${COMMERCE_CONFIRM_RESET:-}" != decisionops-multi-agent-demo ]]; then
      echo 'Reset deletes only the fictional task database. Set COMMERCE_CONFIRM_RESET=decisionops-multi-agent-demo explicitly.' >&2
      exit 2
    fi
    "${app[@]}" down -v
    ;;
  *) echo 'Usage: bash scripts/multi_agent_demo.sh build|start|check|stop|reset' >&2; exit 2 ;;
esac
