# Commerce operating runbook

Use the [demo quickstart](../../README.md#run-the-demo) for Compose. It configures
the database, runs migrations and seeds the fictional shop. Use the
[deployment guide](../PORTFOLIO_DEPLOYMENT.md) for worker recovery and database
restore.

## Database connection

For a direct host launch, set `COMMERCE_DATABASE_URL` to a PostgreSQL 16 database
using the `postgresql+psycopg://` scheme. Use a new disposable database for the demo.
Run migrations, seed the portfolio data and set up worker checkpoints in the
order shown in the [host launch guide](../LOCAL_MODEL.md#run-the-app). Use
`--mode mock-specialists` on the host launcher to run without a model.
The API’s `/health` endpoint checks readiness. If it fails after changing images,
check whether the app supports the installed schema before restarting workers.

An existing demo volume keeps its original fixture and saved work. Use the
[fictional demo reset](../ARCHIVE.md#reset-the-fictional-compose-demo) only when
you want to discard those records.

## Model-free regression checks

Install the locked Commerce dependencies, then point the tests at a disposable
loopback PostgreSQL database. The database test profile creates temporary
schemas and fails if a required test skips.

```bash
uv sync --locked --only-group commerce --only-group commerce-api
export COMMERCE_TEST_DATABASE_URL='postgresql+psycopg://USER@127.0.0.1:PORT/commerce_delivery_test'
python3 -B -S scripts/commerce_ci_tests.py dependency-free
.venv/bin/python -B scripts/commerce_ci_tests.py postgres
```

The older provider CLI tests require the exact PostgreSQL identity in the
[Commerce CI service](../../.github/workflows/commerce.yml), including loopback
port 55446 mapped to server port 5432. Use the [customer browser smoke test](../PORTFOLIO_DEMO.md#run-the-browser-smoke-test)
for browser verification and SQL counts on a fresh fixture.

## Offline operator configuration checks

The optional [Decisions operator kit](../../scripts/commerce_decisions_operator/README.md)
has a verifier for its [configuration](../../scripts/commerce_decisions_operator/api-decisions-proposed.json).
The [Nano configuration](../../data/commerce/api-nano-proposed.json) is an SDK
test fixture. Its tests use mocked HTTP and verify that supplying credentials and
a configuration alone cannot authorize a live request.
