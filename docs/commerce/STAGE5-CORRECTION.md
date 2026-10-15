# Stage 5 bounded correctness correction

Base:3523244bd7a61101deae01950b447b08626b5363 (prior blocked Stage5 snapshot).
Branch fix/commerce-stage5-correctness, worktree runs/worktrees/stage5-correction.
Accepted Stage4 d3c3896 and its archive, the prior Stage5 archive, frozen19 fixtures,
16 replay inputs,152 descriptive groups,57 verified pairs and9 retained attestations
are unchanged. No baseline, native pilot, comparison or replay was run here.

## Source contract and application change

The current source maps case_revision (0006), durable jobs/accounting (0007) and
session records (0008). Its release schema contract is exactly one Alembic revision
row **0008**, not0005, a lower bound or any arbitrary future revision. Health now
calls the read-only schema_readiness validator. It checks mapped table/column names,
PostgreSQL type family, nullability, bounded string length, decimal precision/scale
and required enabled mutation guards bound to their expected function names.
Unbounded PostgreSQL text/varchar are explicitly compatible; a text case_revision
is not. Trigger enablement must apply to normal writers (O or A).

Missing/empty/multiple, old0005/0007 and unsupported0009 revision markers fail503.
Missing/incompatible mapped columns, absent revision table and disabled required
guards fail closed. Health returns the unchanged fictional_store_rules mode only
when the contract passes. It performs no DDL, migrations, seed or case mutation.
This is an explicit compatibility/readiness contract, not a complete adversarial
schema-definition/function-body integrity attestation. SQL errors remain503 without
exposing database internals to staff. New-source deployment requires an explicitly
prepared0008 environment; the original running0004 application is not upgraded.

Application changes are limited to this health validation and updating the closed
native-evaluation CLI's diagnostic text to say supervisor review is required.
Provider dispatch, budget settlement, adaptive admission, cancellation, leases,
publication, checkpoint recovery, approval and execution implementations are unchanged.
No migration, dependency, timeout cap or default-mode change.

## Durable diagnosis and reached boundaries

See correction-verification/diagnosis-original-valid.json,
diagnosis-original-complete.json and durable-boundary-summary.json for absolute
request/run deadlines, lease_until, database time, request/result/error, token,
context/revision, dispatch_count and final case state. The observer only appends
in-memory boundary data during calls and snapshots SQL rows before fixture cleanup.

| Boundary | Evidence and disposition | Correction |
|---|---|---|
| Expired before provider claim | Original50ms request sometimes expired during reservation/commit; dispatch_count0, settled, actual_cost0, deadline_before_dispatch | Separate known-zero test verifies adapter cannot run; do not demand uncertainty |
| Actually dispatched without known result | Another original run reached count1; unknown usage retained | Held fake signals actual choose entry and blocks until deadline; count1/uncertain/retained reservation, then late completion cannot redispatch |
| Staff changed before adaptive admission | Original sleep150ms sometimes preceded claim: reserved/count0, Stale dispatch context | Explicit preclaim barrier escalates before release; asserts rejected admission, count0, no adapter, staff state preserved |
| Staff changed/cancelled during work | Old sleeps did not prove dispatch | Event proves count1/dispatching before real staff approval+execution or operator cancel; cooperative fake is cancelled; reservation uncertain, staff executed case preserved |
| Lease expired before checkpoint SQL | Original1s lease began before setup/domain work; LeaseLost at graph entry instead of intended checkpoint lock | Normal current lease through setup; explicit checkpoint query event, actual pg_stat_activity Lock wait; stricter1s saver budget clamped to original end, existing1.4s bound retained |
| Terminal job repair | Original1s renewal preceded final expensive publication | First prove publication committed and fault-after-application reached; only then expire test owner via SQL and resume; no duplicate proposal/counter/dispatch |

The changed test deadline is a request fixture (2s inside existing production caps),
not an increased production cap. Read-lock1s is a smaller checkpoint-local budget
inside the valid job/run bound. Test-only SQL expiry shortens an already-owned
lease after proving a committed effect; it never resets counters or grants authority.

The first required-profile run after these fixes found three more setup races:
1. A1s carrier-policy fixture could expire while collecting7 tools. Corrected unit
   fixture allows30s collection, proves fresh complete evidence, then moves only
   the test clock just past the recorded carrier expiry but before run deadline.
   No immutable observation, frozen evaluation fixture or production lifetime changes.
2. Operator cancellation's200ms sleep could still precede dispatch. It now waits
   for actual fake choose entry/count1 before cancellation.
3. The checkpoint-write test's1s lease could expire before publication. It now
   proves the proposal committed, takes the real checkpoint lock, then applies a
   stricter1s saver bound. The existing1.5s assertion measures that checkpoint
   phase; full projection wall time is separately reported (not hidden).

Original failed profile and dedicated before/after diagnosis of these three remain
available. There are no weakened ownership/freshness predicates or removed safety
assertions. A diagnostic-only first attempt mistakenly serialized a dataclass with
dict(); that observer run is retained but not used as valid product evidence.
Corrected observers preserve original return objects and values. A checkpoint query
observer initially mismatched SQL case; its failed boundary assertion is retained.
Both issues were in test/diagnostic tooling, not silently repaired application paths.

The next full profile reached192/194 with no skips. Its publication-expiry test
renewed a1s lease before safety work and raised QueryDeadline before the intended
final fence. It now expires only the test owner in the transaction after publish
returns, asserts LeaseLost/rollback, then explicitly expires the rolled-back owner
for new-owner replay. The focused corrected test passed. A once/SIGTERM subtest
failed to reach dispatch within6s (call None); an isolated rerun passed. Diagnostic
output now captures stdout/stderr and durable job/run/session/call when that
boundary is not reached; no production timing or model cap was changed.
The initial once boundary miss had no persisted diagnostic snapshot before test
cleanup, so its root cause is not claimed established by the isolated pass. This
remains an explicit diagnostic limitation; later green runs do not erase it.

The following profile reached193/194, no skips, and reproduced the token variant
with durable phase data. Job/run creation23:15:21.987822Z preceded session reserve
at23:15:27.653849Z (5.666s). At the test's6s signal the child had emitted readiness,
loaded in228ms, sent only the preload input frame, performed0ms inference and was
reaped. Run/lease deadlines were still current. Thus the6s test setup cutoff was
not a decision deadline; it stopped work before the intended decision boundary.
The first diagnostic retained the last-polled call=None rather than querying it
again after stop, so its final ledger state/count is **not inferred** as zero.
The diagnostic now rereads that row after stop.

The corrected test synchronizes on durable state=dispatching/count1 **and** a ready
session before SIGTERM. Its setup wait uses existing slot/preload/decision maxima,
clamped to the immutable run deadline, and exits on process/session/known-call
failure. No production cap changes. It logs full call/deadline/binding evidence
when reached, then retains the original uncertain/no-usage/no-tools/reaped-child
assertions. Both once and token variants passed the focused regression. The old
6s failures remain retained, not replaced by this result.

## Verification

All commands below were agent executed in only the verified correction database:

```bash
export COMMERCE_TEST_PYTHON=/home/richard/projects/decisionops/runs/worktrees/local-providers/.venv/bin/python
export COMMERCE_TEST_DATABASE_URL='postgresql+psycopg://commerce_correction:correction-fictional-only@127.0.0.1:55443/commerce_stage5_correction'
"$COMMERCE_TEST_PYTHON" -B scripts/commerce_correctness_diagnose.py --include-admission
"$COMMERCE_TEST_PYTHON" -B scripts/commerce_correctness_diagnose.py --extra-boundaries
PYTHONPATH=tests "$COMMERCE_TEST_PYTHON" -B -m unittest test_commerce_api.APITests.test_health_accepts_current_0008_schema_without_migration test_commerce_api.APITests.test_health_fails_closed_for_missing_old_new_and_multiple_revisions test_commerce_api.APITests.test_health_rejects_missing_or_incompatible_required_schema -v
"$COMMERCE_TEST_PYTHON" -B scripts/commerce_ci_tests.py postgres
```

The initial pre-fix health test failed503 versus expected200 (readiness-red.log).
Final focused health3/3 and synchronized boundary6/6 passed; additional boundary3/3
passed. Real checkpoint read lock timed out around1.05s; post-commit write around
1.02s, full projection2.35s. These are local fake/test measurements, not models.

Final current-source verification, all agent-executed:

| Check | Actual result | Raw evidence |
|---|---|---|
| Required PostgreSQL profile | **194/194 passed,0 failures/errors,0 skips**,119.454s | postgres-required-phase-corrected.log |
| Dependency-free profile | **186 passed**,0 failures/errors;196 explicit skips (194 opt-in PostgreSQL,2 optional Laya API tests) | dependency-free-final.log |
| Browser workflow | **6/6 passed**,0 skipped/flaky/unexpected;22.038s | browser-tests.log and browser-summary.json / full Playwright JSON |
| Focused readiness |3 passed,0 skips | readiness-final.log |
| Focused durable boundary set |6 passed,0 skips | diagnosis-synchronized.log/json |
| Additional expiry/cancel/checkpoint set |3 passed,0 skips | diagnosis-extra-corrected.log/json |
| Publication expiry and replay |1 passed,0 skips | publication-expiry-final.log |
| Actual once/token SIGTERM |1 test /2 subcases passed,0 skips | session-phase-synchronized.log |
| Current frontend build |Passed offline, cached lock matches current SHA256 | frontend-build-final.log / cached-browser-lock.sha256 |
| Current-source public CI |**UNEXECUTED**, recorded approval-review rejection; no retry | publication inventory is proposed only |
| Native inference / corpus reruns |**0 /0** | Frozen files and previous archive hashes verified unchanged |

The actual browser assertions executed: stale dialog could not approve; fresh exact
approval created one verified replacement/one executed event; incomplete history
remained unknown with no approval control; insufficient stock remained a false
condition; selection/error/credential handling passed. Isolated SQL showed schema0008,
one operation and one executed case. Rules-only health returned200. This browser
run used the same corrected API source; later changes were test/diagnostic/docs only.
No fresh historical viewer run was needed for this bounded correction; its prior
results are retained, not claimed as a new run.

Full raw logs, intermediate failures, durable JSON, commands and browser artifacts
are in the correction bundle. Earlier negative outputs remain unchanged. An earlier
profile passed191/194 with1 failure/2 errors before the extra setup corrections;
that output is not the final result. Nothing was skipped to make a required profile
green. No frozen evaluation was regenerated to package evidence.

## Operational scope, publication and review gate

Only new disposable correction resources: PostgreSQL commerce_stage5_correction
on loopback55443 (user commerce_correction); browser project
 decisionops-stage5-correction-browser on55444/8083 with its own network/tmpfs DB.
Cached images and existing locked environments only; current frontend is built
from source using cached packages with networking disabled. No downloads/upgrades.
Original containers/volume/worktrees were not restarted, migrated, seeded or modified.

Public CI remains UNEXECUTED under the recorded approval-review rejection. No remote
upload/ref update was retried and rejected artifacts are not omitted as a workaround.
The proposed publication inventory lists exact bytes, SHA256/Git blob IDs, source
HEAD and public base, including the previously rejected enumeration unchanged.
Inventory is a review artifact, not permission to publish. Complete docs remain local.

Stage5 remains pending supervisor review and native work remains explicitly closed.
Readiness/corrected local checks are not native model evidence, production rollout
or proof of business value. Exact human approval/generation/proposal/hash binding,
deterministic execution rechecks, transaction/reservation locking, duplicate
prevention and reconciliation remain unchanged. No merge, release, paid calls or AWS.

Attribution: all correction commands/tests/browser execution are agent-executed.
Richard supplied no new personally executed commands. Fresh reviewer inspected the
initial readiness/synchronization source only and ran no tests or runtime operations;
additional test-only boundary corrections were author-verified. Prior supervisor
scope remains as recorded in STAGE5-REVIEW.md; no independent corrected-PostgreSQL,
browser or native verification is attributed to that supervisor.
