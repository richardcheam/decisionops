# Customer-to-staff portfolio design

## Goal and baseline
Build the fictional Paris shop's complete missing-parcel journey on reviewed source
`8307701fceb9438527e9649257695d982dd8cc71`. Reuse the React/FastAPI app, PostgreSQL,
carrier ingestion, LangGraph investigations and existing workers. The owner explicitly
asked the implementer to make routine design decisions and proceed without another
design approval round. Source remains local on `feat/customer-staff-portfolio`.

## Approach and flow
Extend the existing application rather than build another customer backend. A separate
service would duplicate admission and authorization; an unauthenticated storefront
would not satisfy ownership. `/customer` and `/staff` serve role-specific React entry
points; `/customer-api` and existing `/api` enforce separate backend role boundaries.
Local demo credentials are configured by the operator; customer identity comes from
server authentication, never text, model output or request customer IDs.

Two seeded fictional customers own different DEMO orders in the same store. A
customer selects an owned order, asks delivery status, explicitly reports nonreceipt,
and receives the canonical case reference. Multiple parcels require clarification.
Typed customer actions only read owned records or file an explicit scoped report.
Model classification cannot create intent or parcel scope absent from the message
and server selection. Staff typed actions remain report/investigate/status; approval
and execution remain separate existing authenticated endpoints and dialogs.

Admission calls `delivery.report_nonreceipt` and reuses its shop fence and parcel/case
link. Do not lock an order before this scanner path. Store each customer submission
separately from overdue triggers and immutable carrier events. Request keys and
conversation locking prevent replay; the canonical link prevents concurrent duplicate
cases. Staff investigate the same case through existing LangGraph workers. Status
questions read saved progress without resetting proposals or approvals.

Customer conversation refresh projects saved business records through an explicit
allowlist. It shows case received/in review/replacement created only after verified
reconciliation; tracking/shipping requires a verified shipment. Never return staff
notes, evidence internals, stock quantities or compensation history. The customer
can return to the original saved conversation to see the current verified outcome.
A replacement record or reservation does not mean shipment.

## Data and migration
Add customers, customer/order ownership, customer conversations/messages and immutable
customer reports in migration 0011. Conversation selection and pending clarification
are server-owned. Customer reports point to the canonical existing case and parcel.
Extend schema readiness to the new head and preserve supported 0010 upgrades. Existing
business/audit tables and authority remain unchanged.

## Model and observability boundaries
Retain model-free deterministic demo routing and specialist choices. Provide one
bounded injectable model adapter through typed role action interfaces for evaluation;
transport cannot return identity, approval, execution or eligibility. Compare frozen
cases with recorded observed results; report live quality/latency/cost unmeasured when
no authorized model run exists. Optional LangSmith export requires explicit opt-in and
credentials. Export only allowlisted graph/tool/retry/fallback/stop metadata correlated
by server investigation ID, never customer text, record payloads, credentials or model
prompts. Export failures and deadlines must not block investigations. Test with a local
fake exporter; hosted export remains pending absent authorization.

## Packaging and verification
Keep one Compose quickstart for the same API, web, workers and database. Add one
Kubernetes manifest approach with isolated namespace, migrations before rollout and
application rollback procedure. Prepare AWS staging Terraform without apply or cloud
credentials. Try an isolated local cluster, browser workflow, worker recovery,
rollback and disposable PostgreSQL backup/restore; mark concrete environment blockers
rather than claim static manifests were deployed. No paid calls, hosted export, AWS
provisioning, real integrations or publication are authorized by this design.

## Acceptance checks
1. Real browser: customer reports Lyon; separate staff session opens identical case.
2. Same-store second customer cannot access order/parcel/case/conversation; ordinary
   investigator cannot approve/execute, including direct requests and guessed IDs.
3. Concurrent/replayed reports and carrier events yield one case; split scope clarifies;
   stale/conflicting authoritative evidence requires review. Use normal ingestion.
4. Exact proposal approval then separate confirmation; SQL one replacement/reservation;
   original customer conversation shows reconciled replacement, never invented shipment.
5. Worker interruption and duplicate confirmation leave one effect set; optional tracing
   records resume/failure without sensitive data and fails open during exporter outage.
6. Applicable PostgreSQL/browser/migration/deployment checks, restore and rollback;
   concise reproducible guide, purposeful dependencies and exact-SHA supervisor review.

## Review risks
Test customer identity collisions with staff; foreign IDs in every route and replay;
model-generated replacement scope; concurrent scan/report lock ordering; stale proposal
on customer polling; customer-visible status before reconciliation; privacy on trace
exceptions; worker/rollback schema compatibility. Sol High supervisor stays read-only.
