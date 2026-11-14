# Stage 2 durable model-free investigation contract

Stage 1 accepted snapshot: fde904f627df2cf7301089059e700f691cdbd5d5, exactly the
reviewed archive contents. Main was fetched and remains b27e2d7. Stage 2 is a
separate feat/commerce-adaptive-core worktree/diff. Supervisor verification covered
archive integrity/reconstruction, 16 pure observations and 12 frozen legacy cases;
PostgreSQL/full-suite verification remains agent-executed. CI/browser unexecuted.

## Publication bridge (decided before implementation)

Reject propose before safety reads unless collected v2 evidence establishes all
seven conditions true, complete supported scope and current dependency bindings.
Lock case then run then existing business rows in a short READ COMMITTED safety
transaction. Re-read the seven already-collected tools into a private temporary
v2 History, with explicit dependencies. Compare every v2 content/dependency version
with the collected binding. Safety evidence is never appended to collected history
or supplied to the policy. Its audit feedback consists only of changed tool names
and invalidated collected observation IDs, not new facts or source rows.

Drift invalidates affected old observations through immutable invalidation events;
old records remain inspectable. The next decision may explicitly refresh within
remaining limits or request review. Only after exact confirmation, read a separate
legacy v1 attestation, require it eligible/supported, and use unchanged
build_proposal/document_hash to persist legacy investigation/proposal records.
Fresh clocks/freshness are checked again before publication. The case keeps the
run's allocated generation; database case_revision advances on final publication.
Existing exact staff approval, execution revalidation and reconciliation continue
unchanged. No recommendation grants permission or performs business writes.

## Durable storage and serialization

Migration 0006 follows actual head 0005. Add case_revision default zero and the
resolved server-side BEFORE UPDATE trigger: every case UPDATE assigns OLD+1,
including direct SQL/no-op and same-generation edits. Insert begins at zero.

Runs bind case ID, allocated generation, resulting post-start case_revision,
immutable request/report, admitted observation/action versions, start/deadline and
policy configuration. Start locks case, forbids executed cases, allocates generation,
clears old proposal/investigation/approval and records revocation. Capture revision
with UPDATE RETURNING. A partial unique index enforces one active run per case.

Append-only steps and observation rows retain all outcomes. Supersession edges
are immutable; active-selection pointers are explicitly maintained. Counter rows
cap each tool at two, runs cap tools at 12 and decisions at 16. Run context version
advances under row lock on every persisted event; immutable header and monotonic
counter/version triggers reject mutation/reset. All advancement locks case then
run. A submitted context version must match; racing submissions do not dispatch
second work. Case revision/generation drift terminates the old run without touching
newer staff approval/execution/state.

Reserve a decision/tool attempt and pending token before reading; commit. Execute
the tool in its own consistent READ ONLY transaction with no business/run locks.
Persist result in a new short transaction only if token, reserved pending-context and case bindings
still match. Discard late results into audit without updating active evidence.
There is no queue, graph, lease or renewal. Explicit recovery of an abandoned
read invalidates its token and records interruption; a retry is a new counted
attempt. Inspection alone does not resume anything or reset budgets.

## Boundaries and bounded progress

One typed action contract supports fixed-order, cue-rules and scripted/adversarial
fake policies: read(tool), propose, report_blocker, request_review(enum reason).
Allowed actions derive only from collected history, dependencies and budgets.
Initial report is at most 2,000 UTF-8 bytes. The existing policy observation view
retains its 8,192-byte cap; policy features contain only report, that view, attempted
tools, bounded rejection codes, remaining limits and allowed actions. Case/run IDs,
versions, raw rows and safety-read results remain audit/binding metadata.

Rejected/malformed choices and policy errors consume decision attempts. Any fixed
fallback is a separate counted decision, recorded as fallback. Prioritize unread
tools before retries; unsupported/missing information remains unknown. Terminal
observed-blocker reports enumerate every unknown/unread requirement and unresolved
scope tool. blocked requires established supported scope; otherwise needs_review.

The total deadline is start+240 seconds (test configurations may shorten, never
raise caps). Each real database statement/lock wait is bounded by min(5 seconds,
remaining run time), recomputed before statements; no post-hoc-only timeout. DB
control/timeout queries are explicit infrastructure, not hidden business reads.
Safety reads are logged separately from selected tool attempts and consume a
proposal decision; they cannot become a free policy loop. Exhaustion/expiry yields
a recorded review or existing valid blocker report, never invented evidence.

No adaptive browser/API/default-worker integration, providers/models, adaptive
jobs/graph, lease renewal, budget accounting or model sessions in Stage 2.

## Deadline admission and audit cleanup

The immutable run deadline is bootstrapped by a non-row-locking header lookup
under a five-second statement timeout. Active context assembly, case/run locks,
reservation, recovery and result persistence then recompute server statement and
lock limits from the remaining deadline. A lock timeout rolls back the transaction;
the CLI returns a controlled database error, with no fabricated observation. Once
the deadline has passed, a separate bounded audit-cleanup transaction may record
review/discarded results, but cannot dispatch another business read. Historical
inspection and expired cleanup use five-second statement limits. These are not
extensions to the investigation's decision/tool budget. Late discarded results
may advance audit sequence without altering a terminal run or a newer pending
claim. Recovery never automatically redispatches a reserved read.

Stage 1 v1 hashes/validators remain unchanged. Stage 2 adds only recorded v2
invalidation IDs (`refresh_required`) and deadline-unavailable observations.
Migration downgrade destroys adaptive audit records and is not operational recovery.


## Stage 2 correction: final blocker confirmation and result admission

`finish` never treats the earlier blocker flag as proof. At final publication it
requires a fresh assessment containing at least one valid bound false condition.
Explicit reports and tool/decision exhaustion use the same confirmation path.
Private validation reads only collected blocker tools plus their explicit
collected dependency closure. Only when collected scope would justify blocked
are the already-collected order_manifest, fulfilment and compensation_history
scope tools added. Reads use exact Stage 1 projections, locking those rows in
case/run -> ordered dependency-tool order, under the remaining run timeout.
There is no bundled assessment or broad business-lock helper in this validation.
Parent order/shipment locks also serialize supported FK inserts and compensation
revision writes. Missing/failed/conflicting private evidence is not false.

Private projected hashes/dependencies must match collected bindings. Freshness is
checked again after lock waits and validation. Drift/expiry records immutable
`safety_drift` invalidation IDs and changed tool names; private observations are
not persisted, made active or shown to policies. The run remains active only if
explicit refresh of changed tools fits per-tool, total-read, decision and wall
limits (leaving a decision to finish); otherwise it ends in review. Unsupported
or unresolved scope still forces needs_review. There is no blocked or
observed_blocker outcome with zero valid blockers.

Result admission recomputes database time after acquiring case/run locks. A
successful result finishing after the run deadline is retained with applied=false;
it cannot update active pointers or supersessions. If it owns the reservation,
bounded expired cleanup ends the run in review. An older token cannot clear a
newer pending token or close its run: only its discarded audit record is appended;
the owning result or explicit recovery performs cleanup. Terminal runs and newer
staff state remain fenced. No attempt reset, deadline extension or redispatch.
