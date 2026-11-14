# Richard's first live Decisions investigation

Richard reported running the prepared SSH-terminal commands. Retained native records
corroborate exactly one investigation and one budget, using the approved configuration:
`b318cc81100b474bf1cad6815bd9ed8f39a064db9f1cdf55debff8eb2a54da09`.
The agent subsequently inspected files, reconciled hashes/accounting and checked that
the dedicated container was absent. The agent did not make these paid calls or rerun
the investigation. This is **real Decisions integration evidence**, and a **negative
proposal-completion result**: the model stopped early in a safe review outcome.

Run `ARUN-aa325a0713a14702bfb3295cc52c18d8`; case
`CASE-5b1cd9cc37cc416daaad456f653974b3`; one shirt-blue-M for ORD-1042/SHIP-1042.
Model gpt-6-luna, POST /v1/decisions, simulation=false.

## Actual choices and usage

Each request asked the one named `investigation_action` choice question. Choice
values were local to that request's allowed-action list, not globally named tools.

| Step | Value | Selected action | Returned evidence/outcome | Native input tokens | Cost estimate USD | SDK elapsed |
|---|---|---|---|---:|---:|---:|
| 1 | c000 | order_manifest | Exact requested variant/quantity valid | 361 | 0.00003610 | 4.667 s |
| 2 | c000 | replacement_policy | Applicable bound policy permits replacement | 496 | 0.00004960 | 0.319 s |
| 3 | c001 | fulfilment | Relevant item shipped | 509 | 0.00005090 | 2.218 s |
| 4 | c000 | payment | Payment established | 546 | 0.00005460 | 0.421 s |
| 5 | c000 | carrier_loss | Correct shipment explicitly lost | 559 | 0.00005590 | 0.312 s |
| 6 | c000 | compensation_history | Complete history establishes no previous compensation | 572 | 0.00005720 | 0.310 s |
| 7 | c001 | request_review: unknown_evidence | Terminal needs_review; stock unknown | 585 | 0.00005850 | 0.473 s |

Every native usage record reports **zero output tokens and zero reasoning tokens**;
cache-read/write tokens are also zero. Totals: **3,628 input, 0 output, 0 reasoning**.
Input-only estimate at the approved standard-global $0.10/million rate:
**$0.00036280**. This is a usage-based estimate, not independently checked invoice data.

Each call first reserved $0.00245760. Seven historical reservations sum to
$0.01720320, all settled to known usage; there are no uncertain/outstanding
reservations. Retained reservation fields are audit history, not an additional fee.
Seven requests of the permitted twelve were used. All seven actions were inferred:
no forced decisions, fallback, retry, rejection or API refusal.

Run start: 2026-10-16 11:37:06.691970 UTC. Terminal step:
11:37:19.458412 UTC. Full durable-run wall time: **12.766442 seconds**.
Recorded SDK elapsed sums to **8.720 seconds**. These measurements include SDK/client
and orchestration effects; they are not isolated server inference benchmarks. No
memory measurement or model-quality benchmark is claimed.

## Why there is no proposal

The final evidence-only assessment is:

- paid, shipped, loss_confirmed, quantities_valid, no_previous_compensation and
  policy_permits: established true;
- stock_available: unknown, because inventory was never selected;
- scope supported/complete; no established blocker.

The seventh request still allowed `read inventory` as c000. It also allowed review,
which the model selected as c001. Its native distribution assigned inventory 0.37,
unknown-evidence review 0.54, manual review 0.06 and policy-refused review 0.03.
Native confidence was 0.39, a separate uncalibrated model estimate. These scores did
not authorize business action and do not explain the model's internal reasoning.

The model stopped voluntarily with six of seven required reads completed. No money,
request, tool or time limit forced this stop. Review is currently a permitted terminal
action even while another read is available. The system therefore accepted the valid
review choice, disclosed the missing inventory condition, and refused to fabricate
eligibility. It did not silently switch to rules to finish the remaining read.
CLI exit zero means an orderly terminal result, not a successful business proposal.

The database export includes seed records, but unselected records must not be used
to retroactively claim this investigation collected inventory evidence. Missing stock
evidence is not insufficient stock: it is unknown. No proposal, human approval,
operation, stock reservation, replacement order or replacement line was created.

## Follow the code path

1. `api_investigation.py` verifies the isolated database identity and exact approved
   configuration. The single-use terminal wrapper prevents accidental rerun and reads
   credentials only from Richard's external shell environment.
2. `adaptive_accounting.prepare` snapshots the bounded policy features and durable
   context. `api_accounting.reserve` locks the budget and reserves request/input cost
   atomically before dispatch. Immutable request/configuration hashes remain bound.
3. `openai_decisions.wire_request` maps the current allowed actions to c000/c001/etc.,
   includes only permitted features and fixed instructions, and caps complete request
   bytes. `DecisionsAdapter` uses the official SDK's Decisions resource. Shared
   transport disables retries, caps response bytes and respects the deadline.
4. The adapter verifies the one question's name, answer type, exact model, selected
   value, native usage and finite probability distribution. The runner records and
   settles known usage, then applies only a current/fenced, deterministically allowed
   action. Confidence never becomes evidence or approval.
5. Each selected `adaptive_tools.read_tool` executes its declared projected queries
   in a short read-only transaction and persists the returned observation. Dependencies
   are explicit: carrier_loss became available after manifest, policy and fulfilment.
   Fulfilment itself did not read carrier status; that occurred in step 5.
6. The final review choice goes through `adaptive_investigations.advance/finish`.
   The system records needs_review and stock_available unknown, completing the job.
   It did not exercise proposal safety revalidation, staff approval, deterministic
   execution or reconciliation business paths in this live run. Prior regression
   checks cover those paths separately; this run cannot claim to demonstrate them.

## Inspect without paid calls or database access

Original files were archived unchanged; [the evidence index](../../reports/commerce-evidence/INDEX.md)
maps their original `runs/decisions-manual-evidence/` location. The completed export includes
`live/trace.json`, `durable-records.json`, `fictional-database.sql`, logs, the exact
used config and `sha256-inventory.json`. All inventory hashes matched on review.
The dedicated `decisionops-decisions-live` container is absent. No database restore
is needed to inspect the files; the original application/volume remain untouched.

```bash
cd <historical-checkout>
export DECISIONOPS_EVIDENCE_ROOT=/home/richard/projects/decisionops-archive/2026-10-16-wrapup/worktrees/stage5-correction
python3 -m json.tool "$DECISIONOPS_EVIDENCE_ROOT/runs/decisions-manual-evidence/live/trace.json"
PYTHONPATH="$PWD" .venv-decisions/bin/python scripts/commerce_reconcile_decisions.py
python3 -m json.tool runs/evidence-review/decisions-summary.json
```

The reconciliation script reads only retained files. It verifies configuration and
file hashes, both immutable request-hash contracts, base request fields, case/deadline
bindings, local choice-to-action mapping, dispatch counts and exact Decimal arithmetic.
It writes a separate derived summary to ignored runs/evidence-review/; archived
original evidence and inventory remain unchanged.
No API calls, database queries, tests, model runs or access probes are involved.

The raw trace's per-call request.features shows precisely what was visible at each
choice; result.metadata contains native scores/usage. Monetary companion rows contain
input-only prices/reservations/settlements. The duration ledger's zero USD fields
must not be mistaken for the live API monetary companion's actual usage estimate.

## Learning note and pause

The application successfully used the real Decisions endpoint and enforced its safety
boundary, but the model did not complete the eligible-fixture investigation. There is
no basis to call it a successful proposal, or infer efficiency/business value from its
speed or cost. Nor is this one run comparable to the historical nano run as a controlled
model benchmark. Preserve both negative outcomes.

No patch, second investigation, automatic retry, replacement budget or policy change
was made in response. The attempt is terminal. Keep the single-use marker and durable
records; do not resume it. Any further live investigation needs another explicit
RUN LIVE TEST. Pause for Richard's walkthrough before more development.
