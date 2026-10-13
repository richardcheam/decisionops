# Optional fake decision provider and durable budget

Approved execution scope is Richard's implementation request; native implementation
with independent final review, no mandatory exercises or design approval pauses.

Insertion: existing cases.investigate_case gathers ALL reads through bundled
read_assessment and saves immutable investigation/proposal. New provider_service
wraps that case workflow, reserving budget in a short transaction, closing it
before dispatch, and applying a checked recommendation in another short transaction.
The opt-in provider_demo CLI exercises this real application service. Existing
API, graph and worker continue their rules-only path, not adaptive tool selection.

Choices: present_replacement (only eligible awaiting-review whole order) or
staff_review (always a permissible conservative disposition for this assessment).
The former preserves the exact proposal awaiting real staff review; the latter
escalates eligible cases and clears approval via the existing case service. Blocked
or already-review-required cases keep their deterministic facts/status and record
review routing. Results arriving after state/generation/evidence drift are stale;
never overwrite a later approval/execution or invent facts. Current same-generation
awaiting-review proposals whose evidence drifted are deterministically invalidated.
Provider failures/budget denial route to staff review explicitly. Rules remain default.

Requests: constant task, case/run/provider IDs, immutable configuration/version,
seven permitted tri-state facts and relevant bindings (generation, investigation,
proposal/hash, order/shipment/variants/quantities, policy, evidence versions), allowed
choices, UTC deadline and bounded token/request/cost limits. No raw customer text,
addresses, secrets or arbitrary tool content. Typed results: choice, provider and
request identity, simulated usage, measured latency, status/error, optional estimate
of confidence. Confidence never supplies permission or evidence.

Fake only: successful offer/review, unavailable, refused, invalid choice, malformed
payload, instruction override, timeout. Adapter dispatch is bounded by deadline;
late thread results cannot change a settled/uncertain record. No retries/real calls.

PostgreSQL 0005: immutable budget configuration and durable call/reservation ledger.
Budget row lock serializes aggregate request count and exact Decimal cost commitments.
Reserve maximum token cost before dispatch. Counts conservatively retain every
reserved request. Known bounded usage settles actual simulated cost; outcomes without known usage
(including timeouts) retain maximum commitment. Record pricing snapshot/version.
Unique run ID prevents duplicate reservation/dispatch and binds case/config/budget.
Persist dispatching before invocation. Restart can claim reserved work once, replay
settled results once, or review dispatching/uncertain work without redispatch.
Expired in-flight calls become uncertain. No transaction/business lock spans provider wait.

Testing uses separate PostgreSQL project/port/volume and app image tags. Preserve live
0004 database/images; do not migrate/recreate the working rules app. New branch's
health/migration expectations move together to 0005. No new dependencies or lock edits.
Simulated pricing/usage/costs are integration fixtures, never OpenAI billing/performance.
