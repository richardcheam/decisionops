# Two fictional shops: model-free gate and proposed API evaluation

Historical preparation record: the current offline release candidate and forced-function
protocol are documented in [PORTFOLIO-RC.md](PORTFOLIO-RC.md). The old v1 live command
below is superseded; its original configuration/evidence remain historical.

Worktree `runs/worktrees/browser-investigation`, branch `feat/browser-investigation`,
starts from frozen Site A `b85a23e620e5e3428e4954da58cf22eb4735ebed`.
The frozen Shop component/styles and Commerce implementation/locks are unchanged.
A separate evaluation entry point reuses that component with neutral fictional
records. The original shop at 8095 and rehearsed release at d2f174e are preserved.

## Start, inspect and stop

From this worktree, with Docker access already configured:

```bash
bash scripts/browser_fixture.sh build
bash scripts/browser_fixture.sh start
bash scripts/browser_fixture.sh check
```

The build uses **already cached** `decisionops-commerce-browser:local` and the pinned
Node image in `compose.browser-fixtures.yaml`. `--pull never` and network-free
build containers prevent downloads. No database, private configuration, SDK credential
or staff worker is required. On a fresh host those cached images must first be
reproduced with the existing locked frontend/container build; that download/build
was not rehearsed here. This is a local fixture gate, not deployment packaging.
If your shell needs group activation, use `sg docker -c 'bash scripts/browser_fixture.sh check'`.

- Site A evaluation copy: <http://127.0.0.1:8096/shop/account/orders>
- Site B, FOLD & WEFT: <http://127.0.0.1:8097/account>
- B journey for a human: Purchases → matching receipt → Delivery → Parcel.
- Both `/health` endpoints should print `status: ready`.

```bash
bash scripts/browser_fixture.sh test runs/browser-investigation/final-gate
python3 scripts/grade_browser_evaluation.py runs/browser-investigation/final-gate
python3 -B -m unittest discover -s tests -p test_browser_evaluation.py -v
# Existing optional SDK environment, no installation or external HTTP:
../stage5-correction/.venv-decisions/bin/python -B -m unittest discover -s tests -p test_browser_evaluation_sdk.py -v
BROWSER_FIXTURE_TESTS=1 ../stage5-correction/.venv-decisions/bin/python -B -m unittest discover -s tests -p test_browser_bridge.py -v
bash scripts/browser_fixture.sh stop
```

Stop targets only project `decisionops-browser-fixtures`; there are no database
volumes to delete. Restart with `start`. Do not use the original Commerce project's
commands for these fixtures. The two fixture services have read-only source/data
mounts, 128 MiB limits and loopback ports. The test browser is a disposable container.

## What is implemented

`fixtures/server.mjs` serves only fictional customer projections. `evaluation.tsx`
imports Shop and SiteB, never the staff application. The site has no approval,
replacement, inventory, compensation-history or store-policy endpoints. B exposes
the carrier record only through an opened parcel disclosure. Its purchases list,
receipt/item view and parcel event table differ structurally from A's cards → detail
→ tracking page.

`harness.ts` owns a fresh Playwright context and four tools: open, observe, act,
finish. The policy can address **only current rendered control references**; no
selectors, JavaScript, network bodies or hidden DOM are exposed. Private transport
permissions in `permissions.ts` constrain shopper resources but are not sent as
route instructions. Each run stays on its initial loopback origin. GET/HEAD only;
all redirects, credential headers, unobserved documents, staff paths, frames,
popups, downloads, dialogs and WebSockets are rejected. Resources are streamed with
a 512 KiB cap and absolute 5-second/remaining-time bound before browser fulfillment.

Observations contain visible text, semantic blocks and role/name/state references.
Closed/hidden content is excluded. An intercepted fetch/render race was reproduced
and corrected with a bounded generic quiet interval plus in-flight tracking; no
site-specific readiness selector was added. A changed document invalidates references.
8 KiB/observation, 32 KiB cumulative observations, 16 observations, 12 action attempts,
32 open/observe/act attempts, 60 seconds/run, one known-read retry, 64 network requests and 8 MiB aggregate served resources. Finish is terminal
cleanup, not an additional navigation attempt. Rejected attempts count.

Citations must quote saved, untruncated visible blocks. Order binding must be
unambiguous; parcel claim/time share a single parcel record block. A separate saved
visible block must link the order/item/quantity to that parcel. A tracking page need
not repeat item fields if the inspected order detail establishes this relationship.
This fixture supports one requested line and one parcel. It proves page co-display
and navigation, not authoritative allocation across partial/multi-parcel shipments.
Browser evidence is always `untrusted-browser-page/v1`, `execution_authorized:false`;
it is **never** inserted into Commerce v1/v2 proposal evidence.

## Frozen evaluation and grading

`browser-investigation/evaluation/FROZEN.json` hashes the records, six-case matrix,
controller, task-only inputs, answers, API configuration and relevant implementation.
The original three-file freeze remains in commit d50e22b. The final manifest adds
source/build admission and aggregate network caps before any model run; it does not
change the six cases, their expected outcomes or the existing action/time caps. Inputs and expected answers are separate files.
The API runner reads tasks only. The grader runs separately and reads evaluator truth.

| Case (evaluator-only) | Entry and required inspection | Admissible result |
|---|---|---|
| A1 | A history → item/order → current parcel event | Bound loss/time evidence |
| A2 | A old in-transit event | Missing current evidence; quote stale record |
| B1 | B dashboard → receipt → opened parcel | Same fact as A1, different navigation |
| B2 | B opened parcel without event/time | Missing evidence, cite inspected parcel |
| G1 | B parcel belongs to another order | Reject binding, preserve mismatch |
| G2 | A tracking page fails | Bounded tool-unavailable stop, partial evidence |

The model sees goal + entry URL then observations, control refs, attempts/budgets
and rejection/error feedback. Case keys, site labels, record JSON, expected answers,
source hashes and pricing/correlation metadata stay outside its features. Matching
identifiers printed on the page are necessary binding data, not hidden evaluator labels.

`frontend/browser-tests` deliberately uses fixture-specific scripts **only as tests**.
Six accepted scripts do not establish autonomous navigation or transfer. A1/B1 are
paired versions of one fact pattern, not independent model-quality samples.
The grader checks field support, binding, honest completion/stop and read-only safety.
An early missing-evidence claim without inspecting the relevant source fails evidence
acquisition even if it is safe. Failures and incomplete outcomes must remain in results.
No scoring-driven controller adjustment after live runs is part of this evaluation.

## Proposed live evaluation — NOT RUN, explicit approval required

The existing **Commerce Decisions adapter is preserved**. This separate browser
controller proposes Responses structured JSON because actions require dynamic control
references and quoted citations, not just the existing Commerce two-choice task.
No hosted browser tools, LangChain agents or deterministic route fallback are used.

Proposed official SDK: existing locked `openai==3.26.0` optional environment.
Endpoint `https://api.openai.com/v1/responses`, model `gpt-6-luna`, reasoning `none`,
standard-global/default service tier, `store:false`, SDK retries **zero**. The model
alias has no dated snapshot listed in the fetched official page: response model is
validated and recorded, but immutable weights are not claimed. Account availability
has not been probed. Refusal/unavailability stops without model switching.

Six cases, sequentially, at most **8 calls/case = 48 calls**. Each complete JSON
request (instructions, schema and all permitted context) is capped at **32,768 bytes**;
reserve **36,864 input tokens** including conservative envelope headroom. Maximum
**1,024 output tokens/call**, including any reasoning tokens. No silent truncation of
requests. Observations explicitly flag their own truncation; truncated blocks cannot
be cited. 15 seconds/decision, existing 60 seconds/case, 420 seconds/evaluation;
owned browser container 768 MiB and 128 PIDs. No second evaluation on failure.

Official standard rates checked 13 Nov 2026: input $0.10/M, output $0.50/M; cache
writes can cost $0.125/M input. Reservations conservatively use **$0.125/M for all
input** and $0.50/M output. Per call $0.00512; 48 calls **$0.24576 maximum reserved**,
proposed monetary cap **$0.25**. Maximum totals: 1,769,472 reserved input and
49,152 output tokens. No tools, regional/Fast premium or cache-discount assumption.
Usage records retain native fields. Standard usage estimate and conservative upper
estimate are labelled separately; neither is an invoice. Unknown usage retains the
whole reservation and stops. A response outside token bounds stops as a breach.

`api-config.json` canonical SHA-256 is printed without touching credentials by:

```bash
python3 scripts/browser_evaluation.py --describe
```

**Future paid command, do not execute until explicitly approved for its exact hash:**

```bash
../stage5-correction/.venv-decisions/bin/python -B scripts/browser_evaluation.py \
  --run-live-test --approve-config 487709fc2490a9e175d32309cbd414623de6508b31fe70698851f7553dc1d566 \
  --source REVIEWED_FULL_COMMIT_SHA \
  --output runs/browser-investigation/live-evaluation-001
```

Use a Docker-authorized credential-bearing terminal. The key is read from its
environment by the host SDK only, never forwarded to the browser container or saved.
No startup command, test, ordinary worker, import or `--describe` initiates paid calls.
Source must be the exact clean reviewed commit and match all frozen source, compiled
bridge and built-asset hashes. Preflight also checks each running fixture's startup
source/record identity and byte equality of served assets; these local checks never
enter model context. Start recreates only the fixture containers and waits for readiness.
One new output directory is one admission. Existing directories/ledgers cannot be
reopened/reset. Reservation and dispatch disposition are fsync-persisted before
work. Unknown dispatched results retain reservation; no retry, recovery dispatch,
second directory or replacement budget is authorized by the proposed one evaluation.
All request bodies, decisions, native usage, elapsed time, observations and outcomes
are local records. The output stores partial current context even after failure;
known late results are accounted but unapplied. Actual browser faults stop that case;
provider failure/uncertainty or invalid result stops remaining evaluation cases.
`grade_browser_evaluation.py OUTPUT_DIRECTORY` grades afterward, never inside policy.

Sources: [model and pricing](https://developers.openai.com/api/docs/models/gpt-6-luna),
[structured outputs/refusals](https://developers.openai.com/api/docs/guides/structured-outputs).

## Existing local evidence

Agent-executed, no supervisor attribution: 15 browser tests, six graded scripted cases,
ten dependency-free controller/accounting tests and three grader tests, three real-SDK/fake-HTTP tests,
and one actual browser-bridge test with scripted fake choices. Fake token counts in
the smoke trace are explicitly marked simulated; they are not model-performance,
real usage or incurred charges. Negative outputs (collection errors, render race,
strict typing and binding-rule correction) remain in `runs/browser-investigation`.
CI, staff-browser/PostgreSQL regressions and live browser API evaluation were not run:
Commerce source and dependency locks are unchanged; this milestone has no DB effects.
The prior live Commerce Decisions trace remains historical, not browser evidence.

Screenshots: `runs/browser-investigation/final-gate/screenshots/site-b-dashboard.png`,
`site-b-receipt.png`, `site-b-parcel.png`. Model-free raw audits are A1…G2 JSON alongside
the screenshots; `model-free-grades.json` records grading. `bridge-smoke.json` records
the separately labelled fake transport integration. See BROWSER-GRAPH-TRACE-PLAN.md
for the next proposed PostgreSQL/LangGraph/Langfuse change; it is not implemented here.
