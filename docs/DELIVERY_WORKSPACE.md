# Delivery workspace operation

Use the root Compose demo in README, or run the same app locally against an
**isolated, disposable PostgreSQL16 UTF8 database**. Preserve historical volumes
and other worktrees. No reset command below targets an existing merchant database.

## Local launch without Docker

Requires Python3.12, uv, Node20.19+ (verified Node24), PostgreSQL16 and a Chromium
browser. Supply the URL of a newly created database, for example a local test
cluster's `postgresql+psycopg://USER@127.0.0.1:PORT/NEW_DATABASE`. Do not put private
credentials in committed files. Shell commands assume the project root:

```bash
uv sync --locked --only-group commerce --only-group commerce-api --no-python-downloads
npm --prefix frontend ci --no-audit --no-fund
npm --prefix frontend run build
export COMMERCE_DATABASE_URL='postgresql+psycopg://USER@127.0.0.1:PORT/NEW_DATABASE'
export COMMERCE_STAFF_PASSWORD='choose-a-local-demo-password'
export COMMERCE_HELPER_PASSWORD='choose-a-different-staff-password'
.venv/bin/alembic upgrade head
.venv/bin/python -B -m decisionops.commerce.seed
.venv/bin/python -B -m decisionops.commerce.delivery_seed
.venv/bin/python -B -m decisionops.commerce.worker setup
.venv/bin/python -B scripts/commerce_delivery_local.py --port 8155
```

Open http://127.0.0.1:8155. `operator` is the approver; optional `staff` uses the
helper password and can investigate but cannot approve or execute. Existing API
callers retain the configured primary account's approval path. Local production
identity providers are not claimed. The launcher serves built React from the
existing FastAPI app and starts the existing Commerce and staff workers. Ctrl-C
stops all children. It never starts a model or enables a paid adapter.

The FR seed adds orders prefixed `DEMO-` alongside unchanged historical `ORD-`
fixtures. `--now 2026-11-11T12:00:00+00:00` injects the seed clock for frozen tests;
reporting functions and `create_app(demo_clock=...)` support injected reporting
clocks. Routine browser demos seed with current database time. Repeated seed does
not overwrite old observations or refresh carrier timestamps. Use a **new isolated
database** to reset or start another reporting week, then repeat migration/seed.

## Verification

Use another disposable PostgreSQL database ending in `_test` for the full suite
(the retained shop fixture enforces this name before creating its own database/role). Test classes create unique
schemas, migrate them, and remove only their own schemas. Migration coverage includes
both fresh head and a separate supported0009-to0010 upgrade preserving legacy rows.

```bash
mkdir -p runs
export COMMERCE_TEST_DATABASE_URL='postgresql+psycopg://USER@127.0.0.1:PORT/commerce_delivery_test'
python3 -B -S scripts/commerce_ci_tests.py dependency-free
.venv/bin/python -B scripts/commerce_ci_tests.py postgres
.venv/bin/python -B -m unittest discover -s tests -v
.venv/bin/python -B scripts/commerce_delivery_recovery.py
.venv/bin/python -B scripts/commerce_worker_walkthrough.py
.venv/bin/python -B scripts/commerce_execution_walkthrough.py
.venv/bin/python -B -m decisionops.commerce.comparison --postgres > runs/delivery-product-comparison.json
.venv/bin/python -B -m decisionops.commerce.comparison --adversarial > runs/delivery-controller-simulation.json
npm --prefix frontend run build
```

The dependency-free profile reports optional dependency/database/model skips; the
required PostgreSQL profile fails on **any** skip. The full locked Commerce-only
profile intentionally omits heavyweight ML dependencies and reports those skips.
No paid endpoint is used in any of these checks. Create `runs/` before redirection.

Run browser acceptance from the project root with the isolated runner. It creates
fresh FR data, synthetic approver/helper accounts and a real foreign-store case:

```bash
# Optional system Chromium/Brave; otherwise install Playwright Chromium locally.
export COMMERCE_BROWSER_PATH=/usr/bin/brave-browser
.venv/bin/python -B scripts/commerce_delivery_browser.py
```

Direct Playwright invocation requires the runner's foreign-store fixture and
`COMMERCE_FOREIGN_CASE_ID` and `COMMERCE_STALE_CASE_ID`; an ordinary manual demo
seed alone does not supply these verification fixtures.

The browser suite performs a fictional replacement. Reset using a new isolated
browser database before repeating the entire suite. The legacy suites remain under
`tests`, `staff-tests`, `multi-agent-tests`, and `shop-tests`; their fixtures and
launchers are retained. `.github/workflows/commerce.yml` keeps the established
model-free/PostgreSQL/browser checks; the PostgreSQL profile includes the new
migration, carrier, chat and specialist acceptance modules.

## Authority and recovery

Carrier events have stable source/external identities, parcel bindings, event and
receipt times, verification flags and immutable original fixture records. Exact
replay retains first receipt. Changed content for one identity remains as a second
record, never overwrites evidence. Verified terminal events outrank late transit;
opposing verified lost/delivered records project unknown and force review. Carrier
outage and nonreceipt do not establish loss. Parcel status and operational triggers
are distinct. Resolved queue entries retain trigger and case history.

Only Commerce creates proposals, approves, executes and reconciles. The dispatcher
derives case/order/parcel/item scope from server state and admits typed scoped
reads. The order branch owns payment and compensation; the shipment branch owns
fulfilment and carrier evidence; the coordinator binds manifest/policy, checks
inventory and joins committed evidence. Private model reasoning is never requested
or displayed. The registration contract in `workflow_registry.py` has a paper-only
returns definition; returns cannot dispatch or resolve a case in this release.

Runs cap tool attempts12, decisions16, each tool2 attempts, specialist decisions4,
run deadline240sec, branch60sec and decision5sec. A transient unavailable specialist
read can retry once within all caps. Wrong, expired, conflicted or late evidence
cannot authorize a proposal. A private safety reread can invalidate gathered facts,
but cannot fill a missing evidence requirement. Follow-up freshness reads do not
write business state or consume a new investigation run.

PostgreSQL request identities, short transactions, leases, ownership fences and
committed dispositions prevent late writes and redispatch of uncertain decisions.
A restart reconstructs progress from committed business records. Approval binds
proposal ID, generation and hash; confirmation is separate. Duplicate confirmation
while queued returns the same job; after completion it returns409 while the verified
operation remains available. Uncertain non-idempotent operations require
reconciliation. Historical investigation facts are labelled separately from a
verified execution, which remains the authority for a completed replacement.

For a fresh, automated browser schema and direct PostgreSQL uniqueness assertions, run from the root:

```bash
.venv/bin/python -B scripts/commerce_delivery_browser.py
```

This runner uses its own synthetic approver/helper accounts, builds the frontend,
launches the same app on8157, runs all delivery browser tests, verifies the one
replacement/reservation set, then stops its children and drops only its own schemas.

The retained operator CLI tests additionally require the guarded historical test
endpoint: URL host127.0.0.1/port55446/database`commerce_decisions_test`/user
`commerce_decisions`, with PostgreSQL reporting server port5432 (the established
Docker port mapping). Use the existing isolated setup in
[OPENAI-DECISIONS.md](commerce/OPENAI-DECISIONS.md). A user-local PostgreSQL5432 plus
loopback TCP forwarding55446→5432 is equivalent and was verified in this session.
This guard remains unchanged. A generic isolated database runs the required
PostgreSQL profile and new acceptance suites; the **full** repository suite needs
this identity and a database name ending in`_test`.
