#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
root=$PWD
ready() {
 for port in 8096 8097; do
  found=0
  for ((attempt=0; attempt<20; attempt++)); do
   if curl --noproxy '*' --connect-timeout 1 --max-time 1 --fail --silent "http://127.0.0.1:$port/health"; then echo; found=1; break; fi
   sleep 0.2
  done
  if ((found==0)); then echo "Fixture $port did not become ready" >&2; return 1; fi
 done
}
case "${1:-}" in
 build)
  mkdir -p runs/browser-investigation/{dist,runtime}
  docker run --rm --pull never --network none \
    -v "$root/frontend:/source:ro" -v "$root/runs/browser-investigation/dist:/output" \
    --entrypoint sh decisionops-commerce-browser:local -c 'cp -r /source/. /workspace/ && ./node_modules/.bin/tsc --noEmit && ./node_modules/.bin/vite build --config vite.evaluation.config.ts --outDir /output --emptyOutDir'
  docker run --rm --pull never --network none \
    -v "$root/browser-investigation:/source/browser-investigation:ro" -v "$root/runs/browser-investigation/runtime:/runtime" \
    --entrypoint sh decisionops-commerce-browser:local -c 'cp -r /source/browser-investigation /workspace/browser-investigation && ./node_modules/.bin/tsc -p browser-investigation/tsconfig.json'
  ;;
 start) test -f runs/browser-investigation/dist/evaluation.html; docker compose --project-directory "$PWD" -p decisionops-browser-fixtures -f tests/compose/browser-fixtures.yaml up -d --force-recreate --pull never; ready ;;
 check) ready ;;
 test)
  artifacts=${2:-runs/browser-investigation/tests}
  mkdir -p "$artifacts"
  artifacts=$(realpath "$artifacts")
  docker run --rm --pull never --network host -e BROWSER_ARTIFACT_DIR=/workspace/artifacts \
    -v "$root/browser-investigation:/workspace/repo/browser-investigation:ro" \
    -v "$root/frontend:/workspace/repo/frontend:ro" -v "$artifacts:/workspace/artifacts" \
    --entrypoint sh decisionops-commerce-browser:local -c 'npx --no-install playwright test --config repo/frontend/playwright.browser.config.ts'
  ;;
 stop) docker compose --project-directory "$PWD" -p decisionops-browser-fixtures -f tests/compose/browser-fixtures.yaml down ;;
 *) echo 'Usage: bash scripts/browser_fixture.sh build|start|check|test [artifact-directory]|stop' >&2; exit 2 ;;
esac
