# Specialist candidate verification

All executions below are agent-executed locally on 13 November 2026. CI/publication,
live multi-agent providers, models and fresh uncached hosts were not executed.
Baseline: d62d5795d534d441e862605fded31066d3fe2b3a. Worktree: runs/worktrees/multi-agent,
branch feat/commerce-multi-agent. Original application/projects were not restarted,
migrated or reseeded. New demo project: decisionops-multi-agent-demo, loopback8123,
internal PostgreSQL database portfolio, separate portfolio_pgdata volume. Tests used
only decisionops-specialists-test, loopback55548, database/user specialists_test.

| Local check | Actual result | Saved output under runs/multi-agent |
| --- | --- | --- |
| Pure specialist contracts/results | 8 passed | contracts-final.log |
| Focused PostgreSQL specialist boundaries | 18 passed, zero skips | focused-final.log |
| Required PostgreSQL profile | 212 passed, zero skips | postgres-release.log |
| Legacy staff rules/mocked Decisions | 13 passed, zero skips | staff-regressions.log |
| Dependency-free CI-equivalent | 236 passed; 297 optional skips; 533 collected | dependency-free-release.log |
| Frozen eligibility cases | 12 passed, zero provider calls | frozen-regression.json |
| Real staff browser, mocked specialists | 3 passed, zero skips | browser-clean.log / browser-clean |
| Locked TypeScript/Vite build, network disabled | Passed | frontend-build-corrected.log |
| Actual investigator container stop/reclaim/restart | Proposed;7 reads;3 calls;0 duplicate dispatch;no approval/execution | clean-worker-restart.log |
| Clean-checkout release | Passed; fresh-volume0009, build/health/stop/restart,3 browser passes,worker recovery | clean-*.log / browser-clean.log |

The dependency-free optional skips include PostgreSQL and unavailable optional runtime/
ML packages; the full reasons remain in its log. They do not count as DB/browser passes.
The focused18 include real graph interruption, concurrent reservation/claim, wrong case,
wrong tool/missing dependencies, case changes, stale/conflicting evidence, late admission,
interrupted read audit, parent caps, request replay/coalescing, and trace redaction.
The final profile includes all18 plus the relevant legacy execution/provider/session
regressions. No browser benchmark/evaluation was rerun.

## Same-input comparison and traces

`commerce_specialists_walkthrough.py` migrated/seeded an owned disposable schema in the
verified test DB, compared the existing fixed-order adaptive rules controller with the
new mocked specialists on the same uncompensated ORD-1042 request, then separately
approved/executed one fictional replacement. Summary: walkthrough-release/summary.json.
Both paths:7 applied policy-visible reads,8 decisions,7/7 mandatory conditions,valid
proposal. Existing private safety SQL is additional and never a policy observation.
One local measurement: fixed-order783ms; specialist1660ms; recovery2101ms. These include
local schema-loaded mocked work/checkpoints and concurrent test load; no latency or
business-value advantage is established. Specialists remain opt-in.

Unavailable Shipment:4 reads/4 established facts retained,6 decisions,review with
loss/history/stock unknown,no proposal. Recovery retains four committed observations
and finishes with7 reads. Explicit execution invoked twice after exact approval creates
one replacement. This is deterministic integration evidence,not live model performance.

Final redacted traces are success.json,partial-failure.json,recovery-before.json and
recovery-after.json under walkthrough-release. The real restart trace is under
clean-worker-restart/trace.json. Screenshot paths:
browser-clean/multi-agent-results/specialists-proposal.png and specialists-incomplete.png.

## Retained failures and corrections

- Initial walkthrough executed ORD-1042 before comparing recovery on that same order.
  Compensation then correctly blocked another proposal. Preserved walkthrough.log and
  walkthrough/*.json; corrected sequencing compares before explicit execution.
- An ad-hoc direct Compose reset omitted required COMMERCE_PORTFOLIO_PASSWORD and failed
  before deleting data. The later restart rehearsal therefore correctly reported the
  existing compensation blocker. Retained task-demo-reset.log,worker-restart.log and
  fictional SQL export/hash. The wrapper now owns environment mapping and requires
  an explicit project-name confirmation for reset. Fresh-volume restart passed.
- Ad-hoc frontend verification initially omitted index.html; Vite failed to resolve
  its entry. Retained frontend-build.log. The corrected complete-copy verification
  and actual network-disabled Dockerfile build pass; no dependency was changed.

Independent Codex source review challenged false proposals,cross-case evidence and
restart duplication. Material findings were fixed and regression-tested: exact result
binding; settled-call reuse; reclaimed-only recovery; bounded current-lease checkpoint
SQL; redacted traces; late interrupted-read audits. Final reviewer found no remaining
P0/P1 acceptance blockers. This review is source review,not supervisor or CI execution.

See [MULTI-AGENT.md](MULTI-AGENT.md) for operation,framework ownership and limitations.

## Clean-checkout rehearsal and source identity

Implementation commit: `1240345fa37a72f5409b4fb3e88a1719e16ce041`. A new detached
worktree at exactly that commit was clean before and after the rehearsal. Used existing
cached app/browser/nginx/PG images only, network-disabled builds and `--pull never`.
Fresh-volume preflight established no task volume existed. Init created/migrated/seeded
only the new project: `portfolio|portfolio|0009|0|0` (database,user,revision,cases,calls).
No pre-seeded database,private env file or provider credential was needed.

From that clean source, actual worker restart retained2 order observations,completed
with7 reads/3 specialist calls/0 duplicate dispatches and no approval/execution;44.01s
including the intentional31s lease wait. The3 real browser tests then passed in18.1s,
including double-click,same-ID replay,different-ID coalescing,stale submission,refresh,
exact approval/separate execution confirmation and one fictional replacement. Runtime
implementation,migration and lock hashes equal the committed source; see
runtime-source-equality.json. Final trace serialization's consistent read snapshot was
also checked by2 focused PostgreSQL tests (final-trace-check.log).

`stop` removed only task containers/networks and retained the task volume. Restart kept
its one replacement and operation. Fictional test records were exported before an
explicit operator-controlled reset. The demo was left freshly seeded (0009,zero cases,
zero replacements) for Richard to try. The disposable PostgreSQL test project and clean
rehearsal worktree were then removed; the implementation branch and all earlier worktrees
remain. All actions here were agent-executed,not Richard or an independent supervisor.

Public CI was not triggered because publication was prohibited. Historical viewer,
browser benchmark,live providers and fresh uncached host image retrieval remain
unexecuted; no inference quality/hosting claim follows from the local rehearsal.
Both historical live ledgers and live002/A1 hashes match their preserved checkpoint
values (preserved-live-hashes.txt). Frozen cases/grader/locks and approval/execution
implementations were not changed.
