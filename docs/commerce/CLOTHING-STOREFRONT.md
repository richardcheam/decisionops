# THREAD / STUDY — first fictional browser fixture

Open **http://127.0.0.1:8095/shop**. This is a local browse-only clothing shop, alongside
[the staff console](http://127.0.0.1:8095/). Products use original local SVG illustrations.
There is no checkout/payment service, real customer account or live carrier connection.
The fictional customer preview needs no credentials; staff login is `visitor` /
`fictional-shop-demo-only` (deliberately public LOCAL fixture credentials, not an invitation
for a deployed service). Nothing has been published or provisioned.

The accepted d2f174e release stays preserved on feat/commerce-staff-investigation.
New work is on feat/commerce-shop-fixture in runs/worktrees/clothing-fixture. Original,
55521 staff, 8091 portfolio and 8093/8094 release rehearsals are not upgraded by this fixture.

## A short demo in both views

1. On /shop browse the four garments. Open Everyday cotton shirt; change colour/size.
   These are local accessible controls, not a cart or stock promise.
2. Click **My account** → **View order ORD-1042** → **Track shipment**. The line shows the
   exact blue/M variant and quantity; the tracking page binds SHIP-1042 to that order
   and shows the carrier's explicit lost status and actual record timestamp (UTC).
3. Go back to Order history and choose ORD-TRACKING. Its linked tracking page shows
   an in-transit update recorded three days before fixture preparation. There is no
   current authoritative loss confirmation; never infer loss from delay alone.
4. Open Staff console in another tab and sign in. Select ORD-1042 → Start review.
   That existing action uses the bundled check. Enter a shipment report and choose
   **Investigate shipment** for the explicit-read rules workflow. Inspect the evidence.
   Open **Evidence source**: declared record tables, exact request/order/shipment,
   observation ID/version and a matching customer-page link where applicable. It
   explicitly says database records were read, not that a browser agent visited pages.
5. If all conditions hold, inspect the proposal. **Approve replacement → Confirm
   approval**, then **Create replacement → Confirm replacement** are separate staff
   actions. The existing deterministic services recheck/lock/commit/reconcile exactly
   one fictional replacement. No shopper control or model can approve or execute.
6. Investigate ORD-TRACKING for a missing/current-tracking review. Alternatively try
   ORD-HISTORY: its customer carrier page reports loss, but staff-only compensation
   history is incomplete. No eligible proposal can be made from the customer page
   alone. Internal inventory, history completeness and replacement policy never appear
   in the customer projection.

The fresh demo was left with zero cases/operations. After you execute once, that order
is compensated and a second replacement must be blocked. Original shipment tracking
still describes the lost original parcel; creating a replacement does not rewrite it.
Carrier timestamps age naturally: after 24h even the initially lost event can become
stale under demo policy. Startup does not refresh timestamps, reset approvals or erase
history. Ask for an operator-owned fresh fixture when appropriate; do not bypass policy.

## Launch, inspect and stop (cached dependencies only)

Use the new standalone file/project, never apply it to any existing project/volume:

```bash
cd /home/richard/projects/decisionops/runs/worktrees/clothing-fixture
export COMMERCE_SHOP_PASSWORD=fictional-shop-demo-only
sg docker -c 'docker compose --env-file /dev/null -f compose.shop-fixture.yaml -p decisionops-shop-demo build --pull=false'
sg docker -c 'docker compose --env-file /dev/null -f compose.shop-fixture.yaml -p decisionops-shop-demo up -d --wait --wait-timeout 90 --no-build --pull never'
curl --fail http://127.0.0.1:8095/health
sg docker -c 'docker compose --env-file /dev/null -f compose.shop-fixture.yaml -p decisionops-shop-demo ps --all'
sg docker -c 'docker compose --env-file /dev/null -f compose.shop-fixture.yaml -p decisionops-shop-demo logs --tail 30 init api staff-investigator worker web'
# Stops only this fixture; retains all data/evidence:
sg docker -c 'docker compose --env-file /dev/null -f compose.shop-fixture.yaml -p decisionops-shop-demo stop'
```

Expected: init exits 0 after schema 0008, guarded seed and checkpoint setup; API/web/PG
healthy, workers running. On SSH, forward localhost 8095 for both views. PostgreSQL
is bound to localhost 55526 ONLY for local integration checks; it is not a hosting
configuration. Database/user shop_fixture, volume decisionops-shop-demo_shop_pgdata.
No private .env is read. Missing staff password fails closed. No OpenAI key/model
configuration is passed. Existing locked app/browser images and nginx/PostgreSQL
must already be cached; builds use network:none, no pip/npm install or upgrades.
A fresh-machine bootstrap/download was not performed. No new migration was added.

COMMERCE_STOREFRONT_FIXTURE=1 is set only in this file's API. Customer reads also require
exact shop_fixture DB/user identity and demo-store; an explicit allowlist exposes
only three fictional orders. History/detail/tracking have separate column projections.
The flag defaults off elsewhere; customer writes return 405 and staff endpoints still
require authentication. The one-time shop seed refuses other DB/user identities
BEFORE seeding, and never refreshes an already prepared fixture. No API reset exists.

The stopped verification project decisionops-shop-fixture retains a DIFFERENT volume,
plus exported durable JSON under runs/shop-fixture. It was used for automated tests;
do not start it while the fresh demo owns 8095/55526. Never use down -v for routine
shutdown. Preserve exports/source identity before any future explicit fixture deletion.
The original runtime/volume and accepted release artifacts are outside reset scope.

## Evidence and what it means

[Actual checks, screenshots and recorded failures](../../reports/commerce-shop-fixture-20261112/README.md).
The tests use site-specific Playwright selectors and scripted links: they prove the
shop is navigable, not autonomous investigation or transfer. Rules staff investigations
are real current record reads; mock API checks are explicitly simulated. The preserved
real Decisions trace remains historical and ended in review; it was not replayed as
browser activity or rerun. All new commands, automated staff approvals/replacements
and screenshots were agent-executed; Richard has not reported running this new fixture.

[Proposed browser-tool interface and two-site acceptance matrix](BROWSER-INVESTIGATION-DESIGN.md)
are for next-milestone review only. Site B and live/model-driven browser-agent evaluation
remain unimplemented. Diagnostic IDs such as ORD-TRACKING are not a neutral frozen
model benchmark; the design requires neutral task data before such evaluation.
