# Review the local staff milestone

Staff select a fictional order, click **Start review**, read clear evidence checks,
confirm an exact replacement approval, and explicitly create the replacement.
The result is verified from PostgreSQL records. Missing evidence differs from a
failed condition. Product users need only the browser; see STAFF-GUIDE.md.

This is a loopback-only, single-operator demonstration. HTTP Basic credentials in
memory and local HTTP are not production identity/TLS. No real shipment, refund,
message, model call, AWS resource or automatic manager notification is produced.

## Guarantees and the tests to inspect

| Boundary | Implementation | Demonstrating tests |
| --- | --- | --- |
| Staff permission, store/order binding, strict JSON/origins | `decisionops/commerce/api.py` | [test_commerce_api.py](../../tests/test_commerce_api.py): `test_authentication_and_json_origin_checks`, `test_strict_input_and_store_binding` |
| Exact proposal, generation/hash, permanently invalidated approval | `proposals.py`, `cases.py` | [test_commerce_execution.py](../../tests/test_commerce_execution.py): `test_wrong_proposal_hash_generation_and_case_are_rejected`, `test_stale_approval_is_permanently_invalidated`; browser superseded-dialog test |
| Lock ordering, last unit, duplicate compensation, atomic rollback | `cases.py`, `execution.py`, migration `0003` | [test_commerce_execution.py](../../tests/test_commerce_execution.py): `test_two_orders_contend_for_last_available_unit`, `test_two_cases_for_same_order_do_not_duplicate_compensation`, `test_direct_concurrent_refunds_cannot_overcompensate`, `test_mid_transaction_failure_rolls_back_every_write` |
| Operation IDs and reconciliation of an uncertain response | `execution.py` | `test_lost_response_after_commit_reconciles_without_second_reservation`, `test_retry_reconciliation_uses_one_stock_snapshot_during_other_commit`, `test_reconcile_missing_and_inconsistent_records_never_claims_success` |
| Lease expiry, attempts, stale-worker fencing | `jobs.py`, migration `0004` | [test_commerce_jobs.py](../../tests/test_commerce_jobs.py): `test_claim_and_fence_reclaimed_lease`, `test_expired_lease_during_business_work_rolls_back` |
| Business commit precedes separate graph projection; replay is safe | `workflow.py`, `worker.py` | [test_commerce_jobs.py](../../tests/test_commerce_jobs.py): `test_checkpoint_failure_after_commit_replays_without_new_investigation`, `test_durable_review_interrupt_resumes_only_after_real_approval` |
| Unknown history, unsupported partial cases, wrong shipment | `read_tools.py`, `evidence.py` | [test_commerce_postgres.py](../../tests/test_commerce_postgres.py): `test_incomplete_history_never_means_no_compensation`, `test_partial_shipments_and_compensation_require_review`, `test_wrong_order_shipment_is_not_loss_evidence` |

Paths without prefixes in the implementation column are under
`decisionops/commerce/`; all Python tests are under `tests/`. Browser tests are
[workspace.spec.ts](../../frontend/tests/workspace.spec.ts). The graph never grants permission, and a
checkpoint/trace never proves a business write. Execution locks case, order,
policy, sorted business rows and inventory, checks current database time and
records, then writes the operation, replacement, reservation, resolution and
lifecycle event in one transaction. Reconciliation compares actual records and
stock ledger in a consistent snapshot. External fulfilment would require a new
outbox/reconciliation contract.

## Reproduce from a fresh checkout

Requirements: Git, Docker Engine with Compose v2, and Python 3.12.14/uv 0.12.19
for host test commands. Docker builds use pinned Python/Node/base-image digests;
`uv.lock` and `frontend/package-lock.json` are committed. Do not run default
`uv sync`: it selects historical model dependencies.

```bash
git clone --branch feat/commerce-eligibility https://github.com/richardcheam/decisionops.git
cd decisionops
python3 -B -S scripts/commerce_ci_tests.py dependency-free
uv sync --locked --only-group commerce --no-python-downloads
python3 -B scripts/commerce_local_setup.py
docker compose --profile app build
docker compose --profile app up -d --wait
curl --fail http://127.0.0.1:8080/health
docker compose exec -T postgres pg_isready -U commerce -d commerce
docker compose --profile app logs init
export COMMERCE_TEST_DATABASE_URL='postgresql+psycopg://commerce:local-demo-only@127.0.0.1:55432/commerce'
.venv/bin/python -B scripts/commerce_ci_tests.py postgres
.venv/bin/python -B scripts/commerce_execution_walkthrough.py
.venv/bin/python -B scripts/commerce_worker_walkthrough.py
docker build -f docker/Dockerfile.browser -t decisionops-commerce-browser:local .
.venv/bin/python -B scripts/commerce_browser_walkthrough.py
python3 -B scripts/commerce_backup_walkthrough.py
python3 -B scripts/commerce_release_walkthrough.py
docker compose --profile app down
```

Expected: dependency-free suite reports optional dependency/model/database skips;
PostgreSQL profile collects all six integration modules and fails on **any skip**;
six browser checks execute with zero skipped/flaky/failing checks. Init applies
migrations through `0005`, seeds once, sets up graph checkpoints. `/health` reports
ready. Docker `down` preserves the volume; `down -v` destroys its data and is not a
recovery command. Browser and release walkthroughs temporarily interrupt their
stack; do not run against a workspace someone is using. Walkthroughs retain local
ignored diagnostics and restore their stack/remove only owned test schemas.

For a parallel fresh environment, set `COMPOSE_PROJECT_NAME` to a unique name,
`COMMERCE_POSTGRES_PORT`, `COMMERCE_WEB_PORT`, `COMMERCE_WEB_URL`,
`COMMERCE_ORIGINS` and the host test database URL consistently. This gives a new
persistent volume and separate ports without touching the original store.

CI runs separate dependency-free, PostgreSQL and real Compose/browser jobs.
Optional historical model-package tests remain optional; no models are installed
by the commerce profile. Test summaries list individual skips. Credentials, `.env`,
dumps, logs, `runs/`, frontend builds and browser artifacts are excluded from Git.
`.env.example` contains no usable staff secret. Existing tracked historical
reports remain unchanged; local diagnostic artifacts stay on Richard's machine.

## What remains unfinished

Production TLS/identity, cloud IaC/deploy/teardown, encrypted off-host backup,
optional model adapters with durable budgets, independent held-out evaluation,
stock release/cancellation and real carrier/fulfilment integration remain future
milestones. The spending plan is proposed, not permission to spend. Regression
fixtures are AI-authored deterministic checks, not independent model evaluation.
Agent verification must not be described as Richard personally operating the app.

## Optional fake-provider review boundaries

`provider_service.prepare` is the insertion after the existing bundled assessment.
Recommendations route actual cases for exact staff review or escalation; they do
not choose individual tools or grant permission. Browser and worker default rules
are unchanged. Fake usage/prices are simulated. Migration 0005 adds the ledger.

Inspect [pure provider tests](../../tests/test_commerce_providers.py) and
[provider PostgreSQL tests](../../tests/test_commerce_provider_postgres.py) for
atomic count/cost races, uncertain retention/no redispatch, cross-process recovery,
no locks during provider waits, stale result rejection, later approval preservation,
request-ID bounds and business-before-call lock ordering. Existing execution tests
continue to verify exact review, transactional writes, duplicate prevention and
reconciliation. `scripts/commerce_provider_walkthrough.py` demonstrates the consumed
route and then requires a real exact review before creating one replacement.

Use RUNBOOK's isolated project/ports/image-tag setup before local branch tests.
The original running milestone remains revision 0004; this branch is revision 0005.
