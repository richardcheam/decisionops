# Local specialist evidence index

Evidence root: `runs/multi-agent/` in the `feat/commerce-multi-agent` worktree.
This directory is intentionally ignored. No evidence was uploaded or sent to telemetry.
The local review archive contains the patch, changed files, safety-code context,
authoritative redacted traces, screenshots and exact verification outputs.
`evidence-manifest.json` records original relative paths and SHA-256 hashes, including
retained negative outputs and fictional SQL exports that remain local only.

Implementation/rehearsal source: `1240345fa37a72f5409b4fb3e88a1719e16ce041`.
Baseline: `d62d5795d534d441e862605fded31066d3fe2b3a`.
Final handoff commit changes documentation only relative to the tested implementation.
`runtime-source-equality.json` confirms the running code, migration and lock hashes.
All new verification was agent-executed. No Richard/supervisor/live-model result is
attributed to these new tests. CI was not executed.

| Evidence | Authoritative location |
| --- | --- |
| Same-input rules comparison, success, partial failure, recovery | `walkthrough-release/summary.json`, `success.json`, `partial-failure.json`, `recovery-before.json`, `recovery-after.json` |
| Actual clean-release worker restart | `clean-worker-restart.log`, `clean-worker-restart/trace.json`, before/paused/after JSON |
| Staff browser assertions and screenshots | `browser-clean.log`, `browser-clean/multi-agent-report.json`, `browser-clean/multi-agent-results/specialists-proposal.png`, `specialists-incomplete.png` |
| Required PostgreSQL profile | `postgres-release.log`:212 passed,0 skips |
| Focused specialist failures/races | `focused-final.log`:18 passed,0 skips; `final-trace-check.log`:2 passed |
| Legacy rules and mocked Decisions staff behavior | `staff-regressions.log`:13 passed,0 skips |
| Pure specialist contracts | `contracts-final.log`:8 passed |
| Dependency-free profile | `dependency-free-release.log`:236 passed,297 optional skips; reasons retained |
| Frozen historical eligibility regression | `frozen-regression.json`:12 passed,no inference |
| Clean build/start/readiness/stop/restart | `clean-build.log`, `clean-start.log`, `clean-health.log`, `clean-db-readiness.log`, `clean-stop.log`, `clean-restart.log`, `retained-data.log` |
| Fresh-checkout/source identity | `clean-checkout-source.txt`, empty `clean-checkout-status.txt`, `fresh-volume-preflight.log`, `runtime-source-equality.json` |
| Ready-to-try new demo | `demo-ready-health.log`, `demo-ready-db.log`:0009,0 cases,0 replacements |
| Preserved historical live trace equality | `preserved-live-hashes.txt` |

Retained procedural failures: `walkthrough.log` and `walkthrough/` (comparison after
prior compensation); `task-demo-reset.log` and `worker-restart.log` (missing direct
Compose password mapping retained old test data); `frontend-build.log` (incomplete
ad-hoc copy). Corrections and their later passing outputs are explained in
[MULTI-AGENT-VERIFICATION.md](MULTI-AGENT-VERIFICATION.md). These failures were not
removed, relabeled as passes, or used to weaken business validation.

The local fictional SQL exports preserve task-created records before explicit resets.
They are not required to launch the demo and are excluded from the attachable review
archive. No original application data, model weights, caches, environments or credentials
were copied. The original live traces remain in their original worktrees, unchanged.

Use [MULTI-AGENT.md](MULTI-AGENT.md) for the walkthrough,commands and limitations.
