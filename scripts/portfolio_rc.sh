#!/usr/bin/env bash
# Offline fictional release candidate. No provider key is forwarded to Compose.
set -euo pipefail
cd "$(dirname "$0")/.."
export COMMERCE_PORTFOLIO_PORT=8103
export COMMERCE_PORTFOLIO_ORIGIN=http://127.0.0.1:8103
: "${COMMERCE_PORTFOLIO_PASSWORD:?Set a fictional local invitation password of at least 16 characters}"
if ((${#COMMERCE_PORTFOLIO_PASSWORD}<16)); then echo 'Invitation password must have at least 16 characters' >&2; exit 2; fi
app=(docker compose --env-file /dev/null -p decisionops-portfolio-rc-demo -f compose.portfolio.yaml -f compose.portfolio-rc.yaml)
public=(docker compose --env-file /dev/null -p decisionops-portfolio-rc-public -f compose.walkthrough-rc.yaml)
case "${1:-}" in
 build) "${app[@]}" build --pull=false init web; "${public[@]}" build --pull=false ;;
 start) "${app[@]}" up -d --no-build --pull never --wait --wait-timeout 100; "${public[@]}" up -d --no-build --pull never --wait --wait-timeout 60 ;;
 check) curl --noproxy '*' --fail --silent --max-time 5 http://127.0.0.1:8103/health; echo; curl --noproxy '*' --fail --silent --max-time 5 http://127.0.0.1:8104/health; echo; "${app[@]}" ps --all ;;
 verify) python3 -B scripts/commerce_portfolio_verify.py --project decisionops-portfolio-rc-demo --port 8103 --public-url http://127.0.0.1:8104 --output runs/portfolio-rc/staff-rehearsal --compose-override compose.portfolio-rc.yaml ;;
 stop) "${app[@]}" down; "${public[@]}" down ;;
 reset)
  if [[ "${RESET_FICTIONAL_RC:-}" != '1' ]]; then echo 'Operator-only reset: set RESET_FICTIONAL_RC=1; this deletes ONLY the RC fictional database.' >&2; exit 2; fi
  "${app[@]}" down -v
  "${app[@]}" up -d --no-build --pull never --wait --wait-timeout 100
  ;;
 *) echo 'Usage: bash scripts/portfolio_rc.sh build|start|check|verify|stop|reset' >&2; exit 2 ;;
esac
