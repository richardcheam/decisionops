# Manual operator sources — consumed historical run; no new authorization

Richard executed the archived predecessor once. These relocated sources were not
run during wrapup. Original consumed attempt markers remain in place; do not delete
them or recreate the old budget to obtain another run. See the
[maintainer index](../../docs/ARCHIVE.md#project-history) for historical results.

## Check the configuration offline

From the checkout root with the locked Commerce dependencies installed:

```bash
PYTHONPATH="$PWD" .venv/bin/python -B scripts/commerce_decisions_operator/verify_config.py
```

The verifier reads the adjacent [Decisions configuration](api-decisions-proposed.json)
and checks its approved document hash and budget caps without opening an API client.

## Historical operator procedure

Only after Richard issues a new RUN LIVE TEST for the Decisions configuration:

```bash
cd /home/richard/projects/decisionops/runs/worktrees/stage5-correction
bash scripts/commerce_decisions_operator/prepare.sh
# PAID STEP: exactly one investigation; external terminal credential only.
bash scripts/commerce_decisions_operator/run-once.sh
# After it returns; save full JSON/SQL evidence before removing tmpfs container.
bash scripts/commerce_decisions_operator/cleanup.sh
```

The runner checks configuration and uses an atomic single-use marker. A hash alone
is reusable and is not a per-run authorization token. Never delete the marker or
replace an existing budget to retry. The prepare script also refuses existing output
so old evidence is retained. Failures stop; no model substitution, automatic resume
or second investigation. The kit is confined to decisionops-decisions-live on port
55446 (commerce_decisions_test/commerce_decisions). Never run it while the separate
decisionops-decisions-tests verification container occupies that port.

All outputs go to runs/decisions-manual-evidence. They do not exist until authorized
execution. CLI exit 0 may mean review rather than a proposal; inspect the outcome.
No credentials in configuration or files. $0.03 money cap, at most 12 requests,
$0.00245760/request reservation, $0.02949120 maximum at standard global input-only
pricing, no SDK/transport retries; existing 20-second decision/240-second run caps.

Only shell/Python syntax and offline configuration verification were checked when
preparing this kit. Database startup/seed/live/cleanup commands have NOT run.
