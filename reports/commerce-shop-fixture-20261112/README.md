# Clothing storefront fixture: local evidence

Base d2f174e3753567c39027b0b7076e87598eabe29d preserved on the prior release branch.
Implementation commit 8d2f614 is on feat/commerce-shop-fixture; later commit adds only
this handoff/screenshots. [Launch guide and two-view demo](https://github.com/richardcheam/decisionops/blob/a816f6191af1b2ebda9863e1fa20ffdcf6416a14/docs/commerce/CLOTHING-STOREFRONT.md).
[Future browser contract/acceptance tests](https://github.com/richardcheam/decisionops/blob/a816f6191af1b2ebda9863e1fa20ffdcf6416a14/docs/commerce/BROWSER-INVESTIGATION-DESIGN.md).

Screenshots: [shop](shop-home.png), [product options](shop-product.png),
[order history](shop-orders.png), [order detail](shop-order.png),
[explicit loss](shop-tracking-lost.png), [incomplete tracking](shop-tracking-incomplete.png),
[staff record trace/review](staff-stale-record-evidence.png), [staff proposal](staff-proposal.png),
[mobile shop](shop-mobile.png). Local original SVG placeholders, no asset downloads.

## Actual local verification

| Check | Result |
|---|---|
| New customer/provenance/seed PostgreSQL tests | 9 passed, 0 skips |
| Existing staff backend/API rules/mock protections | 13 passed, 0 skips |
| Required legacy PostgreSQL profile | 194 passed, 0 skips |
| Scripted shopper + stale staff handoff | 3 passed, 0 skips (12.8s) |
| Existing staff browser approval/execution/history workflow | 2 passed, 0 skips (17.6s) |
| Final read-only shopper recheck after UTC/source-link fix | 2 selected passed, 0 skips (2.1s); third write-producing staff case deliberately not repeated |
| Mobile layout | 390px viewport, no horizontal overflow; timestamp has explicit UTC |
| Cached TypeScript/Vite and images | Passed, no dependency installation/download |
| Dependency-free profile | 200 passed, 274 explicit optional skips, 474 collected; 0 failures/errors |

The required 194 and 13 staff tests ran before the final narrow customer-link binding
correction. Its final 9 focused tests cover both valid links and suppression for a
mismatched shipment. Approval/execution/runner/evidence validation were not changed.
No broad legacy suite was repeated for that presentation-only correction.

[summary.json](summary.json) records 3 durable rules runs: one proposal (subsequently
approved/executed by Playwright staff clicks), stale-tracking review and missing-history
review. One operation/reservation/replacement exists. No model approval or Richard-
performed execution is claimed. Prior live model traces/stopped pilots/frozen inputs
remain unchanged. CI, real browser-agent evaluation, Site B and live-site automation
were not executed. All commands/screenshots/new verification here are agent-local.

Tests used only new decisionops-shop-fixture PostgreSQL (host 55526, DB/user shop_fixture,
server 5432), each backend test in a disposable schema. New public fixture seed was
prepared only there. The verification volume was retained/stopped after exports; a
separate fresh decisionops-shop-demo volume was started with zero cases/operations
for Richard. Existing original and release stacks were not restarted/migrated/reseeded.

## Commands and preserved raw artifacts

```bash
COMMERCE_TEST_DATABASE_URL='postgresql+psycopg://shop_fixture:fictional-shop-fixture-only@127.0.0.1:55526/shop_fixture' <historical-checkout>/.venv-decisions/bin/python -B -m unittest discover -s tests -p test_commerce_shop.py -v
# Same explicit URL/interpreter:
# unittest discover -s tests -p test_commerce_staff_investigation.py -v
# scripts/commerce_ci_tests.py postgres
python3 -B -S scripts/commerce_ci_tests.py dependency-free
```

Scripted browser command (shop configuration; staff suite substitutes staff-tests /
playwright.staff.config.ts and COMMERCE_STAFF_USERNAME=visitor, mode rules):

```bash
sg docker -c 'docker run --rm --pull never --network host -e COMMERCE_WEB_URL=http://127.0.0.1:8095 -e COMMERCE_STAFF_PASSWORD=fictional-shop-staff-test-only -v /home/richard/projects/decisionops/runs/worktrees/clothing-fixture/frontend/shop-tests:/workspace/shop-tests:ro -v /home/richard/projects/decisionops/runs/worktrees/clothing-fixture/frontend/playwright.shop.config.ts:/workspace/playwright.shop.config.ts:ro -v /home/richard/projects/decisionops/runs/worktrees/clothing-fixture/runs/shop-fixture/shop-browser:/workspace/artifacts --entrypoint sh decisionops-commerce-browser:local -c "npx --no-install playwright test --config playwright.shop.config.ts"'
```

That browser command includes a staff investigation and must not be repeated against
Richard's fresh demo casually. Test fixtures intentionally share this fictional store.
Raw logs/data remain runs/shop-fixture: api-final.log,review-red.log,review-green.log,
staff-backend.log,required-postgres.log,shop-browser-corrected.log,staff-browser.log,
final-shop-browser.log,mobile.log,dependency-free-final.log,final-build.log,
durable-records.json and fresh-demo-start/identity logs. Browser reports have traces
disabled; no secret/config/process environment dump was exported.

Retained failures:

- First DB setup reported connection refusal: Docker did not publish a port on its
  internal-only network. Added a PG-only local test-access bridge; guards/identity
  checks then executed. Early skips and setup failures are not counted as passes.
- First shopper browser 2 failed at order links: /demo-shop returned SPA HTML because
  the new route had no nginx proxy. Added a fixture-specific proxy/Dockerfile;
  preserved failed screenshots/logs. Original release proxy remains unchanged.
- Independent static review found a tracking link could point to the canonical shipment
  despite a mismatched request. Reproduced failing DB test, restricted links to the
  observed order+shipment binding, then 9 passed. Seed entry point wrong-DB refusal
  was also explicitly verified with mocked engine/seed and no writes.

Source display uses immutable observation ID/hash and DECLARED record scope, not a
new SQL audit log. A corresponding customer-page link is not a recorded browser visit.
Missing/discarded/conflicting observations remain not-current/unknown as before.

## Limits and next acceptance gate

This is one deliberately fictional functional fixture: browse-only catalog, fixed
preview customer, three diagnostic order IDs, no production customer auth or checkout.
Staff permissions and exact approvals stay in the existing console. Customer source
never queries or discloses inventory, compensation history/completeness or policy.
No old tracking event is silently promoted into loss or refreshes on startup.

Passing selectors/scripts proves navigability, not transferable navigation. The next
milestone must build a meaningfully different information/navigation structure for
Site B, freeze neutral inputs/admissible outcomes and validate a bounded read-only
browser tool contract before any separately authorized model run. Page claims cannot
replace authoritative Commerce evidence or authorize a proposal/execution. No quality,
generalisation, production, AWS or deployment claim follows from these tests.
