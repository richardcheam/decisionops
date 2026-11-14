# Stage 1 selectable reads: resolved contract

Implementation scope: independently selected reads and in-memory immutable observation history only. No case publication, migration, jobs, policy/model loop or runtime wiring. Existing bundled readers/evidence/proposals remain unchanged.

## Exact SQL projections and dependencies

Queries select the columns below, filtered to the immutable `AssessmentRequest`. Results are sorted by projected primary identity. No `SELECT table.*`, implicit supporting read, lock or write is allowed.

| Tool | Required observations | Queries/projections |
|---|---|---|
| order_manifest | none | orders: id, store_id, policy_id, currency; order_lines: order_id, variant_id, quantity, unit_price_minor. Both filter order_id. |
| replacement_policy | manifest | policy_versions: id, store_id, version, allow_confirmed_loss, max_units, carrier_max_age_seconds; filter manifest's policy_id AND store_id. |
| payment | manifest | payments: order_id, status, amount_minor, currency; filter order_id. Total/currency come from the explicit manifest, never another query. |
| fulfilment | manifest | shipments: id, order_id, fulfilment_status for this order; shipment_lines: shipment_id, order_id, variant_id, quantity for requested shipment AND order, only if shipment found. If not found, shipments: order_id filtered by requested shipment ID, solely to distinguish wrong-order binding. No carrier columns. |
| carrier_loss | manifest, fulfilment, policy | shipments: id, order_id, carrier_status, carrier_observed_at; filter shipment ID AND order. Does not fetch fulfilment, policy or lines. |
| compensation_history | manifest | orders: id, resolution_history_complete, compensation_revision; resolutions: id, order_id, variant_id, quantity, kind, operation_id; filter order_id. The completeness read is explicitly part of this tool, not manifest. |
| inventory | manifest | inventory: store_id, variant_id, on_hand, reserved; filter store AND requested variants. |

The manifest provides request validity and full-order scope. Fulfilment provides shipped status and split/partial/wrong-order scope. Compensation provides completeness and partial-compensation scope. These three scope checks must all be current and established for a supported assessment. Carrier selection requires a current, successful, bound fulfilment observation; fulfilment need not establish shipped=true, but must identify the requested shipment. Incomplete/missing dependencies produce a controlled dependency rejection before SQL. Carrier tracking may be unknown and still have a complete bound observation.

## Authority and completeness

Only admitted PostgreSQL observation streams count as trusted; default is `primary`. Additional independent streams require explicit server-side admission to the history object, never a policy choice. Each tool uses its declared source ID and request binding. Timestamp, digest and dependency validation happen before evidence contributes.

The actual schema has one payment per order, one applicable policy per ID/store, unique order/ship lines and inventory identities. Conflicting/duplicate singleton or line identities in returned rows are unknown, not resolved by row order, majority or recency. Distinct resolution IDs are additive; duplicate IDs are unknown rather than double-counted. Unknown statuses and malformed quantities/amounts also remain unknown. Demonstrably pending/failed payment or a paid amount/currency mismatch is false; absent payment is unknown. Reliable current delivered tracking is false; in_transit/unknown/stale/future tracking is unknown. No loss inference from delay.

History requires exactly one matching order marker with complete=true and valid unique resolution rows. Incomplete, absent or failed history is unknown even if returned rows are empty (or suggest compensation). Exact variant sums determine compensation; unknown/out-of-order variants make the result unresolved. Supported scope still sends partial compensation to review. Inventory requires every requested variant; missing variants are unknown, not zero stock. The caller supplies a consistent read transaction per tool; no claim of one cross-tool snapshot is made.

## Immutable history, supersession and dependencies

Observations are frozen values with canonical serialized payloads; exported records are copies. History appends observations; it never edits them. IDs are unique. A refresh must explicitly name the active predecessor, with identical tool/request/admitted stream and nondecreasing observation time. Cross-stream replacement is rejected. Without explicit supersession, both observations remain active: conflicting true/false claims stay unknown, and unresolved claims remain unresolved. Different active content versions also leave the tool unknown even when their Boolean values agree; agreeing values do not resolve conflicting stock counts or payment amounts. A same-stream refresh can replace a failed lookup; independent active evidence cannot be erased by that operation.

Dependencies bind tool, stream and content version. An unchanged-content refresh keeps descendants valid; changed content, ambiguous active dependency content versions (even when Boolean values agree), unavailable dependencies, expiry or a contradiction invalidates descendants transitively. Old descendants remain in history and contribute unknown until explicitly refreshed. No SQL occurs while assembling or invalidating evidence. Expiry is 24 hours by default; carrier evidence also expires at its carrier timestamp plus the selected policy's age limit. Future observations are invalid. Do not infer current state from stale snapshots.

## Hash/version compatibility and safety recheck

New contract: `commerce-adaptive-observation/v2`. SHA-256 covers the contract, tool, admitted stream, exact request, returned status/value/scope, projected payload, and dependency tool/stream/content versions. Observation IDs, fetch time and expiry are not content identity; they are separately validated. Hashes are integrity/content bindings, not signatures or permission. Source IDs are `postgres-adaptive-v2-<tool>`.

Version-1 `read_assessment`, `tool_result`, `assemble`, `assess_evidence`, `binding`, `build_proposal` and `check_proposal` remain unchanged. V2 assembly uses the existing evidence validator with its own trusted-source configuration, but returns `observations`, not legacy `read_tools`. V2 hashes must never be passed off as version-1 hashes or used directly as legacy proposal inputs. Histories admit only the explicit v2 contract; unsupported contract versions are rejected before assembly. Stage 1 provides no proposal publication API.

Future publication must first establish complete valid collected v2 evidence and scope. A locked safety recheck must confirm those projected contents/dependencies against current records before constructing a legacy version-1 proposal from its separate bundled attestation (or an explicitly versioned future proposal). Safety reads cannot fill collection gaps or become policy observations. That bridge is later-stage work, not implemented here. Historical version-1 documents and rechecks continue using exactly their existing hash scheme.

## Verification scope

Use real SQLAlchemy queries against an in-memory SQLite business-record mirror for projection/selection/derivation tests, with no runtime migration. Query capture asserts exactly which columns/tables were read. SQLite tests are local query/contract evidence, not PostgreSQL integration evidence. Pure history tests run without dependencies using `python -S`. The opt-in PostgreSQL module reuses existing migrations only in a disposable test schema when explicitly enabled; it is collected by the required CI profile alongside the SQLite contracts. At the initial checkpoint these PostgreSQL tests were unexecuted. Completion verification now runs existing migrations and fictional seeds only inside disposable test schemas on the verified separate test database; see the current runbook results. PostgreSQL execution must be reported separately; no CI or PostgreSQL pass may be inferred from SQLite results.

Known conservative departure from the legacy bundled reader: absence of all shipment lines is missing evidence, not a false shipped condition. Supported complete records retain parity.

Ruling: keep projected derivation separate from the legacy reader for Stage 1, rather than refactoring version-1 internals. This protects historical content hashes and permits conservative missing-line behavior. The maintenance cost is duplicate derivation logic, guarded by parity regressions; any future shared extraction must preserve both explicit contracts.

## Reconciled Stage 1 completion decisions

The tool caller must supply the exact prerequisite Observation objects via
`read_tool(..., dependencies=(...))`. Merely having records in History is not
permission to choose dependencies implicitly. Objects must be active in that
history, scoped to the same request, current, and unambiguous; rejection precedes
SQL. Dependencies are not queried or refreshed by the selected tool.

Successful complete-empty history means: an admitted PostgreSQL source; an
explicit valid manifest binding; exactly one matching complete=true order marker;
a successful unpaginated resolution query for that entire order in the same
consistent transaction; valid unique IDs/variants/quantities; and no active
independent conflict. Zero rows then establishes no compensation. A failed query,
absent/incomplete marker, malformed row or invalidated dependency cannot do so.
An unsupported partial request still requires review even if its history is known.

`Observation.record()` / `History.assess()` are operator/audit views, containing
projected source rows, identities and hashes. `History.policy_view(now)` is the
separate bounded projection: requested variant quantities and only active requested
observations' tool, tri-state value, status, enumerated reason, scope-known flag
and enumerated scope reasons. It excludes rows, case/order/shipment/store/policy
IDs, observation IDs, source/dependency hashes, stream IDs, unrequested requirements
and complete eligibility. Invalid dependencies become unknown. Unknown free-text
reasons are replaced with a bounded generic code. Its canonical JSON is limited
to 8,192 bytes; overflow raises rather than silently dropping observations. Initial
reports, budgets and tool-choice policies belong to later stages, not this library.

V2 canonicalization uses sorted object keys, compact JSON separators, rejected
NaN/infinity, JSON-preserved scalar types, UTF-8 hashing, UTC ISO timestamps and
primary-identity-ordered projected row arrays. Dependency hash triples are sorted
by tool/stream/version, independently of caller order; dependency observation IDs
are retained for audit but excluded from content identity. Only the explicit v2
contract is admitted by History; other contracts are rejected. V1 serialization,
hashes, documents and validators are untouched. These v2 changes affect only the
uncommitted library, not any persisted application record.

## Case-revision coverage resolved before Stage 2

Stage 2 must add a monotonic `case_revision` with server default zero and a
BEFORE UPDATE trigger assigning OLD.case_revision + 1 on every case-row update
(including direct SQL/no-op updates). Callers cannot reset it. This conservative
rule avoids missing mutation paths and accepts harmless extra invalidation rather
than an ABA race. No trigger/column/migration is introduced in Stage 1.

| Actual path | Revision coverage required in Stage 2 |
|---|---|
| cases.open_case | Initial revision zero, immutable run binds the inserted request |
| cases.investigate_case | Generation/proposal/investigation/status/approval update bumps revision |
| cases.invalidate | Proposal staleness and approval revocation bump even within one generation |
| cases.review_case | Approve/reject updates bump; idempotent read-only repeats do not |
| cases.escalate_case | Staff reason/status/approval change bumps, even if status later returns |
| execution.execute | Executed transition bumps; reconciliation-only retry does not |
| provider_service.prepare/apply | Investigation, invalidation and escalation above cover state effects; reservation/audit-only writes do not mutate case revision |
| Future adaptive start/publication or staff report/request edit | Any case-row update bumps; run step/context revision separately fences evidence changes |

Before Stage 2 publication, compare case generation AND revision plus durable run
context version while holding the existing short case lock. Missing/deleted cases
fail closed. Cover direct updates, same-generation escalation/rejection, approval
revocation, successful execution and no-op update invalidation in Stage 2 tests.
Keep session framing/deadlines/output caps unresolved until Stage 4; Stage 1 adds
no worker or session implementation.

## Returned-field inventory

Every audit record contains contract, tool, exact request binding, admitted stream,
status, tri-state value, reason, scope-known/reasons, dependency triples plus their
observation IDs, immutable observation ID, UTC observation/expiry and v2 source
version. Payload fields below contain only the tool's explicitly projected rows.
The separate policy view strips this audit envelope and raw payload.

| Tool | Requirement value | Audit payload fields |
|---|---|---|
| order_manifest | quantities_valid | orders, lines |
| replacement_policy | policy_permits | policies |
| payment | paid | payments |
| fulfilment | shipped | shipments, selected, lines; binding_mismatch boolean only on missing/mismatched shipment |
| carrier_loss | loss_confirmed | carrier |
| compensation_history | no_previous_compensation | markers, resolutions |
| inventory | stock_available | inventory |

On a query failure, payload is discarded completely and value stays unknown;
partial rows do not constitute a successful history query. A complete eligible
selection performs seven tools and ten declared SQL queries (manifest and history
have two, fulfilment has two). This is deliberate granularity, not an efficiency
claim. The bundled path remains its existing eight-query assessment.
