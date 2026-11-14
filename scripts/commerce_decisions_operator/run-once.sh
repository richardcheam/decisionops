#!/usr/bin/env bash
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
umask 077
PYTHONPATH="$PWD" .venv-decisions/bin/python scripts/commerce_decisions_operator/verify_config.py
if [ -z "${OPENAI_API_KEY:-}" ]; then echo 'External credential unavailable; stop.'; exit 1; fi
if [ ! -s "$EVIDENCE/case-id.txt" ]; then echo 'Preparation incomplete; stop.'; exit 1; fi
# Atomic single-use local admission. Never delete/reset this marker to retry.
mkdir "$EVIDENCE/live-attempt-started"
cp "$CONFIG" "$EVIDENCE/used-config.json"
CASE_ID=$(cat "$EVIDENCE/case-id.txt")
# Always attempt durable export, including when CLI exits before writing trace.json.
save_evidence() {
  code=$?
  trap - EXIT
  printf '%s\n' "$code" > "$EVIDENCE/cli-exit-code.txt"
  if ! .venv-decisions/bin/python scripts/commerce_decisions_operator/export_evidence.py > "$EVIDENCE/export.log" 2>&1; then
    echo 'Evidence export failed: keep the container for inspection.'
    cat "$EVIDENCE/export.log"
  fi
  echo "Stopped. Evidence: $EVIDENCE"
  echo 'Do not rerun or resume; review this attempt first.'
  exit "$code"
}
trap save_evidence EXIT
# THE ONLY PAID-CALL COMMAND. One investigation, no SDK/transport retries.
.venv-decisions/bin/python -B -m decisionops.commerce.api_investigation start \
  --case "$CASE_ID" \
  --report 'The shipment did not arrive. Please investigate the relevant fictional store records and propose a replacement only if all required conditions are established.' \
  --config "$CONFIG" \
  --approved-config-sha256 "$APPROVED_HASH" \
  --output "$EVIDENCE/live" \
  > "$EVIDENCE/investigation.log" 2>&1
