# Run and verify the fictional shop

This packages the existing React/FastAPI application, its PostgreSQL database and
both background workers. The shop, customers, orders and carrier data are fictional.
The default works without a model key or tracing credentials. No command here
requires publishing a repository, sending traces or connecting a real carrier.

## One Compose quickstart

Choose four different fictional passwords of at least 16 characters. Configure
these in your shell; do not put real passwords in screenshots, commands committed
to Git, or the guide:

```bash
export COMMERCE_DEMO_PASSWORD='fictional-manager-demo-only'
export COMMERCE_HELPER_PASSWORD='fictional-investigator-only'
export COMMERCE_CUSTOMER_CAMILLE_PASSWORD='fictional-camille-demo-only'
export COMMERCE_CUSTOMER_ALEX_PASSWORD='fictional-alex-demo-only'
export COMMERCE_DEMO_MODE=mock-specialists
bash scripts/demo.sh build
bash scripts/demo.sh start
bash scripts/demo.sh health
```

Open `http://127.0.0.1:8133/customer` as `camille`; open
`http://127.0.0.1:8133/staff` in another browser session as `visitor`.
The investigator account is `staff`. Use the corresponding configured password.
`alex` is the second customer and owns different orders in the same shop.

The init container migrates the database, seeds the two fictional delivery cases and their customers, and
sets up graph checkpoints before the API and workers start. The web server forwards
both `/api/` and `/customer-api/`; React handles `/staff` and `/customer`.
`rules` remains available as a model-free investigation mode; `mock-specialists`
shows both specialist tracks. Neither mode makes paid model calls.

In Camille's conversation, select the Lyon order and report that the parcel did
not arrive. Keep the returned case reference. Staff open that same case, investigate,
review the exact proposal, approve, then confirm creation separately. Return to
Camille's original conversation to see the reconciled replacement result. A created
replacement and reserved item do not mean a parcel was shipped. Do not claim tracking
until a verified shipment exists.

`bash scripts/demo.sh stop` preserves the named database volume. Deleting the
fictional database additionally requires the existing explicit reset guard documented
by `scripts/demo.sh`; stopping the app does not silently delete records.

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

The rehearsal accepts only an explicit `kind-*` or `k3d-*` context and uses the
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
The old 0010 release rejects an 0011 database at readiness; do not present reverting
to that old image as a supported rollback. A schema downgrade requires its own
reviewed data migration or a verified restore into a new environment.

## Disposable database restore

The direct restore rehearsal needs PostgreSQL client tools (`pg_dump`, `pg_restore`)
and a loopback-only test server where the test user may create databases:

```bash
export COMMERCE_TEST_DATABASE_URL='postgresql+psycopg://richard@127.0.0.1:55479/commerce_delivery_test'
.venv/bin/python -B scripts/commerce_portfolio_restore.py \
  --pg-bin /path/to/postgresql/16/bin
```

It never dumps or changes the database in that URL. It creates new uniquely named
source and target databases, migrates and seeds synthetic source records, creates
and reconciles an actual approved replacement, dumps and restores the source, compares
all user tables by row count and content hash, validates readiness/guards, and
reconciles the restored replacement. Both generated databases are dropped afterward.
It also compares the saved investigation and execution graph progress after restore.
A private ignored `runs/portfolio-restore-*/` directory retains the synthetic dump and
verification summary. In a real pilot, a restore test must separately cover the
actual storage, credentials, backup schedule and recovery objectives.

## Runtime evidence from PR #14

[Runtime CI](https://github.com/richardcheam/decisionops/actions/runs/44406587710)
tested the reviewed commit `b18eeab02dcbccd357422861c310c0b26791cb42`.
A fresh Compose launch and an isolated kind install each passed all five customer
browser tests. The Kubernetes run restored the original application Pod template
after an injected API failure and passed the browser suite after rollback.
Both runtimes recovered from a worker-process exit after a specialist commit.
The worker reused two committed calls, and PostgreSQL contained one replacement
and one stock reservation after repeated confirmation.

[Commerce regression CI](https://github.com/richardcheam/decisionops/actions/runs/44406587606)
tested a PR merge commit with the same source tree. The required PostgreSQL
suite passed 265 checks, and full discovery recorded 607 passes and four
optional skips. Mid-task termination of the ordinary Kubernetes worker Pod
and schema downgrade remain untested.

## Earlier local validation

These checks were run locally on the integrated working tree with schema 0011.
The local runtime limitations explain why the deployed tests ran in CI.

| Check | Observed result |
|---|---|
| `python3 scripts/commerce_deployment_verify.py` | Passed seven packaging checks over 12 Kubernetes objects. |
| `kubectl v1.34.3 kustomize deploy/kubernetes` | Rendered successfully, offline. Binary checksum verified against official download. |
| Rendered manifests against upstream Kubernetes v1.34.3 OpenAPI definitions | All 12 objects passed offline JSON Schema validation, translating the Kubernetes `int-or-string` format to the matching JSON Schema union. |
| Terraform 1.12.2 `fmt -check` | Passed. |
| Terraform `init -backend=false -input=false` | Installed signed HashiCorp AWS provider 6.73.0; lock file retained. No AWS API request required. |
| Terraform `validate` | Passed provider schema/configuration validation. No plan or apply. |
| Direct PostgreSQL restore script | Passed on 0011: 49 user tables matched, restored replacement reconciled, two populated worker graphs restored. Evidence: ignored `runs/portfolio-restore-5xkein7l/verification.json`. |
| Docker runtime | Blocked: account cannot access `/var/run/docker.sock`. |
| Alternate local runtime | Root-only containerd socket; user namespace mapping refused by host. No permissions changed. |
| Isolated cluster | Unverified: no usable local runtime; named kind context is absent. |
| Cluster browser, worker business recovery and rollback | Unverified; prepared scripts and local application tests do not establish deployed results. |

All container/database records are synthetic. No AWS provisioning, ECR push, hosted
telemetry, paid model call or real integration was performed.

## Prepared AWS staging and dependency purposes

`infra/terraform/aws-staging` prepares private EKS plus one managed node, private
PostgreSQL 16 on RDS, immutable app/web ECR repositories, and a private encrypted,
versioned backup bucket. It assumes an existing reviewed VPC and private subnets.
It does not apply resources, publish images, establish a public endpoint or connect
merchant systems. Choose a supported EKS version and review IAM, network access,
state storage, TLS/identity, backups and costs before an authorized plan/apply.
See that folder's README for the preparation boundary and validation commands.

| Component | Purpose in the delivered workflow |
|---|---|
| React/TypeScript and Vite/Node | Customer/staff screens and browser build. |
| Python/FastAPI/Pydantic | Typed customer/staff requests and backend access checks. |
| PostgreSQL/SQLAlchemy/psycopg/Alembic | Durable business records, transactions, access and migrations. |
| LangGraph/Postgres checkpoint saver | Staff specialist workflow and restart progress. |
| Playwright | Real browser customer/staff acceptance. |
| Optional LangSmith adapter | Allowlisted investigation metadata when explicitly enabled; no default export. |
| Nginx/Compose | One local app quickstart and both API route proxies. |
| Kubernetes/Kustomize | Same app and workers packaged for isolated deployment and rollout. |
| Terraform/AWS provider | Prepared staging resources; local validation only in this session. |
| PyYAML | Local manifest contract checks/rehearsal input; not a business dependency. |
| PostgreSQL dump/restore tools | Disposable recovery rehearsal. |

Older model-training libraries elsewhere in the repository are not required by this
Commerce-only application path.

Implementation references: [Kustomize documentation](https://kubernetes.io/docs/tasks/manage-kubernetes-objects/kustomization/),
[Terraform AWS EKS resource](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/eks_cluster).

## Runtime CI workflow

The `Verify portfolio container runtime` workflow checks out the PR head commit
and records it in each job summary. It builds and launches the root Compose stack
and installs the same images in an isolated kind cluster in separate jobs. The
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
