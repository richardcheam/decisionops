# DecisionOps

A customer tells an online shop their parcel never arrived. DecisionOps helps staff
check the carrier’s records, see whether the customer already received a refund or
replacement, and find out whether the item is in stock.
When the records support a replacement, an authorized staff member approves it
and separately confirms creation.

## Agents and tools

| Role | What it handles |
|---|---|
| Customer chat router | Own order, tracking and missing-parcel reports |
| Staff chat router | Delivery questions, case status and investigation |
| Order specialist | `payment`, `compensation_history` |
| Shipment specialist | `fulfilment`, `carrier_loss` |
| LangGraph coordinator | `order_manifest`, `replacement_policy`, `inventory` |

The two chat routers select supported actions, such as checking tracking or starting
an investigation. In LLM mode, the specialists choose which of their allowed reads
to run. One Ollama model can serve both routers and both specialists. The coordinator
follows application logic. There are **seven available investigation read tools**.
Chat intents route messages, tool reads check records, and model calls select actions.
Staff approval and confirmation are separate actions in the app.
[Architecture and code map](docs/ARCHITECTURE.md)

## Run the demo

This quickstart uses a fictional shop, simulated carrier data and specialist
choices, and **zero model calls**. Use Docker with Compose v2.24.4 or later.
Run these commands from the checkout with the fictional credentials below.

The first start creates the three demo cases in PostgreSQL. If you ran the demo
before, it keeps the cases and results already in that database.

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

### Walk through Lyon

1. Open [Customer help](http://127.0.0.1:8133/customer) and sign in as `camille`.
   Under **Your orders**, open **DEMO-LYON**, choose **Report a missing parcel**,
   then **Send message**. Keep the case reference.
2. In a separate browser profile, open the [staff workspace](http://127.0.0.1:8133/staff)
   and sign in as `visitor`. Open **DEMO-LYON** in the **Exception queue** and
   match the case reference.
3. Choose **Investigate case**. Watch the order and shipment specialists check
   the records. You can ask “What’s still missing?” while the case is open.
4. Review the proposal for one demo tote. Choose **Approve replacement → Confirm approval**.
   Then choose **Create replacement → Confirm replacement** to set aside one item.
5. Look for **Replacement confirmed** in the staff workspace and the result under
   **Your case updates** in Camille’s original conversation. The replacement was
   created and stock was reserved. Shipping is a separate step.

The fresh demo has two other cases.

- **Lille** (`DEMO-OVERDUE`) is late and still in transit.
- **Saint-Denis** (`DEMO-CONFLICT`) has conflicting carrier records and needs review.

## Where to start next

| If you want to… | Open |
|---|---|
| Present the three cases or repeat the demo | [Demo guide](docs/PORTFOLIO_DEMO.md) |
| Follow the workflow and find the code | [Architecture](docs/ARCHITECTURE.md) |
| Run and check a real local model | [Local Ollama setup](docs/LOCAL_MODEL.md) |
| See how rules and Ollama performed | [Local model benchmark](docs/LOCAL_BENCHMARK.md) |
| See the catalog image results | [Catalog benchmark](docs/CATALOG_BENCHMARK.md) |

The demo’s browser tests check the replacement record and stock reservation in
PostgreSQL. The [demo guide](docs/PORTFOLIO_DEMO.md#run-the-browser-smoke-test)
shows how to run those tests.

The customer can also ask what they ordered or how to get help with returns,
refunds and address changes. Shop staff handle those requests.
