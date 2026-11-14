# Optional API investigation contract (implementation; live calls not authorized)

Insertion: adaptive_runner.tick reserves a task-bound adaptive call before dispatch.
Its existing duration/state ledger stays unchanged for legacy policies. Optional API
runs additionally reserve monetary/count resources in commerce_provider_calls, keyed
by that adaptive call ID, against an immutable task-specific commerce_provider_budgets
row. Reserve/claim/settle/uncertain operations share the domain transaction. Legacy
route_investigated_case validators and two-choice API remain unchanged. No migration
or original-runtime operation is required. API budget readers reject other tasks.

One Responses SDK request chooses an index into the current explicitly allowed
investigation actions. Only PolicyRequest.features() and fixed instructions/schema
enter the model. Audit IDs/bindings/configuration remain outside features. No tools
are exposed to the API itself, no conversation carry-over, no background mode and
store=false. Rules remain default; explicit API jobs use no automatic rules fallback.
An unavailable/invalid/uncertain API recommendation yields deterministic review or
fenced pause when staff/ownership changed. Human approval/execution are unchanged.

SDK retries=0. Every dispatched call may have spent money even after a timeout;
uncertain reservations remain committed and cannot automatically redispatch. Known
usage is settled independently from action validity. Restart reads immutable request,
configuration and pricing; no new budget or counters are created for an old call.

Pre-dispatch reservations use exact Decimal pricing, full uncached input prices,
maximum output tokens, and a conservative input upper bound: entire bounded wire
JSON byte count plus protocol margin, never a guessed measured token count.
Input wire bytes <=32768; maximum input reservation36864 tokens; output <=1024;
response bytes <=65536. SDK/HTTP and total decision deadlines are bounded; HTTP
response bodies drain through a byte limiter. No transaction spans an HTTP await.
External OPENAI_API_KEY is never part of persisted configuration or traces. Endpoint
is explicitly https://api.openai.com/v1; unsupported URLs fail before credentials.

Official documentation inspected 2026-10-16:
- https://developers.openai.com/api/reference/python (SDK retries/timeouts)
- https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses
- https://developers.openai.com/api/reference/resources/responses/methods/create
- https://developers.openai.com/api/docs/models/gpt-5.4-mini
- https://developers.openai.com/api/docs/pricing

Live spend requires a separate explicit approval after mock verification. No API
request (including credential/model probing) is authorized by credential presence.
The cached-pilot experiment remains stopped and is unrelated to this API budget.

## Verified local behavior (agent executed; no live calls)

The actual pinned Python SDK 2.26.0 ran against httpx.MockTransport. Nine transport
checks and nine PostgreSQL accounting/investigation checks passed, zero skips.
The required legacy PostgreSQL profile passed 194/194, zero skips. The separate
dependency-free profile collected 412: 190 passed, 222 explicitly skipped optional
PostgreSQL/SDK/model checks. See runs/api-verification/*-substantive.log,
legacy-postgres.log and dependency-free.log for full output. New-source CI and
browser checks have not run. No Richard-performed commands are asserted here.

A CLI mock success selected seven reads and then propose (eight decisions), producing
ARUN-a9e07bab5c4a4eca94d29fc131782379 through the unchanged deterministic publication
bridge. Its eight usage records are simulated 100 input/10 output tokens each;
$0.00012000 per record is simulated pricing arithmetic, not real usage or spending.
No staff approval or replacement execution occurred. The timeout demonstration
ARUN-221d7ed8998849229a9999e0b9f14898 ended review after one attempted decision and
zero tools. Its uncertain $0.03225600 reservation remains held; no automatic retry.
The timeout is a negative task-completion result. inspect reproduced both traces.
An unapproved live start failed before budget/job creation or HTTP dispatch.

The tests also cover concurrent shared-budget exhaustion, restart after possible
dispatch, malformed choices with known usage, staff changes during HTTP and after
result persistence, absolute result expiry and zero-transport forced actions.
A second transaction acquires the case lock while HTTP is pending, demonstrating
that business locks are not held across inference. Real credentials/model access,
live response quality, billing reconciliation, and human approval/execution remain
unexercised by this slice. The existing execution regressions remain green.

## Proposed live plan — awaiting explicit spending approval

One new fictional investigation, endpoint https://api.openai.com/v1, Responses API,
pinned model gpt-5.4-mini-2026-03-17, reasoning low, service tier default, store=false.
The inspected standard global prices are $0.75/million input and $4.50/million output.
No cache discount assumed. Up to 12 HTTP requests; each reserves 36,864 input tokens
(a conservative byte/protocol bound, not a measured count) and 1,024 output tokens
including reasoning: $0.03225600 per request, $0.38707200 worst-case reservation,
with an immutable $0.40 total ledger ceiling. Aggregate maxima: 442,368 input and
12,288 output tokens. Existing 20-second decisions and 240-second run limit remain.
The 16 decision/12 read/two-per-tool caps also remain. Reservations may stop the run
early; never replenish by replacing a budget ID after uncertainty or exhaustion.
Known usage is multiplied by the versioned conservative rates; stored actual_cost_usd
means the usage-based accounting estimate, not independently verified invoice cost.

Proposed configuration: runs/api-verification/live-proposed.json; canonical config
SHA-256 db174fbcf112c96b7fe41961d264dc71940357ff13ee7075384b34865f38236e.
External OPENAI_API_KEY is read only after matching explicit live configuration
approval. Do not place it in CLI arguments, source, documentation or trace exports.
Credential existence grants no permission. Access may be unavailable; report that
outcome rather than silently substituting rules. The cached pilot ledger is unrelated
and stays stopped. No public uploads, deployment or adaptive default changes.

Source-only fresh review found no blocking defect. Lease/run expiry can fence review
publication itself; unresolved reservations remain for explicit recovery. This review
ran no tests, database operations, HTTP calls or models.


## Current manual-only plan: nano (supersedes unstarted $0.40 authorization)

The previous configuration and evidence are historical and remain unchanged; its
unstarted live authorization is revoked. The current proposal is
[api-nano-proposed.json](examples/api-nano-proposed.json):
`gpt-5-nano-2025-08-07`, global Responses endpoint, $0.05/M input and $0.40/M output.
Canonical configuration SHA-256: `8349e81fc3b0805567aa71e5d3f540ac038623e6efec3735a052c9276a244a83`.
Per request reserve: 36,864 input plus at most 1,024 output tokens = $0.00225280.
Twelve requests reserve at most $0.02703360, under an immutable $0.03 cap.
Reasoning remains low; the 20-second decision/240-second run and evidence/tool/
approval protections remain unchanged. SDK/transport automatic retries remain zero.

No live call is currently authorized. Richard must explicitly say **RUN LIVE TEST**
for this configuration; that permits exactly one investigation. Every subsequent
investigation requires another explicit command. Do not treat a reusable config hash,
credentials, application startup, CI/tests or background workers as spending consent.
Only the explicitly invoked operator path constructs a live adapter with an approval
hash; ordinary workers have no adapter and reject API work rather than substituting
rules. Rules remain default. Do not enqueue live API work before manual admission.
No automatic resume after failure/uncertainty, replacement budget, access probes,
model switch or increased cap. Stop on unavailable access or failure.

Compatibility was checked against official model documentation and the installed
SDK using mocked HTTP: 11 transport tests passed, zero skips, including nano schema/
reasoning/output-limit compatibility and credentials-present/no-approval rejection
before SDK client creation. This does not verify account access or native model
quality. Log: runs/api-verification/nano-compatibility.log. No database or runtime
operations, live requests, deployment or publication occurred for this change.

The official model page currently marks this exact nano snapshot deprecated, while
listing Responses and structured outputs support and the requested rates. Preserve
the selected snapshot; actual account availability remains unverified. If unavailable,
stop without a substitute or retries.


## Current selection-route successor

The proposed selection route is now [the actual Decisions API](OPENAI-DECISIONS.md), with
a separate configuration/version and input-only accounting. This document and the
Responses adapter remain preserved historical compatibility material; its nano
authorization does not authorize Decisions. Wait for a new explicit RUN LIVE TEST.
