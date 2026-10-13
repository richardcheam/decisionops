# Local cases, staff review, and atomic replacement

Richard authorized autonomous completion and repair loops on 2026-10-13.
The next deliverable is the complete local rules-based business path; no external
shipment/payment/communication occurs. No public API, paid inference or AWS.

## Lifecycle

A case owns an immutable request and mutable projection: open -> awaiting_review,
needs_review or blocked after investigation. Staff can approve/reject the exact
current proposal using its ID, hash and investigation generation. CLI actor is
explicitly local-demo-operator, not authenticated production identity. Reinvestigate
increments generation and removes active approval; reject/escalate do not execute.
Approved -> executed only through the transaction service. Stale execution commits
an invalidation event and needs_review; restoring old records never restores approval.
Terminal executed cases cannot reinvestigate or approve. Case events/reviews append
only; proposals and policy versions immutable. Case state is authoritative, graph
state will later be a projection. No background job/checkpoint yet.

## Transactions and race rules

Case mutations lock the case row. Execution/approval use READ COMMITTED, then lock
order, policy, ordered lines, payment, shipments/lines, and exact inventory rows in
sorted key order. Existing compensation is append-only; an insertion trigger bumps
orders.compensation_revision to serialize all compensation insertions and make an
old repeatable-read snapshot fail rather than miss concurrent compensation. Trigger
locks the original line and rejects cumulative compensation above its quantity.
Historical coverage remains an explicit flag; revision is NOT history completeness.
Investigations use the same locked business view; clock_timestamp after lock waits
is used for freshness. No transaction stays open while waiting for staff.

Reservation means increase inventory.reserved, leave on_hand unchanged, and insert
an immutable reservation for the exact variant/quantity. It is not shipping. Create
replacement order/lines, reservations, compensation resolutions, operation ledger,
case executed state and event in the same transaction. All succeed or none commit.
One approved review has a stable operation ID generated at approval, unique per
review, case and whole original order. Duplicate invocation returns verified existing
operation. Lost response reconciles by operation ID before any retry. No external
exactly-once claims. No reservation release/cancellation/fulfilment in this scope.

## Persistence / commands

Migration 0003 adds cases, immutable case events, reviews, operations, replacement
orders/lines, reservations and compensation_revision; guards policy/resolution
mutation and cumulative quantities. Existing fixtures and assessment remain usable.
CLI open/investigate-case/show-case/review/escalate/execute/reconcile commands.
Approval remains an explicit staff command; agent exercises only fictional isolated
schemas, never approves/executes the owner's existing public demo case.

## Acceptance

Eligible approve -> execute -> verified database records; unapproved/rejected/
escalated/stale cases create no operations. Wrong case/proposal/hash/generation is
rejected. Duplicate review/execute no duplicate compensation or stock movement.
Stock drift and carrier expiry permanently invalidate active approval. Failure
mid-transaction rolls back stock and all records. Real concurrent same-order and
shared-stock operations produce at most one approved matching commit and no negative
stock; losing operation returns review. Constraint guards block direct overcompensation.
Commit-response loss reconciles a single committed operation. Startup/run/inspection/
shutdown/failure/undo commands and owner-vs-agent evidence in runbook/learning log.

## Remaining milestones

Durable job leases/fencing and LangGraph checkpoints, staff API/authentication and
React workspace, provider fakes/evaluation, container builds, backup restore and
release operations remain subsequent local work. Cloud/live provider actions stop
at itemized cost plans. Do not claim whole product completion from the CLI flow.
