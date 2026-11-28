# Run and verify the fictional shop

This packages the existing React/FastAPI application, its PostgreSQL database and
both background workers. The shop, customers, orders and carrier data are fictional.
The default works without a model key or tracing credentials. No command here
requires publishing a repository, sending traces or connecting a real carrier.

## Compose launch

Use the [README quickstart](../README.md#run-the-demo). The init container
migrates PostgreSQL, seeds the three fictional cases and sets up checkpoints
before the API and workers start. Nginx forwards both `/api/` and
`/customer-api/`. Check health with `bash scripts/demo.sh health`.

`bash scripts/demo.sh stop` keeps the database volume. Use the
[fictional demo reset](ARCHIVE.md#reset-the-fictional-compose-demo) to rehearse
the Lyon flow on a fresh database.

## Kubernetes uses the same app

`deploy/kubernetes` is the only Kubernetes packaging approach: plain manifests with
one Kustomize entry point. It includes PostgreSQL plus a PVC for a disposable local
rehearsal, a migration/seed Job, API, execution/queue worker, staff investigation worker,
web, Services and ConfigMaps. Migration and worker processes receive only the
database URL; customer/staff passwords are available only to the API. Runtime secrets are supplied separately; none are
committed. The app and workers run without service-account tokens or Linux capabilities,
with read-only root filesystems and bounded CPU/memory. The web image uses its existing
Nginx runtime; its cluster config replaces Docker's DNS-specific resolver.

Offline checks:

```bash
UV_PROJECT_ENVIRONMENT=.venv-deploy uv run --locked --only-group commerce-deploy python scripts/commerce_deployment_verify.py
kubectl kustomize deploy/kubernetes > runs/kubernetes-rendered.yaml
```

The optional locked `commerce-deploy` group supplies PyYAML as a local deployment-tool dependency. It checks
migration parity, proxy routing, selectors, roles' configured credentials and worker
commands; it does not prove a cluster launched.

For an authorized **local disposable** rehearsal, build images tagged with the exact
candidate SHA, create a dedicated kind cluster and load those images. This does not
use AWS or push images anywhere:

```bash
candidate_sha=$(git rev-parse HEAD)
docker build -f docker/Dockerfile.app -t decisionops-portfolio-app:"$candidate_sha" .
docker build -f docker/Dockerfile.web -t decisionops-portfolio-web:"$candidate_sha" .
kind create cluster --name decisionops-portfolio
kind load docker-image --name decisionops-portfolio decisionops-portfolio-app:"$candidate_sha" decisionops-portfolio-web:"$candidate_sha"
python3 scripts/commerce_kubernetes_rehearsal.py \
  --context kind-decisionops-portfolio \
  --app-image decisionops-portfolio-app:"$candidate_sha" \
  --web-image decisionops-portfolio-web:"$candidate_sha"
```

The rehearsal accepts only an explicit `kind-*` context and uses the
`decisionops-local-portfolio` namespace. It refuses to replace existing namespace
credentials, which avoids resetting a previous database password. It waits for
PostgreSQL and successful migrations before applying the application workloads.
It checks web/API readiness, replaces worker Pods, deliberately rolls out a failing
API process using the same local image, then restores the previous Pod template and
checks readiness. That tests application rollback; it does not downgrade a database.
It leaves the namespace available for inspection and prints its precise cleanup command.

Re-run the actual browser suite against the deployed app; readiness checks alone are
not the customer workflow or proof that interrupted business effects resumed:

```bash
kubectl --context kind-decisionops-portfolio -n decisionops-local-portfolio \
  port-forward --address=127.0.0.1 service/web 8166:8080
# In another terminal, with the same synthetic passwords:
export COMMERCE_STAFF_USERNAME=visitor
export COMMERCE_STAFF_PASSWORD="$COMMERCE_DEMO_PASSWORD"
export COMMERCE_WEB_URL=http://127.0.0.1:8166
export COMMERCE_COMPACT_DEMO=1
(cd frontend && npx playwright test --config playwright.customer.config.ts)
```

The deployment browser check must use a fresh fixture; a previously executed Lyon
case must not be misrepresented as a newly completed flow. Verify the same case ID,
customer ownership denials, exact approval and separate confirmation, then count the
replacement and reservation rows. Test business-worker interruption during committed
work, not only an idle Pod restart. The existing recovery walkthroughs provide the
separate direct-local checks; a cluster run is required to claim these on Kubernetes.

Rollback is limited to application revisions compatible with the installed schema.
The previous release expects 0012 and fails readiness against 0013. Rehearse
application rollback with images that both support the installed schema. A
schema downgrade requires a reviewed migration or a verified restore into a
new environment.

## Disposable database restore

The direct restore rehearsal needs PostgreSQL client tools (`pg_dump`, `pg_restore`)
and a loopback-only test server where the test user may create databases:

```bash
export COMMERCE_TEST_DATABASE_URL='postgresql+psycopg://richard@127.0.0.1:55479/commerce_delivery_test'
.venv/bin/python -B scripts/commerce_portfolio_restore.py \
  --pg-bin /path/to/postgresql/16/bin
```

It never dumps or changes the database in that URL. It creates new uniquely named
source and target databases and seeds the same three cases as Compose. It runs
the simulated specialist workflow for Lyon, creates and reconciles the approved
replacement, then dumps the source and restores it into the target. It compares
all user tables by row count and content hash, checks readiness, and reconciles
the restored replacement. The rehearsal drops both generated databases afterward.
It also compares the saved investigation and execution graph progress after restore.
A private ignored `runs/portfolio-restore-*/` directory retains the synthetic dump and
verification summary. In a real pilot, a restore test must separately cover the
actual storage, credentials, backup schedule and recovery objectives.

## Local worker recovery checks

Install the locked Commerce profile and set `COMMERCE_TEST_DATABASE_URL` to a
disposable loopback PostgreSQL database as in the [runbook](commerce/RUNBOOK.md#model-free-regression-checks).
From the checkout, run:

```bash
.venv/bin/python -B scripts/commerce_delivery_recovery.py
.venv/bin/python -B scripts/commerce_worker_walkthrough.py
.venv/bin/python -B scripts/commerce_execution_walkthrough.py
```

The delivery check interrupts a worker after committed specialist work and checks
that the resumed investigation reuses that progress. It also exercises repeated
execution confirmation and verifies a single replacement and stock reservation.
These direct-local checks cover worker and database behavior. Use the runtime
CI results for the tested commit to verify deployed behavior and rollback.

## Draft PR runtime workflow

The `Verify portfolio container runtime` workflow checks out the PR head commit
and records it in each job summary. It builds and launches the root Compose stack
and installs the same images in an isolated kind cluster in separate jobs. The
Compose job stops PostgreSQL after the browser journey and checks for HTTP 503,
restored readiness and the same verified Lyon records after restart. The
Kubernetes job observes an injected API failure, restores the original deployment
template and runs the customer browser suite against the rolled-back application.

During the Lyon browser journey, the CI probe pauses the ordinary investigator,
queues the work through staff chat and runs the specialist worker code in the
deployed application image using the same database. The probe forces a hard exit
after the order specialist commits. The ordinary investigator reclaims the job
after its lease expires. After execution and a repeated confirmation, the probe
compares the committed call IDs and checks the replacement and reservation counts
in PostgreSQL. CI logs contain the resulting counts and the tested SHA. Browser
traces and database dumps are excluded from uploads.

## Hosted Shopify development pilot

Use the existing app and web images with one HTTPS origin and persistent
PostgreSQL. Start with a dedicated database and designate the public URL
`https://<pilot-host>/pilot`. Hosted pilot mode serves merchant sessions under
`/pilot-api/`. The local customer/staff demo uses its own routes when the pilot
origin is unset.

| Setting | Purpose |
|---|---|
| `COMMERCE_DATABASE_URL` | PostgreSQL DSN available to the app and migration job |
| `COMMERCE_PILOT_ORIGIN` | Exact public HTTPS origin with no path |
| `COMMERCE_SHOPIFY_DEV_SHOPS` | Comma-separated approved development shop domains |
| `COMMERCE_SHOPIFY_CLIENT_ID` and `COMMERCE_SHOPIFY_CLIENT_SECRET` | Shopify Dev Dashboard app credentials |
| `COMMERCE_SHOPIFY_TOKEN_KEY` | URL-safe base64 encoding of 32 random bytes for encrypting stored OAuth tokens |

Supply credentials through the host secret manager. In Kubernetes use an
API-only secret. Configure the external HTTPS ingress to forward `/pilot` and
`/pilot-api/` to the existing web service. Keep callback query strings, cookie
headers, and request bodies out of access logs, error reports, and traces.
The app image disables Uvicorn access logging and the provided Nginx config
disables logging in the pilot API location. Keep the token key available for
restore. Losing it requires reconnecting the shop.

1. Create a standalone app with custom distribution in Shopify Dev Dashboard.
   Use the chosen development shop, set the callback to the pilot origin plus
   `/pilot-api/shopify/callback`, and configure `read_orders`, `read_returns`
   and `write_returns`. DecisionOps pins Admin GraphQL to `2026-10` and requests
   expiring offline access. [Shopify standalone installation](https://shopify.dev/docs/apps/build/authentication-authorization/authenticate-standalone-apps) · [Expiring offline tokens](https://shopify.dev/docs/apps/build/security/credentials-and-data/use-expiring-offline-access-tokens)
2. Use the same app image and database credentials to run `alembic upgrade head`
   before replacing application pods. The old app expects revision `0013`;
   the pilot expects `0015`. Preserve a tested backup and the token key before
   rollout. Roll back only to an image compatible with the installed schema,
   or restore the known-good backup to a separate database before switching over.
   A restore may roll durable dispatch claims back in time. Reconcile Shopify
   returns against the restored cases before enabling any writes.
3. In a private operator session on the migrated database, bootstrap the
   first approver. The command prompts for the password.

   ```bash
   python -m decisionops.commerce.pilot_identity bootstrap \
     --store-id training-shop --store-name 'Training shop' --email manager@example.test
   ```

4. Use a Shopify test-payment order, fulfill it, then mark it delivered in
   Shopify Admin. DecisionOps accepts only test orders. Configure the verified
   `app/uninstalled` webhook at `/pilot-api/shopify/webhooks/uninstalled` if
   managing subscriptions through Shopify app configuration. Orders are imported
   on manual resync. Proposal and confirmation read source records directly.
   [Shopify development test orders](https://help.shopify.com/en/manual/intro-to-shopify/initial-setup/setup-prepare-for-launch) · [Mark an order delivered](https://help.shopify.com/en/manual/fulfillment/fulfilling-orders/single-fulfillment#mark-an-order-as-delivered)

For acceptance, use separate clean browser sessions for the approver and
support agent. Match the verified reference in DecisionOps to the same return
in Shopify Admin. Mocked tests and the fictional demo cannot establish that
result.
