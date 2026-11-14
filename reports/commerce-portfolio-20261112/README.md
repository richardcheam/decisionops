# Fictional portfolio: local deployment verification

Accepted baseline: f8ce67917ad7c2dc8a137877a6659c4a04857fd0 on
feat/commerce-staff-investigation. Product/domain/approval/provider code is unchanged
from that accepted snapshot. Additions are standalone packaging, a stdlib verification
harness, configurable browser-test login/timing and static labelled portfolio evidence.
The original Compose file, runtime and volumes were not modified.

[Single launch/stop path and portfolio walkthrough](https://github.com/richardcheam/decisionops/blob/e311fe0e02a0386e86d400fb417147155847da02/docs/commerce/PORTFOLIO-DEMO.md).
[Actual restart/browser summary](summary.json).
Screenshots: [progress](progress.png), [proposal](proposal.png),
[incomplete](incomplete.png), [portfolio page](walkthrough.png).

## Agent-executed checks

| Check | Actual evidence/result |
|---|---|
| Clean source build | Detached portfolio-verify checkout; Compose build --pull=false, network-disabled RUN steps, existing locked caches; TypeScript/Vite and image builds passed |
| Normalized Compose | Six services, separate volume/network namespace, backend internal, web-only ingress bridge, loopback 8091 only, no PG/API host ports, rules mode, no API-key environment |
| First startup/migration/seed | Dedicated decisionops-portfolio-verify volume; schema 0008, seed and existing checkpoint setup succeeded; API/web/PG health passed |
| Rules browser with worker restart | 2 passed, 0 skipped;48.628s full harness wall time. Eligible UI reload/idempotence/proposal/exact staff approval/separate execution; incomplete history review/no proposal or replacement |
| Restart boundary | Stop after first committed read, start staff investigator, wait real lease expiry. 2 claims,7 reads, one proposal, one verified operation/reservation/replacement; all dispatch_count≤1; original deadline and immutable step/observation history preserved |
| Whole-stack stop/restart | Scoped stop made 8091 unavailable; up --wait succeeded; all 11 exported durable table arrays exactly equal before/after idle restart |
| Static walkthrough browser | Cached Chromium rendered page/screenshot and checked live JSON is real historical review, execution_authorized=false |
| Served static bytes | HTML, CSS, manifest and exact live trace matched source over HTTP |
| Evidence tests | 3 passed,0 skips: immutable live trace SHA/outcome, every manifest hash and static local resources/no scripts |
| Dependency-free profile | 462 collected, 197 passed, 265 explicitly reported optional skips, 0 failures/errors |

All executions above are **agent local**, including fictional approval/replacement
clicks. No new Richard execution, supervisor runtime verification, public CI, paid
call, model load, download or cloud provisioning is claimed. A scoped independent
source review found no blocking packaging issue and identified cache-bootstrap limits;
it did not independently run/verify the browser or database outcomes.

Reuse rather than repeat: f8ce679's 194 required PostgreSQL, 13 focused staff API/engine,
4 launcher passes, earlier 2 mocked Decisions browser passes, legacy 6 browser / 8 API
and 28 SDK/database passes. Their core tested source/locks is unchanged. New actual
PostgreSQL execution is the Compose/browser/restart/persistence check above; the full
194-test profile was not rerun merely for packaging. No optional real model/browser
CI job was silently counted as executed. Historical viewer/source is unchanged and
not rerun in this portfolio slice.

## Exact verification commands and source identities

Executed from a clean detached checkout (runs/worktrees/portfolio-verify):

```bash
sg docker -c 'docker compose --env-file /dev/null -f compose.portfolio.yaml -p decisionops-portfolio-verify build --pull=false'
sg docker -c 'docker compose --env-file /dev/null -f compose.portfolio.yaml -p decisionops-portfolio-verify up -d --no-build --pull never'
python3 -B scripts/commerce_portfolio_verify.py
```

The harness uses only the fixed verification project, cached Playwright/Chromium,
visitor fixture login and a freshly seeded empty case history. It saves before,
stopped and after records and executes real browser assertions, not skips. Its first
SQL-only attempt failed due to two mistaken export table names; corrected to the
actual existing schema and retained the failure. No application behavior changed.
Do not repeat it against compensated fixtures or delete its evidence to retry.

- Browser/restart source: 820661c330b2ddd5935bba97056adb96e972c38e.
- Standalone ingress correction: 69cbbc6; initial clean build source: 5b5c64a.
- Final static walkthrough build/source:6329b88 (only static files changed after browser proof).
- Final documentation/evidence-test commit follows those; no business code changed.
- Baseline review bundle retained SHA256
  9192184511edb1c25f145d16dae1be3908b226e7fe868e636514257cc3ad80e7.

Executed from the task worktree after copying evidence:

```bash
python3 -B -S -m unittest discover -s tests -p test_commerce_portfolio_evidence.py -v
python3 -B -S scripts/commerce_ci_tests.py dependency-free
sg docker -c 'docker compose --env-file /dev/null -f compose.portfolio.yaml -p decisionops-portfolio-verify stop'
sg docker -c 'docker compose --env-file /dev/null -f compose.portfolio.yaml -p decisionops-portfolio-verify up -d --wait --wait-timeout 90 --no-build --pull never'
```

Full logs/durable JSON, original failure output, image identities and resource sample
are retained locally at runs/portfolio-demo. Clean-checkout records are under
clean-checkout-artifacts/restart-{before,stopped,after}.json; browser.log records both
executed cases. Those raw records retain request/context/lease bindings and settled
results; ownership tokens are audit metadata, not model features. No credentials or
process environment exports were collected.

## Known startup failures and corrections

1. Docker 29 did not publish the host port on an exclusively internal network, despite
healthy internal services. Preserved first startup output; added an ingress bridge
**only to web**. Backend remained internal and host 8091 became reachable.
2. Plain up -d can return before newly started nginx accepts connections. Immediate
curl returned reset; it subsequently passed. Documented/tested --wait startup instead
of interpreting a transient readiness race as healthy or weakening the healthcheck.
3. First verification SQL referenced nonexistent stock_reservations/replacement_orders;
corrected the harness to commerce_reservations/commerce_replacement_orders. The error
preceded browser/admission; no hidden investigation or reset occurred.

These are packaging/test setup issues, not native-model failures. The prior stopped
cached-pilot failure and both historical API review results remain unchanged.

## Artifact/dependency/resource limits

Image platform: amd64. Existing runtime package pins matched the unchanged lockfile.
No empty-cache bootstrap or dependency installation was tested. Future hosting should
load the already-built runtime artifacts and use --no-build --pull never; builder
caches are not runtime requirements. Mutable tags alone are insufficient identities:

| Artifact | Recorded Docker image ID |
|---|---|
| Cached commerce runtime | e03ffc3b1faa0b71af34b761eb941570f5fb0f9176f7e8514f2b2efe1b080ffb |
| Cached browser/dependencies | e3b1f9080cea2ce68e2b83dc4f981303dbb688763a306b71c940dea617f6898b |
| Portfolio app | 4a1993d0593ecf23ea083a84cdf6d77cf868655e1b7a749979bf08ab5b14ecfa |
| Portfolio web (including static evidence) | 707b3e92d8b1b1cb5326418c8971ba5eba14c4dc785229bdce15f7db91857a7e |

Steady-state single sample: API 64.82MiB,ordinary worker 80.89MiB,staff investigator 40MiB,
PostgreSQL 63.23MiB,web 11.87MiB (~261MiB total). This excludes host/build/browser memory
and is not a peak/load measurement. Runtime service caps total 1,472MiB; init has a
separate 384MiB cap. Hosting sizing/cost/access/reset plan is in PORTFOLIO-DEMO.md.

Remaining unexercised paths: abrupt kill during a dispatched decision/read, public
TLS/DNS/firewall, host image transfer, fresh-host bootstrap, concurrent anonymous
traffic and destructive operator reset. Existing explicit uncertain-call recovery
rules remain; graceful between-step restart proof does not establish those paths.
There is no automatic visitor reset or per-visitor store. Native Stage5 and public
deployment are not declared complete. Real shop connection is deliberately deferred.
