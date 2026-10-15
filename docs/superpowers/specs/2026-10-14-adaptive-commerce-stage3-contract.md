# Stage 3 job, fencing and accounting contract

Accepted Stage 2 (including terminal/admission correction) is separately committed
as e8a9804, on feat/commerce-adaptive-core. Stage 3 branch is
feat/commerce-adaptive-recovery. Main fetched at start remains b27e2d7. No
original runtime operation is authorized. Supervisor verified archive/patch and
mocked terminal/admission logic; 28 focused/148 PostgreSQL passes were agent-run.

## Namespace and fencing (resolved before dependent code)

Migration 0007 follows 0006. Separate commerce_adaptive_jobs, action
adaptive_investigate/v1, one job/run. commerce_jobs continues only investigate and
execute; add explicit legacy claim filters as defense in depth. No browser/API
or ordinary worker opt-in. Scheduled runs bind executor commerce-adaptive-jobs/v1
in immutable contracts; direct Stage 2 CLI remains compatible for unscheduled runs.

Lock order is case -> run -> adaptive job -> recommendation. Claims/renewals lock
only adaptive jobs and read immutable run deadlines without locking runs. Every
scheduled advancement/publication requires matching job/run/token, running status
and unexpired lease at admission and transaction end. Recompute server query
limits using min(remaining lease, remaining run, five seconds). Renewal is token-
fenced and unexpired, never reclaims or extends the immutable run deadline. A
cancelled/stale worker can append discarded immutable result audit only, never
change active observations, publish, clear a newer token or overwrite staff state.
Operator cancellation locks case/run/job, ends the run as review or stale without
replacing newer staff state, and revokes the job token. Decisions run outside DB
transactions; a cooperative cancellation event monitors lease/staff loss. There
are no reusable model sessions or model imports.

## Task-aware recommendations

Keep legacy route_investigated_case request/result/two-choice validators unchanged.
New task choose_investigation_action/v1 uses Stage 2 typed actions and exactly its
bounded policy features. Request separately binds run/case generation/revision,
context, collected source/dependency versions, allowed actions, policy/config
version and absolute deadline. Case IDs/hashes remain audit bindings, not features.
Only fixed/cue/adversarial fake adapters admitted in Stage 3.

Reserve one of the original 16 decisions before dispatch, with immutable request
hash/configuration. Also reserve at most 20,000 ms bounded by remaining wall time
and a 240,000 ms run resource cap. Exact Decimal API charge is zero, explicitly
no_api_charge/model-free-v1; no token usage is invented. Uncertain dispatched
calls retain request and maximum-resource reservations. Dispatch transition is
atomic and occurs once. Reservation without dispatch may be resumed. Dispatch
without a recorded result is outcome-unknown, never automatically redispatched;
explicit current-owner recovery marks it uncertain.
Known results settle measured elapsed milliseconds and immutable result identity;
only current allowed results are applied, without charging a second decision.
Invalid choices/fallback still consume separate original decision attempts.
Explicit recovery may choose a recorded fixed-order fallback or review within
remaining caps. Interrupted read-only tools retry as a new counted attempt after
explicit pending-token recovery. Application and its durable effects are atomic;
replay of a settled/applied recommendation cannot repeat them.

## Graph and recovery

Separate checkpoint schema commerce_adaptive_graph_<business-schema digest> and
thread commerce-adaptive/v1:<job>:<run>. Setup is explicit. Each graph invocation
projects authoritative job/run/steps/calls and advances at most one recorded
recommendation. Checkpoint tokens/actions/counters are never admission authority.
Replay/checkpoint loss reconstructs settled effects; publication and job completion
are separately idempotent. Inspect is read-only. Resume acquires current ownership;
uncertain decisions and pending reads stop for explicit recover, not retry.

Rulings: use additive accounting instead of widening the legacy two-choice ledger;
use a separate job table instead of weakening legacy action constraints. This
costs a second schema/API but makes accidental legacy dispatch structurally
impossible. Audit-only late-result writes are the explicit exception to lease
ownership; they cannot have domain effects. Stage 4 remains pending.


## Recovery rulings and observed boundaries

`dispatching` without a recorded result means outcome-unknown. Resume reports this
and pauses; it does not change a live call to uncertain. Explicit recovery under
current ownership marks it uncertain and retires its application, retaining the
maximum reservation. This prevents stale/concurrent workers invalidating active
work. A late known result for an already uncertain call is bounded discarded audit,
not application or a budget refund. An undispatched expired reservation is a known
zero-work settlement; explicit recovery retires it and permits a new counted
fallback. Application rechecks the call deadline with database time after locks.

Worker SIGINT/SIGTERM sets only a shutdown event, never invokes unfenced operator
cancel. An in-progress cooperative fake is stopped and its unresolved reservation
retained; stopping before dispatch consumes no new attempt. Explicit operator
cancel uses case/run/job serialization and preserves newer staff state. It cannot
undo a proposal already committed before cancellation. Terminal job repair after
lease expiry does not replay publication, including when the claim cap is reached.

A fresh source review identified six concrete gaps; regressions reproduced them.
The fixes separate per-call cancellation from shared shutdown, fence unknown
outcomes, settle expired undispatched work, repair terminal completion, recheck
call deadlines under locks and bind actual queries/locks to lease time. A follow-up
found the unfenced worker-shutdown cancellation race; a regression reproduced and
removed that authority escalation. No Stage 4 model sessions were introduced.

## Shutdown/checkpoint correction (Stage 3 only)

Plain CLI resume now passes its stop event through resume/project to tick as a
runtime closure argument. It is never graph State, serialized configuration,
checkpoint authority or a saved ownership token. Resume checks shutdown before
claim/each projection and after projection, and stops the loop before renewal or
another decision. Once/token-resume keep the same runner and perform projection
only (advance=False) under the current active fence; stopped workers skip this
extra projection. Terminal/audit projections have no advancement authority.

Recheck shutdown after reservation and dispatch-claim waits and before adapter
thread launch/application. A stopped reserved request remains reserved, with its
consumed attempt retained. If a dispatch marker already committed, conservatively
retain an uncertain reservation even when shutdown prevents adapter invocation;
never invent usage or reset counters. Cooperative in-flight work is cancelled;
known results can be settled without application, unknown results remain uncertain.
Only explicit recovery can retire uncertain work. Worker shutdown cannot invoke
operator cancellation or clear ownership. Existing fencing/admission still applies.

Checkpoint connections set statement_timeout and lock_timeout to 5000ms at
connection startup, independently of connect_timeout=3. Setup and unfenced
historical/terminal projection have a separate five-second metadata operation
budget. Active fenced projections capture min(run deadline, current lease) using
server time and a monotonic deadline; every checkpoint execute recomputes its
remaining bound, capped at five seconds. Bulk writes execute synchronously row
by row rather than pipelining unbounded batches. The saver mutex is also bounded
by the operation deadline. No business transaction spans fake work. Connection
establishment has its separate three-second bound; no checkpoint SQL is admitted
once the operation budget has elapsed. A running SQL statement is not instantly
cancelled by SIGTERM; its remaining statement/lock timeout bounds its wait.

Checkpoint failure raises CheckpointFailure; CLI reports adaptive_checkpoint_error
and exit 3, with no automatic retry. PostgreSQL domain commits remain authoritative,
including publication already committed before checkpoint write failure. Inspect
without graph access, fix the lock/readiness issue, then explicitly resume or
recover. Reconstruct only from committed steps/reservations; never replay an
applied recommendation or reset counters. The saver overrides the pinned library's
cursor boundary; future checkpoint-library changes require these regressions,
not a dependency upgrade in this correction.
