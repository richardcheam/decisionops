# Run and present the DecisionOps demo

Start with the [README quickstart](../README.md#run-the-demo). It starts the fictional
shop with simulated specialist choices and zero model calls. Use separate browser
profiles for customer and staff. On Docker, sign in as `camille` for Lyon and
`visitor` for staff approval. The optional `staff` account can investigate.
For a real local model, follow the [Ollama guide](LOCAL_MODEL.md).

## Present it in five minutes

Follow the [Lyon walkthrough](../README.md#walk-through-lyon). Tell the audience
what to look for at each step.

| Step | What to show |
|---|---|
| Report | Camille opens **DEMO-LYON** under **Your orders**, chooses **Report a missing parcel**, and sends the message. The case reference ties the report to that parcel. |
| Investigate | Staff open the matching case in the **Exception queue**. Show **Case history** and **Carrier updates**, then choose **Investigate case** and look at both branches under **Investigation**. |
| Approve | Show the exact item and quantity. **Approve replacement** opens a dialog with the proposal ID, generation and content hash under **Approval binding**. Choose **Confirm approval**. |
| Create | Choose **Create replacement**, then **Confirm replacement**. **Replacement confirmed** means the record was created and the item set aside. |
| Follow up | Read the update in Camille’s **Your case updates**. Reload and sign back in as Camille if prompted. The original conversation shows the confirmed result. |

For Lille, open **DEMO-OVERDUE** and show that the parcel is still in transit.
For Saint-Denis, open **DEMO-CONFLICT** and show the conflicting carrier records
under **Carrier updates**. Both cases illustrate why staff should wait for better
evidence before promising a replacement.

Other questions to try include “What did I order?” in customer chat and “Which
parcels are late?” or “What’s still missing?” in staff chat. The assistant can
explain how to get help with returns, refunds and order changes.

## Repeat the demo

`bash scripts/demo.sh stop` stops the app. A restart preserves cases and previous
results. On a database that has already been seeded, start-up uses the existing
fixtures. See the [maintainer index](ARCHIVE.md) for resetting the fictional demo,
deployment and recovery procedures.

## Run the browser smoke test

With the locked Commerce Python profile, frontend dependencies, Node 24 and a
disposable PostgreSQL database, run from the checkout:

```bash
uv sync --locked --only-group commerce
npm --prefix frontend ci
export COMMERCE_TEST_DATABASE_URL='postgresql+psycopg://USER@127.0.0.1:PORT/commerce_delivery_test'
.venv/bin/python -B scripts/commerce_customer_browser.py --compact
```

Set `COMMERCE_BROWSER_PATH` to a local Chromium or Brave executable if the
Playwright browser has not been installed. The runner migrates an isolated schema,
seeds all three cases, starts the app and workers, and drives both browser sessions.
It checks in PostgreSQL for one Lyon replacement and one stock reservation, then
removes its own schemas. The [deployment guide](PORTFOLIO_DEPLOYMENT.md) covers the
container version of the checks.

## Authorize a return

Use the same quickstart and sign in as Camille and the staff approver in
separate browser profiles.

1. Open **DEMO-RETURN** in Camille’s orders and choose **Check return eligibility**.
   Select **return-tote** under **Return item**, then choose **Start return**.
   Keep the case reference. The other item is final sale.
2. In the staff workspace, open the matching case under **Return cases** and
   choose **Investigate return**. Show the delivery and policy checks. Choose
   **Approve return**, then **Confirm return approval**. Next choose
   **Authorize return**, then **Confirm return authorization**.
3. Return to Camille's original conversation and find the authorization in
   **Your case updates**. The recorded result authorizes one return. It makes
   no refund and reserves no stock.

For an ineligible case, check the tote in **DEMO-RETURN-EXPIRED**. Its delivery
falls outside the 30-day window. For clarification, ask about **DEMO-RETURN**
before choosing an item. The customer sees the choices and the app waits for
an exact selection and an explicit request.

## Verify a catalog image

In the staff workspace, open **Catalog** and choose **TOTE-BLUE**. Select
**Investigate image** to see the current red tote and the proposed blue image
alongside the verified SKU records. Choose **Approve image change** and
**Confirm approval**, then choose **Relink image** and **Confirm relink**.
The saved result identifies `tote-blue`.

Use **TOTE-SLATE** to show that an ambiguous-looking image can already be
correct. Open **MUG-WHITE** to show a supplier disagreement. Staff see the dispute
and the listing keeps its current image.

The check runs as part of the same app. See the
[catalog benchmark](CATALOG_BENCHMARK.md) for the comparison.

## Shopify development-store returns

Once the [hosted pilot](PORTFOLIO_DEPLOYMENT.md#hosted-shopify-development-pilot)
is configured, open its `/pilot` URL. As approver, connect the designated
Shopify development shop, resync its fictional delivered orders, and create a
support-agent invitation. Share the one-time link privately.

In a separate support-agent session, accept the invitation, open a case for an
exact fulfillment line, and submit its return proposal. Back in the approver
session, approve that proposal and separately confirm creation. A verified
state includes the Shopify return reference. Match it to the order and return
in Shopify Admin. If the write outcome is uncertain, use **Check Shopify for a
saved return**. That action reads Shopify and does not issue another creation.
