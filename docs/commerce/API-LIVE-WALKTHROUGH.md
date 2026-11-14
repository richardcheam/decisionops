# First manual nano investigation: safe early review

Richard reported running the prepared SSH terminal scripts. Their saved records show
one real investigation, three Responses requests and two business reads. The agent
subsequently inspected files and the absence of the disposable container; it did not
make these paid calls. This is an integration result and a **negative proposal task
completion result**, not proof of model quality or business value.

Run: `ARUN-f370f8f306cc43e4920f246bbda63188`; fictional request ORD-1042,
SHIP-1042, one shirt-blue-M. Configuration SHA-256:
`8349e81fc3b0805567aa71e5d3f540ac038623e6efec3735a052c9276a244a83`.
The saved budget/model/endpoint match the authorization. simulation=false.

## What happened

| Decision | Selected action | Observed result | Input/output tokens | Usage-based USD | SDK elapsed |
|---|---|---|---|---|---|
| 1 | read order_manifest | Requested variant/quantity valid | 247 / 138 | 0.00006755 | 6.317 s |
| 2 | read fulfilment | Requested item was shipped | 330 / 425 | 0.00018650 | 3.995 s |
| 3 | request_review: unknown_evidence | Terminal needs_review | 357 / 368 | 0.00016505 | 4.048 s |

Totals: 934 input tokens, 931 output tokens, 1,865 tokens; $0.00041910 recorded
usage-based estimate at $0.05/M input and $0.40/M output. This is not an independently
verified invoice. Each call first reserved $0.00225280; three historical reservations
sum to $0.00675840. All settled; no uncertain/unresolved reservation remains. Original
reservation fields remain in history, so do not add them to settled costs. No tokens
were fabricated; output usage includes any reasoning counted by the API, and the
trace does not record a finer reasoning-token breakdown.

Run start 08:55:07.627324 UTC; terminal 08:55:23.052896 UTC (15.425572 seconds).
SDK elapsed totals 14.360 seconds; remainder includes orchestration/database overhead.
All three choices were inferred, no forced choice, fallback, retry or rejection.

The model saw only the bounded report, selected observation summaries, requested
variant/quantity, previous attempts, allowed actions and remaining budgets. It did
not see complete store records or precomputed eligibility. After fulfilment, policy,
payment, compensation and inventory reads were still allowed. carrier_loss required
a policy observation first. The model chose review rather than continuing. We know
its selected action; we do not have evidence establishing its internal rationale.
It did not exhaust money, tool, decision or time budgets.

Unknown requirements: paid, loss_confirmed, no_previous_compensation, stock_available,
policy_permits. Compensation scope remained unresolved. No established blocker was
reported. The deterministic system preserved these unknowns and returned needs_review
rather than inventing evidence or constructing a proposal. No proposal, staff approval,
operation, stock reservation or replacement was created. CLI exit 0 means an orderly
terminal result; it does not mean the business task succeeded.

## How the components fit

1. api_investigation.py is the explicit operator entry point. It verifies isolated
   database identity and configuration approval, creates the budget/job, then runs
   the adaptive coordinator. Ordinary application defaults remain rules-only.
2. adaptive_accounting.py and api_accounting.py persist the bounded recommendation
   and monetary reservation before dispatch. Rows are task/configuration bound.
3. api_decisions.py builds strict structured allowed-index output and invokes the
   SDK outside database transactions, with SDK/transport retries disabled. A valid
   response maps to one existing Action, never direct SQL or an execution command.
4. adaptive_runner.py admits the recorded response through ownership/context checks.
   adaptive_investigations.py validates the action; adaptive_tools.py executes only
   the selected read with explicit dependencies and persists evidence.
5. order_manifest projects order identity/store/policy/currency and line variant/
   quantity/price. fulfilment projects shipment identity/order/fulfilment status and
   shipment lines. It does not retrieve carrier status. These are declared query
   groups from source, not a separately captured live SQL profiler trace.
6. The third valid recommendation selected terminal review; the final deterministic
   assessment disclosed the five unknowns and unresolved scope. Approval/execution
   paths and the proposal safety bridge were not exercised by this live run.

## Inspect this result without another paid call

The disposable database has been removed. Original evidence was archived unchanged;
[the evidence index](../../reports/commerce-evidence/INDEX.md) maps its former
`runs/api-verification/manual-nano-evidence/` location. The full JSON export and SQL snapshot
preserve its records; no restore or rerun is needed to read them.

```bash
cd <historical-checkout>
export DECISIONOPS_EVIDENCE_ROOT=/home/richard/projects/decisionops-archive/2026-10-16-wrapup/worktrees/stage5-correction
python3 -m json.tool "$DECISIONOPS_EVIDENCE_ROOT/runs/api-verification/manual-nano-evidence/live/trace.json"
PYTHONPATH="$PWD" .venv-decisions/bin/python scripts/commerce_reconcile_nano.py
python3 -m json.tool runs/evidence-review/nano-summary.json
```

The last command is offline: it validates the original file inventory, configuration
hash, both request-hash contracts, case/deadline bindings, recorded usage arithmetic
and absence of business actions. It writes only a derived local review summary under ignored runs/evidence-review/.
The initial audit assumed monetary/adaptive request documents identical; inspection
showed the adaptive document adds domain bindings. The final audit verifies shared
base fields plus both hashes and explicit case/deadline bindings. No product patch
was needed.

No new API requests, database operations, models, CI/browser tests or unrelated suites
were run during this evidence review. Prior mock/database regression evidence remains
separate. No publication/deployment or original-runtime changes. The completed run
is terminal; do not resume it, delete its admission marker or create a replacement
budget. Any further live investigation requires another explicit RUN LIVE TEST.

## Learning note

The API model selected the next action; it did not establish business facts. The
read tools established two conditions. Deterministic validation kept the remaining
conditions unknown and prevented a proposal. This demonstrates the permission/evidence
boundary and accounting integration, while retaining the model's early-stop failure.
No prompt/configuration patch or second test has been authorized. Pause for Richard's
walkthrough before choosing any further development.
