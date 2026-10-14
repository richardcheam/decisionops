# Commerce decisions and open questions

## Agreed direction

- Build the fictional-store lost-shipment workflow in coherent, tested slices with operational walkthroughs. Optional participation replaces mandatory exercises and teach-back.
- Begin with pure Python eligibility logic and focused tests, before database access or LangGraph.
- Routine development and CI require no paid inference. Live inference and AWS provisioning require a concrete approved cost plan.
- The eligibility contract and initial function came from ChatGPT and were relayed by Richard; reviewed on 2026-10-12.

## Eligibility contract

Required normalized facts: paid, shipped, loss_confirmed, quantities_valid,
no_previous_compensation, stock_available, policy_permits.

- Every requirement true: eligible to propose; staff approval remains required.
- Any established false: ineligible for the current request/policy.
- Otherwise any unknown: needs investigation or review.
- Collect every blocker and unknown before applying precedence; retain both lists.
- Absent facts and unresolved contradictions map to unknown, never automatically false or true.
- Malformed values raise ValueError. Use identity checks: Python integers 0 and 1 compare equal to booleans but are not accepted facts.

| Requirement | Evidence needed | Established failure | Missing/contradictory evidence |
| --- | --- | --- | --- |
| Paid and shipped (separate facts) | Payment and fulfilment records for relevant items | Ineligible; investigate payment/fulfilment | Retrieve records or review |
| Loss confirmed | Authoritative current carrier loss record bound to the correct shipment | Ineligible under loss-only rule | Investigate; stale tracking, timeouts and customer claims alone do not establish loss |
| Quantities valid | Exact original order variants and quantities | Correct request before reassessment | Retrieve lines or clarify |
| No previous compensation | Complete applicable refund/replacement history | Prevent overlapping compensation | Retrieve history; unavailable is not empty |
| Stock available | Sufficient available, unreserved stock of exact variants | Replacement unavailable now | Refresh or review; do not promise stock |
| Policy permits | Applicable versioned store policy | Explain blocking policy | Retrieve/clarify policy; no invented permission |

The pure function evaluates normalized facts; it does not establish their
authority, currency, provenance, or business scope. A future evidence adapter
must route unsupported partial shipments/partly compensated cases to review.
The evidence intake now routes caller-declared unsupported cases to review;
deriving that scope from order records remains future work. Stale or disputed
tracking remains unknown until authority is resolved. A later policy provider
can apply configurable store criteria to produce policy_permits; this first
slice does not add a configuration engine. Store policy cannot bypass approval,
valid quantities, stock constraints, or duplicate prevention.

## Evidence intake slice (2026-10-12)

- Read-tool attestations carry requirement, boolean/unknown value, status,
  source ID/version, order binding and UTC observation timestamp.
- Trusted source IDs are configured outside the observation. The CLI uses a
  trusted fictional fixture; it is not an authenticated public input endpoint.
- A configurable positive freshness limit applies to observation/read time,
  not the original order event time. The demo uses 24 hours; this is a demo
  default, not a real store SLA. Live adapters must not infer explicit loss
  confirmation from freshly retrieved but stale tracking events.
- Missing, unavailable, future, stale, wrong-order or untrusted records leave
  the associated fact unknown. Any unresolved record in the supplied snapshot
  blocks establishing that fact, even if another record says true. Conflicting
  usable records also remain unknown. New source versions do not implicitly
  supersede older records; adapters must provide a reconciled current snapshot.
- Unsupported cases route to review, retaining blockers/unknowns for inspection.
- Versioned assessment artifacts explain the input decision and contain input
  hashes; they are not graph checkpoints, business ledgers, or historical
  diagnostic replay traces. No records are reserved or replacements created.
- The one-shot command uses real UTC by default. --as-of is explicitly for
  reproducible fixture replay and must not become a production eligibility override.

## Questions to resolve before dependent work

| Question | Resolve before |
| --- | --- |
| Stock reservation semantics, compensation uniqueness and transaction lock ordering | M1 database constraints and race exercises |
| Case states and transitions for rejection, reinvestigation, escalation and uncertain execution | M2 workflow |
| Durable job claiming, leases/fencing and recovery across jobs, graph checkpoints and operations | M2 recovery; verify again before M3 writes |
| Approval version binding, invalidation and operation reconciliation | M3 approved execution |
| Staff authentication, sessions and server-side authorization | M4 API/workspace; before public exposure |
| Provider availability, retries, usage accounting and atomic budget reservation | M5 provider integration |
| Resource costs, secrets, backup retention, recovery targets and migration-compatible rollback | M6 provisioning/release |

## PostgreSQL read slice: resolved assumptions

- One fictional store; exact variant IDs; order lines and requested quantities
  are positive integers up to 1000 each. Requests contain at most 100 variants.
- Supported replacement scope is the whole order, in one fully shipped
  shipment. Subset requests, split/partial shipments and partly compensated
  orders route to review. Wrong variants or excessive quantities are established
  invalid requests, not missing evidence. A wrong-order shipment supplies no
  shipment/loss fact for the requested order and routes to review.
- Payment must have paid status, correct currency and exact line-total amount.
  Money uses integer minor units. The demo excludes taxes, discounts, shipping
  charges and multiple payment captures; do not silently apply its totals to a
  real store with those features.
- Shipment lines have composite foreign keys to both the shipment/order and
  order/variant. Resolution lines reference the original order/variant. Policies
  bind to order/store through a composite foreign key and an explicit version.
- The demo shipment row is the authoritative current carrier snapshot. Only
  lost establishes loss. Delivered establishes false; in_transit/unknown leave
  loss unresolved. Carrier observation age is checked against the pinned
  policy, separately from the fresh database read timestamp. Future observations
  remain unknown. Conflicting raw carrier events are not stored in this slice;
  future adapters must reconcile them or pass unresolved evidence.
- Empty resolution rows mean no compensation only when the order's explicit
  resolution_history_complete flag is true and the lookup succeeds. This flag
  describes fixture import coverage; it cannot be inferred from a zero-row query.
- Available stock is on_hand minus reserved, scoped to store and exact variant.
  No reservation or inventory write occurs during assessment.
- Read tools run in one PostgreSQL repeatable-read snapshot with READ ONLY,
  three-second connection timeout and five-second statement timeout. A failed
  query discards the whole snapshot and returns unavailable facts.
- Source versions are deterministic content digests of the relevant bound
  records. They are provenance for this read, not authorization or durable
  replacement-operation identifiers.
- Seed IDs and business values are deterministic; carrier timestamps are
  anchored to the database clock at first seed. Tests supply a fixed anchor.
  Reseeding is a no-op and does not erase patches or refresh stale observations.
- Migrations and seed are administrative writes. The assessment CLI exposes
  only reads. Immutable version usage is enforced by the application convention
  of inserting new policy versions; administrative SQL can still modify rows.
  Stronger policy immutability/roles must be resolved before approvals depend
  on them. Stock races, action uniqueness and execution lock ordering remain
  explicitly deferred to the write milestone.

Implementation references: [SQLAlchemy connection/transaction model](https://docs.sqlalchemy.org/en/20/core/connections.html),
[Alembic tutorial](https://alembic.sqlalchemy.org/en/latest/tutorial.html),
[PostgreSQL 16.15 release](https://www.postgresql.org/docs/release/16.15/).

## Participation

- Richard selected the eligibility-contract checkpoint and requested checkout preparation.
- Agent performed Git setup and recorded this question register.
- The initial table, function and explanation were AI-assisted and relayed by Richard. Richard reports personally running the previous eligible-fixture demo; no terminal output was supplied. Other verification remains agent-executed.
- Agent added the submitted function to the worktree, focused tests, a malformed-value guard, reproduction commands, and learning notes. No database access, LangGraph, dependency installation, paid calls, or cloud work.
- Agent implemented evidence intake, fixture CLI, tests and operational walkthrough. Owner hands-on participation is optional and no owner execution is assumed.
- Richard supplied successful healthy-container, migration/seed invocation and database assessment output. Agent separately completed Compose integration, outage/recovery and persistent-volume verification; details are in LEARNING.md.

## Durable investigation slice (2026-10-13)

- Richard requested autonomous progress with later end-to-end discussion; no
  required exercises, quizzes or per-step confirmations. Concrete operational
  walkthroughs remain mandatory. No paid inference/cloud changes authorized.
- Next foundation is immutable, durable investigations/proposals before graph
  orchestration or approval. Existing evidence and assessment interfaces remain.
- Append-only audit tables store the original request, complete assessment,
  proposal version 1, policy and evidence bindings. Insert both records atomically.
  Failed/missing orders can be recorded for diagnosis; no order FK on audit header.
- Check reloads current evidence read-only, requires eligibility and exact binding,
  and never authorizes execution. Content restoration can restore valid_for_review;
  permanent supersession/invalidation must be defined with the approval lifecycle.
- Demo guards reject UPDATE/DELETE but do not authenticate staff or protect against
  a privileged database administrator. Roles and policy immutability must be resolved
  before approvals/public access. No application caller can submit arbitrary proposal
  JSON; application constructs it from the existing assessment.
- Original seeded carrier evidence expires with real time. Do not refresh timestamps
  to produce a desired decision. Fresh fictional seed exists only in disposable
  walkthrough/test schemas; source adapters must obtain authoritative observations.
- No stock write, compensation write, approval, worker or LangGraph is introduced.
  M1 duplicate/stock-race execution exercises remain incomplete until transactional
  write semantics are designed. This slice does not claim completion of M1/M2/M3.
- No new dependencies or lock changes were needed beyond the existing commerce group.

## Approved local execution decisions (2026-10-13)

- Richard explicitly authorized continued autonomous local work and repair loops.
- Case service now owns lifecycle; investigation generations bind reviews and prevent
  approving another case/proposal. Stale execution clears active approval permanently;
  source restoration cannot revive approval. Reinvestigation needs a fresh explicit review.
- Explicit local CLI review uses local-demo-operator. It is not authenticated staff
  access; API/session authorization remains unresolved before an exposed workspace.
- Policy/resolution versions and review/event/operation ledgers are append-only under
  database triggers. Privileged administrators can bypass guards; no such trust claim.
- Reservations increase reserved, leave on_hand unchanged, and hold exact quantities.
  No stock release, cancellation, refund reversal or fulfilment is implemented yet.
- Execution lock order: case -> order -> policy shared key lock -> sorted original
  lines/payment/shipments/lines -> sorted inventory. READ COMMITTED plus these locks
  establishes a stable bound business view. Carrier clock uses clock_timestamp after
  waits. No locks remain held while awaiting staff or external services.
- Compensation insertion increments an order revision and checks cumulative quantities
  under parent/line locks, including direct SQL insertion. Revision is concurrency
  machinery, not a history completeness attestation. Old repeatable-read writers can
  fail serialization and must retry safely instead of missing competing compensation.
- Stable operation IDs are created at approval. Unique per review/case/whole order;
  replacement, reservation, compensation, ledger and lifecycle commit atomically.
  Reconciliation checks real records/counters. Unavailable lookup is not not_found.
- Current M1 duplicate/stock-race checks and M3 local business transaction mechanisms
  are implemented and exercised. M2 durable graph/worker recovery, authenticated API,
  staff workspace and deployment still require independent completion/verification.
- GitHub model-free commerce workflow prepared; local equivalents verified. No GitHub
  Actions run or publishing is claimed. No new dependencies or paid/cloud calls.

## Worker and staff access decisions (2026-10-13)

- Durable jobs use database-clock leases, bounded attempts, SKIP LOCKED claims,
  and token fencing. Business outcome and job completion commit together; graph
  checkpoints are a separate recoverable projection. No transaction waits for staff.
- LangGraph/its PostgreSQL saver are commerce-only dependencies. Telemetry export
  is disabled. Model libraries remain excluded. No provider call is used by polling,
  investigation, approval, execution or reconciliation.
- One loopback-only Basic-auth staff operator; authenticated username binds reviews.
  Store checks happen server-side. Mutation JSON/Origin guards and strict typed
  inputs apply independently of UI controls. External exposure requires TLS and
  identity review before deployment.
- UI is structured rules mode, not general language understanding. Confirmation
  freezes exact proposal generation/hash/contents; polling cannot change an open
  approval dialog. Case service rejects superseded approval.
- Business schema 0004 and separate commerce_graph checkpoint schema survive
  restart. UI reviews are authoritative; explicit CLI resume/replay repairs an old
  graph pause. A graph pause never grants or revokes actual business permission.
- Docker app/web/base images are digest-pinned, uv/npm locks reproducible. Secrets
  stay in ignored mode-600 .env. Browser tracing is off to avoid auth-header export.
- Still unresolved before dependent milestones: provider capabilities/pricing and
  budgets, held-out commerce evaluation, cloud TLS/identity/secrets/backups/resource
  sizing and spend approval, cancellation/release/fulfilment external contracts.
  No cloud/provider milestone may be claimed complete from local demo verification.

## Staff usability clarification (2026-10-13)

- Richard clarified that product users have no technical background and do not
  use code or AI agents. Operator/developer guidance remains separate from staff
  instructions. Staff need browser access and manager-provided sign-in details.
- Starting a review creates a saved case and automatically queues its read-only
  investigation. Staff do not need to know about workers/jobs. Backend approval,
  exact quantity/hash binding, rechecking and atomic execution remain unchanged.
- Normal screens use Check order, Approve replacement, Create replacement and
  Ask for help. Missing information and failed checks have different explanations
  and next steps. Technical IDs, hashes, raw records/events are collapsed into
  support-only details; normal screens show product names and understandable results.
- Human display labels cover the two fictional variants; exact variant IDs remain
  in every business request. Future real catalogue integration must supply actual
  product names/variant attributes before broadening to new products; do not invent
  names or obscure an unknown variant's identity at approval.
- Escalation records a note but does not notify anyone. The staff screen/guide
  explicitly tells staff to share the order reference with their manager.
- These are interface changes, not independently validated usability research.
  Observe a real nontechnical staff member using the workflow before claiming it
  is easy for that audience. No mandatory quiz or exercise is required for progress.

## Optional simulated decision-provider slice

- Insertion is after the actual bundled `investigate_case` assessment, before case
  presentation/disposition. No adaptive individual-tool selection is claimed.
- First choice is `present_replacement` versus `staff_review`. It is consumed by
  the case service: preserve exact pending-review proposal or escalate eligible
  case. Blocked/unknown facts never become eligible. Approvals/execution remain
  unchanged, deterministic and mandatory. No language generation or supervisor.
- Opt-in operator CLI only. Browser/API/job worker remain rules-only; mode defaults
  to rules and reserves no provider budget. Fake recommendations/usage/prices are
  integration fixtures, not performance or real billing evidence.
- Immutable request context contains seven normalized facts, only relevant case/
  request/policy/evidence versions and fixed allowed choices; no customer messages,
  addresses, secrets or arbitrary tool output. Confidence is not permission.
- Ledger reserves count plus maximum exact Decimal cost before dispatch under a
  budget row lock. Known bounded usage settles; outcomes without known usage (including timeouts)
  retain maximum cost. Accepted request count is conservative and never refunded.
- Run ID is immutable/idempotent; dispatch marker commits before invocation.
  Reserved work can be claimed once after restart; dispatching/uncertain work is
  never automatically redispatched. Settled application can recover without calls.
- No transactions/business locks across fake work. Application locks case/business
  before the provider call row; settlement locks budget before call. Revalidate
  generation, status, proposal/hash, source versions, facts/eligibility and freshness.
  Late choices cannot overwrite newer reviews or executed cases.
- Migration0005 adds immutable budgets/call ledger and updates current-branch
  health/backup expectations. Test separate DB volume/project/ports/image tags;
  preserve the running 0004 rules app and its operational guarantees.
- OpenAI adapter/account/docs/pricing, real usage receipts/reconciliation, approval
  of spending, production database roles and hosted provider service integration
  remain unresolved before live work. No automatic request retry or model call.


## Optional offline local routing adapters (2026-10-14)

- Laya/GLiClass operator CLI modes share post-bundled-assessment validation and
  actual routing with fake mode. Browser/API/worker stay rules-only. No supervisor
  or adaptive tool selection. Existing approvals and execution services are intact.
- Model features: task, normalized facts and allowed choices only. Bindings, case
  IDs, hashes and evaluator labels are audit metadata, excluded from inference.
- One scored input: all seven facts true. Other tri-state vectors force review
  without loading. No claim of held-out generalisation from duplicated states.
- CPU four threads, batch1, one family per bounded subprocess. Offline flags before
  imports; cached pinned weight's unresolved snapshot parent, no whole snapshot
  download. Loading is inside the maximum 120-second deadline. Always kill/reap the
  owned process group, including descendants after parent exit.
- Migration0005 suffices. Local budgets require explicit zero API charge and
  null token counts. Count reservations, immutable run bindings, timeout retention
  and no redispatch remain. CPU/memory/power are not measured USD prices.
- Native scores and resource phases retained separately, confidence uncalibrated.
  Both models chose review on alltrue evidence; preserve that negative disagreement.
- Dependencies remain optional for Commerce-only CI. Reuse the pinned model
  environment or locked offline historical profile; no upgrades/downloads required.
- Actual billing/live OpenAI, production permissions, hosted adapters and model
  business-value evaluation remain future work. Original 0004 store is untouched.
