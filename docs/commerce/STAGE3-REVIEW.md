# Stage 3 review gate: partitioned adaptive recovery and accounting

Accepted Stage 2 snapshot: e8a980457d6260afb779194be95556cdd4a1b363 on
feat/commerce-adaptive-core. Stage 3: feat/commerce-adaptive-recovery, isolated
adaptive-recovery worktree. Fetched origin/main remains b27e2d7. No Stage 4 work.

[Resolved contracts](../superpowers/specs/2026-10-14-adaptive-commerce-stage3-contract.md)
cover queue namespaces, lock order, lease/deadline fences, immutable bindings,
resource accounting and recovery. [RUNBOOK](RUNBOOK.md#stage-3-opt-in-adaptive-worker-and-recovery)
contains exact startup/inspection/recovery/shutdown commands.

## Changes and acceptance map

- 0007 adds separate adaptive jobs, task-specific calls and immutable call events;
  0006 and historical v1 validation remain unchanged. Legacy claim filters are
  explicit; ordinary worker/browser/API stay bundled rules-only.
- Scheduled runs bind an immutable executor namespace. Admission, actual selected
  SQL and publication inherit remaining lease/run limits. Token-fenced renewal
  cannot revive expiry or extend the run. Staff generation/revision/context and
  pending-token protections remain; late reads are discarded audit.
- Fixed/cue/fake recommendations reserve the original decision counter before
  dispatch. Known results settle actual fake-adapter milliseconds and exact zero
  API charge. Unknown dispatches retain count/resource reservations. Explicit
  recovery permits separately counted fallback; no automatic redispatch.
- Separate LangGraph schema/thread projects PostgreSQL committed steps/reservations.
  Checkpoint loss/replay cannot repeat settled effects or reset counters. Terminal
  completion repair after expiry is metadata only, even at the claim cap.
- Tests in test_commerce_adaptive_jobs.py cover 21 recovery/fencing cases: concurrent
  claim/reservation/renewal, restart at reservation/dispatch/result/application,
  checkpoint loss, lease-expired reads/publication, stale-token writes, cancellation,
  concurrent staff approval/execution, expired recommendation admission, unknown
  resource exhaustion, read retry provenance and shutdown authority. Pure typed
  contracts/cancellation have two dependency-free tests. Required profile includes
  existing Stage 1/2, approval/execution, API/job/provider-routing regressions.

## Agent-executed local checks

Working directory: /home/richard/projects/decisionops/runs/worktrees/adaptive-recovery.
Existing commerce-only interpreter, no install or dependency changes:

```bash
export COMMERCE_TEST_DATABASE_URL='postgresql+psycopg://commerce_stage3:stage3-fictional-only@127.0.0.1:55438/commerce_stage3_test'
/home/richard/projects/decisionops/runs/worktrees/local-providers/.venv/bin/python -B -m unittest discover -s tests -p test_commerce_adaptive_jobs.py -v
/home/richard/projects/decisionops/runs/worktrees/local-providers/.venv/bin/python -B scripts/commerce_ci_tests.py postgres
python3 -B -S scripts/commerce_ci_tests.py dependency-free
/home/richard/projects/decisionops/runs/worktrees/local-providers/.venv/bin/python -B scripts/commerce_adaptive_recovery_walkthrough.py
git diff --check
```

Final required PostgreSQL: 169/169 passed, no failures/errors/skips; includes all
21 Stage 3 tests. Metadata check reports no upgrade operations. Dependency-free:
333 collected, 162 passed, 171 explicitly skipped (optional SQLAlchemy/PostgreSQL
checks and two optional Laya-package checks). CI requires the separate PostgreSQL
profile to execute; configured jobs are not evidence of execution.

CLI walkthrough: seven reads/eight decisions -> proposed, job completed, still
awaiting exact staff approval. Injected dispatch crash -> outcome-unknown;
explicit recover retains one uncertain reservation and records fixed fallback;
seven reads/nine decisions -> proposed, no duplicate dispatch. Exported CLI commands,
complete run/call/event traces: runs/stage3-recovery-ut5oxvmr. These are model-free
integration evidence, not model quality or business-value measurements.

Fresh source review identified six material issues, all reproduced with tests
(review-red.log: five failures/one error). Recheck found one worker-shutdown
operator-authority race, reproduced in shutdown-red.log and removed. Final source
recheck reported no material findings; the reviewer executed no tests/runtime.

Final verification also encountered disposable PostgreSQL OOM: default cache/WAL
inside 512MiB tmpfs/cgroup exhausted memory and the server restarted, producing
37 cascading errors. Failure/container logs are retained. Only that owned test
container was recreated with shared_buffers=32MB, max_wal_size=64MB,
min_wal_size=32MB, checkpoint_timeout=30s. Database/user/port/tmpfs and OOM=false
were reverified before successful serial tests. A historical subprocess readiness
check failed during a concurrent run; its cause was not independently established.
The eight lifecycle tests and full dependency-free profile passed serial recheck
without changing historical code. No failed result was counted as a pass.

## CI and attribution

A dedicated model-free workflow for the review branch executes dependency-free
and required PostgreSQL jobs with the existing locked commerce-only profile.
Actual review-SHA CI results are captured separately in the review archive/final
report after push. Browser CI is not triggered by this dedicated workflow; browser
checks remain unexecuted. No new personally Richard-executed command was reported.
Supervisor Stage 2 verification was patch reconstruction and mocked terminal/
admission logic only; 28 focused/148 prior PostgreSQL passes were agent-executed.
All Stage 3 local checks/traces are agent-executed; GitHub results are separate.

## Limits and next gate

Only cooperative fixed/cue/fake adapters; no model sessions, model downloads,
paid calls, AWS or new providers. Unknown decisions require explicit recovery;
read-only retries consume new attempts. A connection failure can prevent result
persistence: retain uncertainty and inspect/recover rather than redispatch.
Run expiry/claim exhaustion requires explicit operator cleanup; checkpoint repair
cannot restore expired authority. Worker stop signals do not cancel a job as an
operator. Cancellation cannot undo a proposal already committed. Additive migration
downgrade destroys adaptive audit state and is not a recovery procedure.

Only the owned port-55438 test container/schemas/checkpoint namespace were started,
migrated/seeded and removed. Original migration-0004 containers/volume, all worktrees
and historical artifacts remain intact. Stage 3 awaits supervisor review; do not
merge or proceed to Stage 4.


### Earlier publication obstacle (resolved for the source CI mirror)

Implementation commit: 5dbefbf522187c2c3ef73555b1ecf29f6bd22236. Git push
failed because its VS Code credential socket was unavailable and the repository
rejected anonymous writes. The installed GitHub connector has push permission,
but automatic approval review rejected the RUNBOOK.md blob upload to the public
repository, citing local filesystem paths, credential/configuration examples and
operational details without explicit approval of that exact payload. Comparison
with public b27e2d7 established the added credentials are fictional and no private
.env/dumps/logs are tracked; a justified retry was still rejected. Explicit public
source/runbook approval was requested. No branch/ref/commit was created remotely
and no CI job executed. Some permitted unreferenced source blobs were uploaded
without branch publication; those are not a CI run or a release.

Richard explicitly approved public source/documentation publication. Automatic
review still rejected specific documentation payloads. The safe alternative was
a source-only CI mirror: every non-docs tracked file is byte-identical to the
local reviewed tree; documentation stays complete in the local review archive.
The shell credential socket remains unavailable; publication used the GitHub
connector. GitHub-generated commit attribution reflects the connected account;
all publication and verification operations were agent-executed.

### Executed review-SHA CI

Public source review SHA: 0662d051e6be5575848771ab44c4e2bbe981df18.
[Actual push workflow](https://github.com/richardcheam/decisionops/actions/runs/38592061880)
completed successfully. Dependency-free job 115949337674: 333 collected,
162 passed, 171 explicit optional skips. Required PostgreSQL job 115949338276:
169 collected, 169 passed, zero skips; migrations/schema metadata check executed.
Saved job logs and summaries are in runs/stage3-verification/ci-*. The initial
commit-workflow helper filters to pull-request events and incorrectly appeared
to show no runs; the repository actions API confirmed this push-triggered run.
Browser checks remain unexecuted. No CI/model inference ran.

The remote mirror has different commit metadata and excludes all local docs/**
changes. `git diff --exit-code HEAD origin/feat/commerce-adaptive-recovery -- .
':(exclude)docs/**'` returned zero. CI evidence applies to that exact public
source SHA, not to the local documentation commit SHA. The full local accepted
baseline, patch, modified files, contracts and evidence are packaged separately.
Stage 3 implementation and executed CI criteria are satisfied for review;
supervisor acceptance and Stage 4 remain pending. Nothing was merged.

## Shutdown/checkpoint correction review gate

Correction baseline: 317aeb670df691e53d20d841c84dea57e326867a. Accepted Stage 2
remains e8a980457d6260afb779194be95556cdd4a1b363. Same isolated adaptive-recovery
branch/worktree; no migrations, dependencies or Stage 4 changes. Origin/main was
fetched and remains b27e2d7cda764ef6e52f99eff3e5a9f30a45d0f5.

Three implementation files change: adaptive_worker forwards the CLI stop event
through plain graph resume and reports CheckpointFailure distinctly (exit 3);
adaptive_workflow carries stop/fence only in runtime closures and bounds saver
connections/cursors/SQL; adaptive_runner rechecks stop after reservation/claim and
before launch/application. Once/token-resume projects without an additional tick,
under remaining active lease/run limits, and skips projection after shutdown.
The contract and RUNBOOK document reservation retention and recovery semantics.

Six new PostgreSQL regressions in test_commerce_adaptive_jobs.py exercise actual
plain-resume CLI SIGTERM, post-reservation/claim shutdown, real case-lock waits,
real checkpoint read/write locks and nonzero connection statement/lock settings.
A stopped undispatched reservation remains reserved; a committed dispatch marker
without a known result conservatively remains uncertain. Budgets/ownership stay
intact, no operator cancellation or automatic redispatch occurs. Checkpoint write
failure after publication preserves the proposal, applied recommendation and
counters; explicit resume rebuilds projection without repeating them.

### Agent-executed correction verification

Owned container decisionops-adaptive-stage3-correction-tests, cached PostgreSQL
image digest 0ea6700a3b4f0ae6ce746519073558aed4d88a79d8d07622a9a644946c7319c4,
loopback 55438 -> 5432, disposable tmpfs. Database commerce_stage3_correction_test,
user commerce_stage3, memory 512MiB, shared_buffers=32MB/max_wal_size=64MB.
TCP identity/port/storage and OOM=false are recorded in the correction evidence.
Each PostgreSQL test creates/migrates/seeds only its disposable schema. No runtime
migration/restart/seed was performed on the original application.

Exact main commands from the adaptive-recovery checkout:

```bash
export COMMERCE_TEST_DATABASE_URL='postgresql+psycopg://commerce_stage3:stage3-fictional-only@127.0.0.1:55438/commerce_stage3_correction_test'
/home/richard/projects/decisionops/runs/worktrees/local-providers/.venv/bin/python -B -m unittest discover -s tests -p test_commerce_adaptive_jobs.py -v
/home/richard/projects/decisionops/runs/worktrees/local-providers/.venv/bin/python -B scripts/commerce_ci_tests.py postgres
python3 -B -S scripts/commerce_ci_tests.py dependency-free
git diff --check
```

Focused final: 27 passed, zero skips (35.249s). Required PostgreSQL: 175 passed,
zero failures/errors/skips (96.266s); schema metadata check found no upgrade
operations. Dependency-free: 339 collected, 162 passed, 177 explicit optional
skips (SQLAlchemy/PostgreSQL and two optional Laya-package checks). No models were
loaded. Failure reproduction red.log: four tests/five failures, including ignored
SIGTERM, adapter-launch gap, checkpoint read waiting 2.011s past lease and zero
statement timeout. Green, focused-final and required logs are retained. Additional
real checkpoint write-after-publication test passed; read lock took 0.648s and
write lock 0.996s in the required run. Explicit recovery kept one proposal/eight
decisions/seven tools, with no repeated dispatch. No unrelated demos were rerun.

Actual corrected-source CI is recorded below after publication. Public source
mirror excludes docs/**; no rejected documentation payload is uploaded again.
Browser/optional model checks remain unexecuted. All local checks/publication are
agent-executed; GitHub account authorship is not Richard-executed verification.
Stage 3 correction awaits supervisor review; Stage 4 remains pending.

### Corrected-source executed CI and packaging

Local correction implementation commit: 4eeb4957f2eaa693a079a41a312571cd8f115096.
Public corrected source SHA: 971bd69ec7b1782d62fe4f8ed9ee3db5fc721202.
[Executed push workflow](https://github.com/richardcheam/decisionops/actions/runs/38597307206)
completed successfully. Dependency-free job 115967231892: 339 collected,
162 passed, 177 explicit optional skips (4.481s). PostgreSQL job 115967232338:
175 collected/passed, zero skips (122.611s), schema metadata check executed.
Full job logs/results are retained in runs/stage3-correction-verification/ci-*.
No browser/model job executed. CI applied to that exact public source SHA;
all non-docs files match the local correction tree byte-for-byte. Complete local
documentation is in the bundle; no rejected uploads were repeated.

The owned correction test container was removed after retaining PostgreSQL logs.
Read-only inspection confirms original container IDs 64f6f7df0265, 2149aa1496d5,
a9c908f7a16a, b3f14b6f8c27 and volume decisionops-commerce_commerce_pgdata remain.
The earlier reviewed Stage 3 archive's SHA256 is unchanged:
2414ee731a1f5c302712a0a8946700f8bdbc38503c3244ba450265580343b33a.
Accepted Stage 2 and reviewed Stage 3 remain ancestors on the same branch.
The correction bundle contains the baseline tree, reconstructable correction patch,
complete seven modified files, exact commands/retained red and green outputs,
verified isolated environment identities and corrected-SHA CI evidence. Packaging
checks archive integrity, applies the patch to the baseline and compares every
changed file; it does not rerun tests or runtime demonstrations.

Remaining limits: cooperative fake cancellation only; an in-flight SQL statement
is bounded by its timeout rather than instantly cancelled by a signal. Connection
establishment has its separately documented bound. Checkpoint saver cursor behavior
is tested against the existing locked version; dependency changes need revalidation.
Supervisor acceptance remains pending. No implementation blocker remains, no merge
occurred, and Stage 4 is not authorized by this correction.
