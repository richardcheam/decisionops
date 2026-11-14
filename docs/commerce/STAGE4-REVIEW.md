# Stage 4 review: bounded reusable local sessions

Stage 4 only, pending supervisor review. Stage 5 is not implemented or executed.
Accepted Stage 3 baseline: `5ecee30fdcead58a97402af624984f6bab0b429c`, preserved
unchanged on feat/commerce-adaptive-recovery in adaptive-recovery. Stage 4 worktree:
`runs/worktrees/adaptive-sessions`, branch `feat/commerce-adaptive-sessions`.
Initial origin/main was `b27e2d7cda764ef6e52f99eff3e5a9f30a45d0f5`. The accepted
snapshot, rather than main's older feature set, is this patch's reconstruction base.
Contract frozen before implementation in `04c4809480836cded65e7a72f85388e6b006406c`.
Verified implementation snapshot: `5a9b67f64cbd3b11d8e8051cb7d11c30f7907fa0`;
subsequent local commit records only documentation/CI results. The review archive
manifest identifies the final full HEAD and every changed file.

## Behavior and compatibility

An explicitly opted-in adaptive job can own one CPU-only, batch-one local family
child and reuse it for serialized decisions. New pure transport and worker modules
keep model imports outside routine execution. Session accounting reserves preload
separately, records wait/load/inference/total, renews only live job ownership, and
retains unknown reservations. Migration 0008 is additive after actual 0007.
No database transaction or business lock spans child work. Model metadata stays
outside the six permitted policy feature fields. Native choice indexes are mapped
then passed through existing deterministic validators. Forced actions skip loading.

Browser/API/ordinary workers remain rules-only. Legacy one-shot and two-choice
routing files and validators remain compatible. Approval, v1 attestation, private
safety validation, execution/reconciliation and Stage 2 admission/publication
protections remain authoritative. Graph checkpoints carry committed phase
projections, never runtime events, child handles or ownership tokens. Session ticks
run before opening the projection saver so legitimate renewals update its deadline.

Full framing/resource/recovery decisions are in
[the frozen contract](../superpowers/specs/2026-10-14-adaptive-commerce-stage4-contract.md).
32 KiB input frame, 64 KiB output frame; entire-session stdout/stderr each 64 KiB,
not per response. stdin <=589,896, output <=131,072, duplex <=720,968 bytes.
At most three sessions/run; resource reservations and known phases plus decisions
<=240,000ms. Slot <=30s, preload <=120s, decision <=20s, immutable run <=240s.
No API charge or token usage is invented. Real checkpoint code is present but unrun.

## Actual local verification (agent executed)

Working directory: `/home/richard/projects/decisionops/runs/worktrees/adaptive-sessions`.
No dependency installation or upgrades. Existing interpreter:

```bash
export COMMERCE_TEST_PYTHON=/home/richard/projects/decisionops/runs/worktrees/local-providers/.venv/bin/python
export COMMERCE_TEST_DATABASE_URL='postgresql+psycopg://commerce_stage4:stage4-fictional-only@127.0.0.1:55440/commerce_stage4_test'
"$COMMERCE_TEST_PYTHON" -B -m unittest discover -s tests -p test_commerce_sessions.py -v
"$COMMERCE_TEST_PYTHON" -B -m unittest discover -s tests -p test_commerce_adaptive_sessions.py -v
"$COMMERCE_TEST_PYTHON" -B scripts/commerce_ci_tests.py postgres
python3 -B -S scripts/commerce_ci_tests.py dependency-free
"$COMMERCE_TEST_PYTHON" -B scripts/commerce_session_walkthrough.py
```

| Check | Actual result | Retained output |
|---|---|---|
| Fake transport | 14 passed | session-final-14.log |
| Focused PostgreSQL sessions | 14 passed, zero skips | database-final-14.log |
| Required PostgreSQL profile | 189 passed, zero skips; schema matches migration | postgres-final.log |
| Dependency-free profile | 367 collected, 176 passed, 191 explicit skips; zero errors/failures | dependency-free-final.log |
| Fake CLI success and uncertainty/recovery | Both reached proposed, all children reaped; stock unchanged | stage4-session-r28pstyu/ |

The dependency-free skips are 189 opted-in PostgreSQL tests plus two optional Laya
package-API tests. They do not replace the separately executed required database
profile. Browser and real model checks were **not run**. No held-out quality,
performance or business-value claim follows from fake scores.

The required profile also executes legacy approval/execution/provider, SQL binding,
Stage 2 terminal/admission, Stage 3 lease/accounting/replay and real checkpoint-lock
regressions. Existing one-shot subprocess/adapter tests run in the dependency-free
profile. Exact unittest output and skip reasons are included, not inferred from CI
configuration.

### Isolated database reproduction and cleanup

Only a new ephemeral container was started. Existing cached image; no pull:

```bash
sg docker -c 'docker run --name decisionops-adaptive-stage4-tests --pull never --memory 512m --cpus 2 --tmpfs /var/lib/postgresql/data:rw,size=512m -e POSTGRES_DB=commerce_stage4_test -e POSTGRES_USER=commerce_stage4 -e POSTGRES_PASSWORD=stage4-fictional-only -p 127.0.0.1:55440:5432 -d postgres@sha256:0ea6700a3b4f0ae6ce746519073558aed4d88a79d8d07622a9a644946c7319c4 -c shared_buffers=32MB -c max_wal_size=64MB -c min_wal_size=32MB -c checkpoint_timeout=30s'
sg docker -c 'docker exec decisionops-adaptive-stage4-tests pg_isready -U commerce_stage4 -d commerce_stage4_test'
```

Wait for accepting connections; verify the JSON database identity and container
port before tests. The required fixture creates/migrates/seeds/drops disposable
schemas; the walkthrough additionally drops its checkpoint namespace. An initial
connection attempt before readiness failed; database-not-ready.log preserves it.
After final checks the agent removed only this named tmpfs container with
`sg docker -c 'docker rm -f decisionops-adaptive-stage4-tests'`.
No persistent volume was attached. Database final inspect reports OOMKilled=false.
Before/after container inventory, database identity and cleanup output are retained.
The original four container identities and migration-0004 volume were untouched.
All accepted worktrees and historical artifacts remain; canonical handoff is still
untracked and preserved. No original database migration/restart/seed occurred.

## Fake trace and recovery evidence

Saved CLI commands/stdout/stderr plus session rows, immutable phase events and call
records are in `runs/stage4-session-r28pstyu`. Success: seven reads, eight decisions,
one session/load, no uncertain calls or duplicate dispatch, proposed without
execution. Parent waiting 14ms, load 46ms, inference 9ms, session total 1491ms and run
wall 3820ms; child native fake load 0ms, peak_rss_kib 103580. These are measured
**fake process** resources, not cached model measurements. Total is not double-charged.

Wrong-correlation response: one dispatched unknown call, reservation retained,
owned process reaped. Explicit current-token recovery followed by token resume
uses fixed-policy fallback: nine total decisions, seven reads, one session/load,
one uncertain call retained, zero duplicate dispatches, proposed. Stock remained
on_hand=10, reserved=1. Nothing approved or executed a replacement.

## Review map

| Acceptance boundary | Implementation | Existing verification |
|---|---|---|
| One preload, serialized decisions, feature-only model text | session_protocol.py; session_worker.py LoadedModel; adaptive_sessions.Adapter | test_two_decisions_use_one_load_and_no_audit_features; test_success_has_one_persisted_preload_and_many_decisions |
| Frame and cumulative limits; wrong/truncated frames | session_protocol._drain/_exchange | frame/both overflow, cumulative_stdout, malformed, exited-buffered-stderr, exit-surplus tests |
| Bounded cleanup/descendant/parent loss | Session._kill/close; child watchdog | descendant_pipes; parent_loss_watchdog; deadline tests |
| Preload/decision/run/lease and shutdown | adaptive_sessions heartbeat/scope; adaptive_worker; adaptive_workflow.resume | actual plain/once/token SIGTERM tests; lease_loss; preload_outlasts_original_lease |
| Durable uncertainty/reloads/resource cap | migration 0008; adaptive_sessions.reserve/recover; adaptive_accounting.prepare | unknown_preload; mismatched_decision; restart known-result/count-reload; phase_and_decision_resources |
| No load for forced actions; pins historical | Adapter.choose; Config.admit; records | forced_action; historical_session_inspection |
| Legacy deterministic and one-shot compatibility | untouched read/approval/execution/local_provider paths | full required PostgreSQL and dependency-free profiles |

### Retained failures and source review

A fresh source-only reviewer found (1) frozen checkpoint lease across long valid
preload, (2) a known error overwritten by immediate child EOF, (3) unknown preload
pause hidden by graph iteration and (4) buffered tail lost after child exit.
Focused PostgreSQL review-database-red.log reproduced the first/third; green passes
both. review-pipe-red-2.log reproduced the second, followed by green. The original
buffered-exit stress test passed even before the fourth correction; it is not
claimed as a red reproduction. A deterministic socket-backed regression now
proves all 65,537 stderr bytes are consumed after direct-child exit and detects the
proof byte, retaining 1,024. Final source-only refresh found no material findings;
reviewer ran no tests, models or runtime operations.

Earlier staged failures (missing module, diagnostic NUL encoding and missing
permanent fallback) and intermediate results are retained in the local bundle.
Only final logs establish current verification. A shell invocation using missing
`python` failed before editing; the edit was applied with python3 and all final
checks rerun. No failed result is presented as success.

## CI and limitations

CI source-only SHA: `57a6baa048c64796f4534c26b25b9d359a7b1eec`, branch
feat/commerce-adaptive-sessions. [Workflow run](https://github.com/richardcheam/decisionops/actions/runs/38624510630).
Both configured jobs actually executed successfully: dependency-free job 116060136064
ran 367 checks, 176 passed and 191 explicitly skipped; PostgreSQL job 116060135554
ran 189 checks, all passed, zero skips. Full decoded job logs and job/step conclusions
are included as ci-dependency-free.log, ci-postgres.log and ci-jobs.json. Locked
commerce-profile installation executed in CI; no optional model packages/checkpoints
were loaded. Browser remains unexecuted. Source identity is
verified against the local source/migration/test/workflow tree; local documentation
is intentionally absent from the public CI mirror. No rejected documentation
upload was repeated. GitHub commit metadata uses the connected account; execution
and authorship attribution remain agent-assisted, not Richard-run verification.

Real Laya/GLiClass loads, model memory/latency/performance, optional package/API
compatibility under real weights and frozen comparison remain Stage 5. Host lock
coordinates cooperating current-user adaptive sessions only, not external/legacy
processes. No idle daemon, supervisor, model training or production rollout exists.
No paid calls, downloads, dependency upgrades, AWS, browser/default-path changes or
original-runtime operations. Stage 4 stops here for source review; do not merge.
