#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
export COMMERCE_DATABASE_URL='postgresql+psycopg://commerce_decisions:decisions-fictional-only@127.0.0.1:55446/commerce_decisions_test'
export PYTHONPATH="$PWD"
export OPENAI_LOG=error
EVIDENCE="$PWD/runs/decisions-manual-evidence"
CONFIG='docs/commerce/examples/api-decisions-proposed.json'
APPROVED_HASH='b318cc81100b474bf1cad6815bd9ed8f39a064db9f1cdf55debff8eb2a54da09'
