# DecisionOps Commerce: engineer and reviewer walkthrough

A customer reports a missing clothing parcel. The report starts an investigation;
it does not establish that the parcel was lost or that a replacement is permitted.
This offline release candidate demonstrates evidence collection and a deterministic,
explicitly approved fictional replacement. **End-to-end live task completion and cross-site behavior remain unverified.**

## Two paths, one permission boundary

The staff console uses rules by default: report → durable adaptive investigation →
seven projected PostgreSQL reads → current supported assessment → proposal or review.
`decisionops/commerce/staff_investigations.py` owns browser/API job admission and worker
progress; `adaptive_runner.py` validates choices; `adaptive_investigations.py` and
`cases.py` publish/revalidate proposals; `execution.py` owns the transaction. Exact
proposal/generation/content-hash approval plus a separate execution confirmation
are required. Duplicate prevention, stock reservation and reconciliation stay there.

The **separate** browser harness starts with a goal and local URL. It observes visible
shopper controls, asks for one next decision, validates and applies that action once,
then observes the actual resulting page before requesting another decision. It cannot
read staff inventory/history/policy or create a Commerce proposal. Page claims are
`untrusted-browser-page/v1`; they are never authoritative Commerce attestations.
A completed page-evidence task is not permission to replace anything.

## Follow an actual successful offline navigation

`tests/test_browser_bridge.py` connects the installed OpenAI SDK through MockTransport
to `scripts/browser_evaluation.py` and the actual Playwright bridge. The mock's
fixture-specific action names live **only in the test**, not the controller.

1. `investigate()` opens A's order history. The permitted request context contains the
   goal, bounded rendered observations/current control references and remaining caps.
   SDK request serialization uses one strict forced `browser_action` function and
   `parallel_tool_calls:false`; no paid HTTP occurs in this test.
2. The mock selects the observed order link. `parse_action()` requires exactly one
   completed correctly named call and independently validates the action schema.
   `BrowserInvestigation.act()` checks the current observation/reference and request
   guards before navigating. No selector, hidden DOM or evaluator answer is a feature.
3. The resulting order detail becomes the next request's observation. The next mock
   choice opens tracking, then returns saved citations for order, variant/quantity,
   parcel, carrier claim and timestamp. The harness validates their visible bindings.
4. `scripts/grade_browser_evaluation.py` separately grades frozen results; expected
   answers never enter the controller. Six **scripted** fixture runs cover current,
   stale, missing, wrong-bound and unavailable evidence. They test integration and
   grading contracts, not autonomous navigation or held-out model quality.

Open the public walkthrough's **redacted mocked navigation trace** to inspect each
choice, latency, simulated usage/reservation and observation event. Raw permitted
inputs and citations stay in ignored `runs/browser-investigation/bridge-smoke.json`.
The corresponding frozen-case exports are under `runs/portfolio-rc/browser/`.
Mock token counts/costs are simulation evidence, not actual API usage or incurred cost.

## What the real failure proves—and the correction

Richard ran the single authorized `live-evaluation-001` from his terminal. Its
unchanged ledger remains in the `browser-investigation` worktree's ignored evidence
folder. One completed Responses HTTP body contains three distinct message items:
commentary `act(c5)`, commentary `observe`, final answer `finish(missing_evidence)`.
The SDK streaming-response wrapper accumulated bytes and decoded that body once;
local code did not synthesize three decisions. The raw network byte stream/headers
were not retained, so the decoded saved response is the preserved protocol evidence.
It does not explain why the provider emitted that sequence.

The original strict text schema constrained message shape, not decision cardinality.
Rejection before application was correct: A1 failed validation, the other five cases
were unexecuted; no returned action ran. One request used 1,931 input/388 output tokens;
including 1,928 cache-write tokens its historical estimate was $0.0004353. No retry ran.
The new parser still rejects that exact response shape; it does not select the first
message or the final answer. The new request forces one strict named function with
parallel calls disabled. A valid single call is applied once and the next request
waits for its actual browser reply. Refusals, mixed/multiple calls, invalid arguments,
timeouts/uncertain usage and stale/late results remain failure boundaries. Final-action
browser failures remain operational stops; successful unfinished final actions remain
budget exhaustion. See `test_browser_protocol.py`, `test_browser_evaluation_sdk.py`
and `test_browser_evaluation.py`. The second authorized run demonstrated the strict protocol on three responses,
then stopped at citation validation as described below; both authorizations are consumed.

## Live Site A navigation and offline citation closeout

In `live-evaluation-002`, the real API returned exactly one function per request.
Two read-only actions actually ran: order history → OR-4821 detail → PK-6204 tracking.
The third response cited the observed shirt-blue-M/quantity1, lost carrier status and
`13 Nov 2026, 10:00 UTC`, then requested `finish(evidence_found)`. The historical
validator tried to parse its whole-record timestamp quote as a date and rejected it
as `stale_evidence`. A1 therefore remains **failed (`invalid_finish`)** and A2/B1/B2/G1/G2
remain **unexecuted**. Three calls used7,614 input/558 output tokens; estimated cost
including cache writes was$0.00122085. The ledger and case result are unchanged.
This supports live Site A navigation, not completed investigation or transfer to B.

The published instructions said “Cite exact visible quotes” and “Prefer a complete
semantic block”; neither schema nor request required a timestamp-only quote. The
validator was narrower than that contract. `harness.ts` now resolves a whole-record
quote only after existing order/parcel/observation binding, from one labelled
(`Update recorded` or `Recorded timestamp`), untruncated source block with exactly
one timestamp. The quote itself must include that timestamp. Supported formats are
the fixtures' UTC display form and ISO8601 with Z; unsupported formats, multiple
candidate times (even duplicates), invalid calendar dates or wrong records fail
closed. No newest-date selection or lookup in another block occurs. The unchanged
freshness check requires age between0 and24 hours against the frozen goal.as_of.

`frontend/browser-tests/citation.spec.ts` replays the **exact saved final response**
against its saved observation blocks. It now passes offline, as does the unchanged
grader on that explicitly labelled derived replay. The source timestamp is exactly
two hours before `2026-11-13T12:00:00Z`. Precise timestamp quotes still work; stale,
future, ambiguous, missing and wrong-record evidence remains rejected. This does
not rewrite the historical failure, rerun navigation or establish a new live success.
See ignored `runs/portfolio-rc/citation-closeout/` for commands, raw test outputs and
the separately labelled replay/grade. Both original live runs stay immutable.

## Start and review the fictional staff demo

Prerequisites: Docker/Compose and the existing locked cached base images. No API key,
model packages, account or private configuration is needed. From a clean checkout:

```bash
# Fictional local-only test password; replace privately before any future invitation.
export COMMERCE_PORTFOLIO_PASSWORD=fictional-rc-local-demo-only
sg docker -c 'bash scripts/portfolio_rc.sh build'
sg docker -c 'bash scripts/portfolio_rc.sh start'
sg docker -c 'bash scripts/portfolio_rc.sh check'
# Optional automated proof: run NOW on fresh records, before manual interaction.
sg docker -c 'bash scripts/portfolio_rc.sh verify'
```

Staff: <http://127.0.0.1:8103>, username `visitor`, password set above.
Read-only portfolio: <http://127.0.0.1:8104>. It has no API/reset route or credentials.
Select ORD-1042 → Start review → enter a shipment report → Investigate shipment.
Watch all seven reads including inventory; refresh/sign in to see persisted progress.
Approve replacement → Confirm approval → Create replacement → Confirm replacement.
These last clicks change only fictional records. ORD-HISTORY instead leaves incomplete
compensation history unknown: review explanation, no proposal or replacement controls.

Only nginx has a loopback host port; API, workers and PostgreSQL use the new internal
project network. New RC image tags and volume cannot affect preserved release stacks.
Public static service uses a separate project/network. `/health` must be healthy;
init must exit zero after migration0008/fictional seed/checkpoint setup. The startup
command waits for readiness. Restarting containers preserves the database volume.

```bash
# The one-time verify above creates one replacement; do not repeat or overwrite it.
# Stop removes only RC containers/networks; preserves its volume and historical stacks.
sg docker -c 'bash scripts/portfolio_rc.sh stop'
# Start again: existing cases/compensation must persist.
sg docker -c 'bash scripts/portfolio_rc.sh start'
# Explicit operator-only destructive reset of ONLY this fictional RC volume:
sg docker -c 'RESET_FICTIONAL_RC=1 bash scripts/portfolio_rc.sh reset'
```

After the verified replacement, ORD-1042 is compensated; it must not get another one.
Reset only when deliberately opening a fresh demo window, after exporting any wanted
RC evidence. Do not reset ledgers or original runtime volumes. `verify` refuses to
reuse its existing evidence directory; preserve that proof rather than overwrite it.

## Offline browser verification and trace inspection

The fixture build/test commands require the cached browser image; no dependencies
are installed. The original A/B records/permissions/grader remain unchanged.

```bash
sg docker -c 'bash scripts/browser_fixture.sh build'
# Reuse existing admitted 8096/8097 fixtures READ-ONLY; never recreate their project.
# On a fresh host ONLY, with both ports free, a separate RC project can serve them:
# sg docker -c 'docker compose -p decisionops-portfolio-rc-browser -f compose.browser-fixtures.yaml up -d --pull never'
# Do not use browser_fixture.sh start/stop against a preserved fixture project.
sg docker -c 'bash scripts/browser_fixture.sh test runs/portfolio-rc/browser'
python3 scripts/grade_browser_evaluation.py runs/portfolio-rc/browser
python3 -B -m unittest discover -s tests -p test_browser_evaluation.py -v
python3 -B -m unittest discover -s tests -p test_browser_protocol.py -v
python3 -B -m unittest discover -s tests -p test_browser_grading.py -v
python3 -B -m unittest discover -s tests -p test_browser_trace.py -v
# Use the existing optional locked SDK environment, do not install it during demo:
../stage5-correction/.venv-decisions/bin/python -B -m unittest discover -s tests -p test_browser_evaluation_sdk.py -v
sg docker -c 'BROWSER_FIXTURE_TESTS=1 ../stage5-correction/.venv-decisions/bin/python -B -m unittest discover -s tests -p test_browser_bridge.py -v'
python3 scripts/browser_trace.py runs/browser-investigation/bridge-smoke.json --output runs/portfolio-rc/navigation.html
```

The optional SDK environment path is this workstation's existing profile, not a
fresh-host prerequisite for the rules staff demo. A missing SDK skips its optional
tests explicitly; do not report that as passed. `scripts/commerce_ci_tests.py`
records dependency-free and required-PostgreSQL profile counts/skips.

## What was actually verified locally

Clean-checkout rehearsal at `8f0685f`: cached locked build, no private configuration,
new empty PostgreSQL database migrated to0008, **2/2 staff browser tests** with zero
skips. They covered seven reads/inventory, refresh/duplicates, exact approval/separate
execution confirmation, one replacement and incomplete-history review. Worker restart
continued from one committed read to seven with two claims, unchanged deadline and
no repeated effect. Full stack stop/start preserved records. An explicit operator
reset was exercised after exporting the rehearsal DB; the handoff demo is fresh.

Also passed locally:4 real PostgreSQL/LangGraph recovery checks,15 browser-harness
checks,6/6 graded scripted cases,1 actual SDK-mock→browser success,4 SDK checks,
3 protocol,12 controller,3 grader,2 trace,8 rehearsal-config and4 static-evidence tests.
Public boundary checks rejected24 mutation requests without changing records, and
three public walkthrough/trace pages rendered. The dependency-free entry point
collected507:228 passed,279 explicitly skipped, zero failures/errors. Skips include
DB/model/optional SDK/browser profiles under `-S`; focused DB/SDK/browser checks ran
separately. Counts overlap and must not be summed as independent verification.

Evidence is indexed in ignored `runs/portfolio-rc/`: `staff-rehearsal/` contains logs,
screenshots and durable snapshots; `langgraph-postgres.log`, `stack-restart-summary.json`,
SDK/controller/protocol logs and `scripted-grades.json` cover the other checks. The
pre-reset SQL dump/hash preserves the newly created proof records. Final doc-only
changes preserve tested runtime bytes and receive a final clean build/health check.
CI, full PostgreSQL profile, native models, fresh-engine downloads and live protocol
verification were not run. Checks are agent-executed; Richard reported executing the
original live command. No new supervisor/CI verification is claimed.

## Next live gate — prepare only

The request changed from strict `text.format` JSON to:

```json
{"tools":[{"type":"function","name":"browser_action","strict":true,"parameters":"existing action schema"}],
 "tool_choice":{"type":"function","name":"browser_action"},"parallel_tool_calls":false}
```

The actual parameters contain the full unchanged action schema. Instructions require
only the next decision, then waiting for its real browser result. Configuration v2
SHA-256 is `415bef1abf402329e9d9d323fcd2d2d920da36f7c939c8a023bed420d5dccbd3`.
Model remains `gpt-6-luna` on Responses, retries0, at most48 requests across six cases,
36,864 reserved input/1,024 maximum output tokens per request, unchanged deadlines,
$0.24576 worst-case reservation and $0.25 cap. The new output is
`runs/browser-investigation/live-evaluation-003`; never reopen/reset001 or002. The exact
final-source command is supplied in the local handoff, for a Docker-authorized
credential-bearing terminal **only after a new explicit spending approval**.
No startup, test, background worker or credential presence authorizes that call.

Before a separate hosting decision, export the reviewed runtime images locally if
needed (not credentials or volumes), then verify/load them on the approved host:

```bash
# Packaging only; no upload, paid service or provider access.
sg docker -c 'docker tag postgres:16.15-bookworm@sha256:0ea6700a3b4f0ae6ce746519073558aed4d88a79d8d07622a9a644946c7319c4 decisionops-portfolio-postgres:rc'
sg docker -c 'docker save decisionops-portfolio-app:rc decisionops-portfolio-web:rc decisionops-portfolio-walkthrough:rc decisionops-portfolio-postgres:rc' > runs/portfolio-rc/runtime-images.tar
sha256sum runs/portfolio-rc/runtime-images.tar
# Later, only on an approved host: docker load --input runtime-images.tar
# Then: export COMMERCE_PORTFOLIO_POSTGRES_IMAGE=decisionops-portfolio-postgres:rc
```

Image export/transfer/fresh-engine loading is not claimed executed in this milestone.
The isolated stack's tested image IDs are in the evidence inventory. Stop the RC with
its own script for rollback; restore its pre-reset SQL only into a deliberately empty
RC database, never the original runtime. No new migrations were added. Existing
[hosting/HTTPS guidance](PORTFOLIO-RELEASE.md) remains a proposal, not a deployment.

## Framework ownership and release limits

**LangGraph already exists.** `decisionops/commerce/workflow.py` persists a review
interrupt; resume consults the actual durable approval, never a graph input claiming
approval. Focused `test_commerce_jobs` checks cover interruption/resume, checkpoint
failure after commit without re-investigation, and worker restart inspection.
`adaptive_workflow.py` reconstructs from committed steps/reservations with bounded
checkpoint SQL. PostgreSQL remains authoritative. The staff investigator's own
restart proof uses durable jobs/tick, not LangGraph; the separate browser evaluator
is not secretly orchestrated by a graph.

**Trace inspection is local.** `browser_trace.py` allowlists numeric usage, timing,
validation codes, action names and content hashes before HTML generation. It removes
page/report text, URLs/identifiers, headers, keys and arbitrary provider errors. Export
is disabled and the renderer imports no network client. A future optional Langfuse
Python v5/server-v4 adapter could consume that projection after endpoint/retention
approval; neither dependency nor service is installed. Deep Agents adds planning,
filesystem context and delegation that would duplicate this bounded controller; it
is intentionally excluded. See [the bounded integration plan](BROWSER-GRAPH-TRACE-PLAN.md).

This rehearsal uses cached locked dependencies, not a clean engine with downloads.
Shipping to a new host requires approved image transfer or an explicitly approved
locked image build, plus HTTPS, private invitations, storage/backup/reset policy and
hosting approval. No public deployment or completed live investigation is claimed.

Reusable portfolio description: “DecisionOps Commerce is a fictional shipment-review
application with durable evidence gathering, deterministic eligibility and explicitly
approved transactional replacements. A separate read-only browser harness investigates
two shopper interfaces. Rules and mocked-provider flows are verified offline. Live API decisions navigated
one Site A order to tracking, but its finish was rejected; the citation correction
is verified by offline replay only. Neither full live completion nor cross-site
transfer has been established.”


## Optional bounded specialist candidate

The opt-in local mode is documented in [MULTI-AGENT.md](MULTI-AGENT.md).
It uses mocked tool choices, a typed LangGraph fan-out/join and PostgreSQL fencing.
Rules remain the default. This staff path reads database records; the preserved browser
benchmark/live traces are separate and do not power this workflow.
No live multi-agent inference or public deployment is claimed.
