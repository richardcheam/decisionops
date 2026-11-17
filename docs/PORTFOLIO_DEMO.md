# Explain and reproduce the customer-to-staff demo

“A customer says their parcel never arrived. Before sending another one, the shop
needs to check the carrier’s updates, previous refunds or replacements, and stock.
DecisionOps puts those checks in one staff workspace. The customer gets a case
reference, staff review the exact proposal, and an authorized person approves it
and confirms creation separately. The customer then sees the verified result in
their original conversation.”

This shop and its records are fictional. Carrier data and specialist choices are
simulated. The browser workflow, database writes and approval checks are implemented.
The result is a replacement record and stock reservation, not a shipped parcel.
Time savings and live-model quality must be measured in an authorized pilot.

## Present it in five minutes

Use the single Compose quickstart and four configured fictional credentials in
[the README](../README.md). Camille owns Lyon and the split order; Alex owns other
orders in the same shop. Use two browser profiles so customer and staff sessions
stay separate. `visitor` is the Compose approver; `staff` is the investigator.

1. Camille: `/customer`, select `DEMO-LYON`, say “My parcel never arrived. Please
   report it missing.” Read the case reference. “This tells the shop which parcel
   I mean. Repeating the report doesn’t open another case.”
2. Staff: `/staff`, open that exact case. Show the customer’s words, overdue trigger
   and carrier timeline. “A customer report starts the work. It doesn’t prove loss.”
3. Ask “Fix this.” Show both specialist tracks. “One checks payment and previous
   compensation; the other checks the shipment and carrier updates. Stock and the
   shop’s policy are checked too.” Ask “What’s still missing?” without restarting.
4. Inspect one `demo-tote` for this Lyon order. Show the actual proposal ID,
   generation and hash in the dialog. “I’m approving these exact items.” Click
   **Approve replacement → Confirm approval**. Then separately **Create replacement
   → Confirm replacement**. “Now I’m asking the shop to create it and reserve stock.”
5. Show **Replacement confirmed** and Camille’s original conversation, including
   after reload. “The replacement was created. It hasn’t been shipped.” Alex’s
   session cannot access Camille’s records; the investigator cannot approve it.

Second example: open `DEMO-CONFLICT`. The carrier records say both lost and delivered.
The application keeps both and asks staff to review. `DEMO-OVERDUE` is merely late;
`DEMO-REPLACED` already has a replacement; `DEMO-HISTORY` lacks a complete history.
A split order asks which parcel is meant; partial replacement remains unsupported.

## Run the local checks without a model

From the isolated branch worktree, install the locked Commerce profile and build
using Node20+ (Node24 was used locally). Point checks at a disposable loopback
PostgreSQL16 test database; every runner creates its own schema.

```bash
uv sync --locked --only-group commerce
npm --prefix frontend ci
export COMMERCE_TEST_DATABASE_URL='postgresql+psycopg://richard@127.0.0.1:55479/commerce_delivery_test'
.venv/bin/python -B scripts/commerce_ci_tests.py postgres
.venv/bin/python -B scripts/commerce_customer_browser.py
.venv/bin/python -B scripts/commerce_delivery_browser.py
.venv/bin/python -B scripts/commerce_delivery_recovery.py
.venv/bin/python -B -m decisionops.commerce.customer_evaluation --simulate-adapter
```

The browser runner migrates/seeds synthetic records, launches the same API and workers,
uses separate real-browser sessions and checks SQL uniqueness. Set `COMMERCE_BROWSER_PATH`
if the local Playwright browser is not installed. It stops only its own processes and
drops only its generated schemas. The recovery walkthrough kills a worker after
committed specialist work and verifies restart and one replacement/reservation set.

For an interactive launch without Docker, use a **new disposable** database. Export
`COMMERCE_DATABASE_URL`, staff username/password, helper password, and the two customer
passwords. Then:

```bash
.venv/bin/alembic upgrade head
.venv/bin/python -B -m decisionops.commerce.seed
.venv/bin/python -B -m decisionops.commerce.delivery_seed
.venv/bin/python -B -m decisionops.commerce.customer_seed
.venv/bin/python -B -m decisionops.commerce.worker setup
npm --prefix frontend run build
.venv/bin/python -B scripts/commerce_delivery_local.py --port 8155
```

Open `/customer` and `/staff` at `http://127.0.0.1:8155`. The local launcher defaults
to staff username `operator` unless configured. It uses the same deterministic
specialist path and database writes; it does not establish Docker or Kubernetes launch.

## Technical follow-up

| Dependency | Its job in this workflow |
|---|---|
| React, TypeScript; Vite/Node | Customer and staff screens; compile/build the browser app. |
| FastAPI, Pydantic, Uvicorn | Typed role-specific HTTP requests, server authentication and ownership checks. |
| PostgreSQL, SQLAlchemy, psycopg, Alembic | Business records, transactions, locks, immutable audits and schema upgrades. |
| LangGraph and PostgreSQL checkpoints | Staff investigation branches and restart from committed progress. |
| Playwright | Separate browser sessions and the full customer/staff acceptance journey. |
| LangSmith (already a graph dependency) | Optional explicit metadata export; no automatic input/output tracing. |
| PyYAML (`commerce-deploy` only) | Offline Compose/Kubernetes tooling, not application runtime. |
| Compose/Nginx; Kubernetes/Kustomize; Terraform | Same-app packaging, local deployment preparation, proposed AWS staging. |

The model adapter uses separate customer, staff and investigator action contracts.
It can classify intent and choose an allowed read; server code owns identity, scope,
eligibility and all writes. Explicit reporting intent is checked independently of
model output. Simulated adapter tests run the same cases through this boundary.
They establish compatibility and business checks, not live-model quality or savings.
The historical `RecommendationAdapter` protocol is separate; the new adapter plugs
into the existing specialist graph using its `SpecialistRequest` contract.

Tracing stays off without `COMMERCE_LANGSMITH_EXPORT=1` and a key. Any hosted export
needs separate authorization. Only server investigation IDs, attempt/step counts and
allowlisted node/tool/outcome/retry/fallback/stop metadata are eligible. Customer text,
order IDs, stock records, credentials and raw exceptions never enter exported events.
Inspection and export use a bounded background queue; exporter failure cannot hold
up a case. Local fake-exporter and installed-SDK serialization checks cover this;
hosted LangSmith delivery remains unverified.

[Checkpoint](PORTFOLIO_CHECKPOINT.md) records the candidate and actual command results.
[Deployment notes](PORTFOLIO_DEPLOYMENT.md) distinguish static validation and disposable
restore from pending container/cluster launch, deployed browser/recovery and rollback.
AWS resources are prepared only. No provisioning, paid calls, hosted export, real
carrier integration, push or publication is part of these local checks.
