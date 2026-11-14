# Bounded specialists: local reviewer guide

For the supported standalone release,start with the [root quickstart](../../README.md).
The raw evidence paths in this accepted milestone record now refer to the external
[archive](../ARCHIVE.md);the [publishable summary](../EVIDENCE.md) requires no private path.


This optional Commerce demo splits evidence gathering between two specialists while
retaining the existing replacement policy, exact staff approval and separate execution.
Rules remain the default. Select `mock-specialists` explicitly to exercise the new path;
the browser identifies it as **Mocked specialists. No paid calls.** This is a fictional,
local integration demonstration. It does not demonstrate live model quality, lower cost,
faster investigations or improved business outcomes. The [verification record](MULTI-AGENT-VERIFICATION.md) separates executed checks and remaining gates.

The [architecture decision](../decisions/2026-11-13-bounded-specialists.md) defines the
contracts and alternatives. The implementation lives in
[`multi_agent.py`](../../decisionops/commerce/multi_agent.py) and
[`multi_agent_workflow.py`](../../decisionops/commerce/multi_agent_workflow.py).
The checks below distinguish local evidence from unexecuted live and hosting work. The separate browser benchmark harness is outside this mode.

## Ninety-second explanation

A store employee reports a missing parcel. The coordinator first reads the order
manifest and applicable replacement policy. The Order specialist chooses whether to
check payment or fulfilment first. Shipment tracking cannot start until an explicit
fulfilment observation binds the selected parcel to this order.

Once that binding exists, remaining Order payment work can overlap with Shipment
work. The Shipment specialist chooses carrier evidence or an explicit fulfilment
refresh. Both specialists select bounded, read-only tools from their own allowlists;
they cannot approve replacements or infer evidence that a tool did not return.

The coordinator then gathers compensation history and available stock. A deterministic
join checks all seven required conditions, dependencies, current scope and freshness.
Missing or conflicting evidence produces an explained review outcome; an unmet
condition blocks replacement. Complete evidence can produce a proposal. The employee
still approves the exact proposal and separately confirms execution. Creating a
replacement remains an existing transactional business operation.

PostgreSQL records the work and owns recovery. The graph coordinates the branches
and saves a projection of their progress. A graph checkpoint cannot authorize a
replacement or replay a committed business effect. The purpose is to make scoped
choices, branch progress and recovery inspectable, not to claim that additional agents
outperform the simpler existing controller.

## Evidence flow and authority

```mermaid
flowchart TD
    M[Coordinator: manifest and applicable policy] --> O[Order: choose fulfilment or payment first]
    O --> B[Explicit fulfilment binds selected parcel]
    B --> P[Order branch: remaining payment read]
    B --> S[Shipment branch: choose carrier read or explicit fulfilment refresh]
    P --> C[Coordinator: compensation history and inventory]
    S --> C
    C --> G[Deterministic gate: seven conditions, scope, dependencies and freshness]
    G --> R[Explained review or blocker]
    G --> Q[Replacement proposal]
    Q --> A[Exact staff approval]
    A --> E[Separate execution confirmation]
```

Only the two branches after parcel binding may overlap. Fulfilment is a dependency of
carrier evidence. The coordinator owns compensation and inventory reads; neither
specialist controls eligibility. Observations remain bound to the case, order, shipment,
generation and dependency versions. An unavailable branch preserves a completed sibling
but does not satisfy missing conditions or bypass the gate.

PostgreSQL is authoritative for run admission, leases, attempt budgets, branch calls,
observations and terminal publication. LangGraph checkpoints contain projection IDs and
statuses. On restart, reconstruct from committed rows, retain consumed attempts and
original deadlines, and skip effects already applied. Known settled results require
current ownership and dependency checks before application. Abandoned dispatched work
is uncertain and routes to review; it is not silently repeated. Late results cannot
overwrite newer case decisions. See the ADR for the full recovery and fencing contract.

## Isolated local operation

Use only the dedicated project `decisionops-multi-agent-demo`. Its web listener is
`http://127.0.0.1:8123`, its username is `visitor`, and its images are
`decisionops-multi-agent-app:local` and `decisionops-multi-agent-web:local`.
The [overlay](../../compose.multi-agent.yaml) builds on
[`compose.portfolio.yaml`](../../compose.portfolio.yaml), retains its isolated database
volume and network protections, and enables `COMMERCE_STAFF_INVESTIGATION_MODE=mock-specialists`
only for this API. The ordinary worker retains its existing CLI; the specialist
investigator uses the existing staff worker entry point with the new job routing.

The [script](../../scripts/multi_agent_demo.sh) fixes the project, port and origin.
Supply an explicit fictional local password of at least 16 characters through the
environment. It must not be a reused account password. For example, enter it without
putting the value in shell history:

```bash
read -r -s -p 'Fictional local password: ' COMMERCE_MULTI_AGENT_PASSWORD
export COMMERCE_MULTI_AGENT_PASSWORD
bash scripts/multi_agent_demo.sh build
bash scripts/multi_agent_demo.sh start
bash scripts/multi_agent_demo.sh check
# Open http://127.0.0.1:8123 and sign in as visitor.
bash scripts/multi_agent_demo.sh stop
unset COMMERCE_MULTI_AGENT_PASSWORD
```

These commands were rehearsed against the new fictional project. Builds require the
existing locked local base images and cached dependencies. They use no build network,
package installation or new model download. Startup forbids image pulls. No provider
credentials are forwarded. The overlay's `!override` port declaration requires Docker
Compose 2.24.4 or later. `stop` removes this project's containers and network while
retaining its fictional database volume. Do not substitute the original demo project,
retag its images, or apply migrations to its running database.

## Review and verification status

Verification below was agent-executed locally. CI was not run or published.
Use a fresh isolated fictional database for the acceptance scenarios; executing a
replacement changes stock and compensation history for later runs.

| Check | Intended evidence | Status |
| --- | --- | --- |
| Mode isolation and admission | Rules default; opt-in mocked mode; matching retries coalesce | Passed locally |
| Eligible order | Branch choices and source references, full evidence, one proposal | Passed locally |
| Approval and execution | No execute before exact approval; separate confirmation; one replacement | Passed locally |
| Missing history or unavailable branch | Successful sibling retained; missing condition stays unknown; no proposal | Passed locally |
| Stock failure | Failed stock condition remains a blocker; no approval | Passed locally |
| Recovery and stale results | Restart after committed branch; no repeated effect; late or unowned result unapplied | Passed locally |
| Clean isolated deployment | Local images, port 8123, worker routing and health checks | Passed locally |

The separate scoped browser suite is
[`frontend/multi-agent-tests/specialists.spec.ts`](../../frontend/multi-agent-tests/specialists.spec.ts).
With the isolated stack running, a fresh fixture and cached browser dependencies,
run from `frontend`:

```bash
npx --no-install playwright test -c playwright.multi-agent.config.ts
```

It expects the explicit `COMMERCE_MULTI_AGENT_PASSWORD` environment variable and
covers an eligible order, incomplete history and failed stock. Backend tests must
separately establish injected unavailable tools, restart and stale-result behavior;
there is no hidden failure-scenario selector in the UI or specialist policy. Do not
alter the existing portfolio verifier's project allowlist merely to run this demo.

## Tradeoffs and adoption

The existing fixed-order controller is simpler and already adequate for these fictional
cases. Bounded specialists expose ownership, independent read choices and explicit
join/recovery behavior, at the cost of more persisted coordination state, fencing and
failure paths. A dynamic supervisor would add delegation choices where the task graph
is already known. No measured quality, latency or cost gain supports adoption here.
Keep this mode opt-in; any comparison needs matched fictional requests, mandatory
coverage, duplicate-effect counts and clearly stated mocked timing conditions.

## Claim-by-claim closeout at c8dc5b5

This map reviews the existing bundle/logs only; no suite, investigation or runtime
operation was repeated. Evidence paths below are relative to `runs/multi-agent/`
in this worktree (`evidence/` inside the existing review archive). All choices are
mocked and all staff interactions below were automated tests, not Richard's actions.

**Success, including approval and separate execution — verified locally.** Follow
M→O→B→P/S→C→G→Q in the diagram through
[`multi_agent_workflow.run`](../../decisionops/commerce/multi_agent_workflow.py),
[`multi_agent.join`](../../decisionops/commerce/multi_agent.py), then
[`adaptive_investigations.publish`](../../decisionops/commerce/adaptive_investigations.py).
`walkthrough-release/success.json` is run
`ARUN-595a7ac8f0504b0289b4e12dc0b07a9d`: Order chooses fulfilment/payment;
Shipment chooses carrier_loss; join step 25 leads to proposal step 27 with 7/7 conditions
and `execution_authorized:false`. The trace ends at the proposal, not execution.
The same success case is subsequently approved/executed by the assertions in
[`commerce_specialists_walkthrough.py`](../../scripts/commerce_specialists_walkthrough.py)
(main: explicit staff operations); `walkthrough-release/summary.json` records 2 execution
invocations but 1 replacement. The exact backend test is
`SpecialistTests.test_seven_facts_publish_existing_proposal_and_require_exact_approval`
in [test_commerce_specialists.py](../../tests/test_commerce_specialists.py)
(`focused-final.log`:ok). A→E is also exercised by the browser test
`specialist choices and sources remain visible before exact approval and execution`
in [specialists.spec.ts](../../frontend/multi-agent-tests/specialists.spec.ts): unapproved
execute returns 409, approval confirmation precedes a separate replacement confirmation,
operation becomes verified and exactly 1 executed event exists. Its saved pass is in
`browser-clean.log` and `browser-clean/multi-agent-report.json`.
Exact generation/proposal/hash mismatch rejection is independently covered by
`ExecutionTests.test_wrong_proposal_hash_generation_and_case_are_rejected` in
[test_commerce_execution.py](../../tests/test_commerce_execution.py)
(`postgres-release.log`:ok), through the unchanged `cases.review_case` validator.
Approval/execution are therefore test/report-backed; a continuous post-proposal
approval/execution event trace is **not saved in success.json**.

**One specialist fails, peer evidence survives, no proposal — verified by the saved
executable walkthrough.** Follow the Shipment branch to G→R. The walkthrough's
`Unavailable.choose` raises RuntimeError; the graph's `choose` records uncertainty
rather than inventing a result. `walkthrough-release/partial-failure.json`, run
`ARUN-ea52e50f9048456e9e475c8d6d5b5e40`, retains both applied Order calls and 4 established
facts. Shipment has `state:uncertain`, `dispatch_count:1`, no decision. Join step 18
ends at review step 20, with loss/compensation/stock unknown and no proposal ID.
The walkthrough assertions check review and retained paid/shipped facts; its final
proposal-count assertion excludes a proposal for this failed case. Results are in
`walkthrough-release.log` / `summary.json`. The related unit test
`test_cancelled_decision_keeps_sibling_evidence_and_never_redispatches`
(`focused-final.log`:ok) verifies cancellation retention/no redispatch; it does **not**
itself test the unavailable-provider join. Do not label it as that exact scenario.

**Stale/conflicting/wrong-case rejection — evidence has different coverage.**
`test_conflicting_authority_and_expired_tracking_do_not_pass_join`
(`focused-final.log`:ok) runs the full graph and asserts review, unknown loss,
retained payment and no terminal proposal ID. It injects an expired observation or
an unknown observation marked `conflicting_records`; it does not create genuinely
contradictory authoritative database rows. There is **no saved per-run trace** for
these adversarial test runs. `test_case_change_during_read_discards_late_result`
verifies stale case admission and preservation of staff escalation. Wrong-case coverage
is `test_wrong_request_observation_cannot_supply_payment_fact`; wrong-tool/dependency
coverage is `test_wrong_tool_and_missing_dependencies_are_discarded_without_pointer_corruption`.
Both reject before active evidence is admitted in `multi_agent.read`, with no proposal
at that point (`focused-final.log`:ok). A wrong-case result carried through a final
join, and a multi-agent join over actual conflicting authoritative rows, remain
**unverified as end-to-end scenarios**. No standalone adversarial traces are claimed.

**Restart after branch commit without duplicate dispatch/proposal — verified locally.**
Follow B→P, interruption, reconstruction from PostgreSQL, then S→C→G→Q. The exact tests
are `test_completed_order_branch_is_not_dispatched_again_on_graph_resume` and
`test_actual_graph_interrupt_after_order_commit_replays_no_effects`
(`focused-final.log`:both ok). They retain Order observation/call IDs, refuse any
Order adapter replay, finish at 7 reads and assert 1 proposal after graph replay.
For actual container recovery, [commerce_specialists_restart.py](../../scripts/commerce_specialists_restart.py)
stops the worker after Order commits, waits for lease expiry and restarts it.
`clean-worker-restart/before.json`, `paused.json`, `after.json` and `trace.json`
share run `ARUN-24a1e41a3b434ad49a9012d4336da57b`. The saved trace has 3 specialist calls,
each dispatched once; the script checks retention of 2 Order observations, 7 total reads,
null approval and null operation. `clean-worker-restart.log` records 44.01s including
the intentional 31s lease wait. `walkthrough-release/recovery-before.json` and
`recovery-after.json` additionally show the same run and 4 retained observations under
explicit reclaim. These recovery runs stop at a proposal: no replacement is executed.
Exactly-once execution **after recovery** is unverified here; ordinary duplicate
execution is separately checked by the successful walkthrough, not this restart trace.

The selected same-input comparison in `walkthrough-release/summary.json` is the
**existing fixed-order adaptive rules controller**, not a live single-model baseline.
Both paths use 7 policy-visible reads/8 decisions and produce complete proposals;
private safety SQL is additional. The saved local sample is 783ms rules versus 1660ms
mocked specialists. It is not a quality benchmark, repeated-state sample expansion,
production latency estimate or provider-cost measurement. Specialists stay opt-in.
Live multi-agent behavior, public CI for this source and an uncached fresh-host build
remain **unexecuted gates**. The separate historical live browser traces do not verify
this staff workflow. No framework, provider or deployment was added during closeout.

## Follow the implementation and trace

Start with `staff_investigations.enqueue` (authenticated case lock and idempotency),
then `multi_agent_workflow.run` (identity → binding → fan-out → join). Each specialist
uses `SpecialistRequest`/`validate_action` in `specialist_contracts.py`. `multi_agent.reserve`,
`choose` and `read` separately reserve counts, dispatch one mocked choice, settle it,
and execute/admit exactly one scoped read. The allowed choices are real inputs: a
payment cue changes Order's priority; a refresh cue can choose an explicit fulfilment
refresh before tracking. No agent conversation or hidden bundled assessment occurs.

`adaptive_tools.read_tool` supplies projected record evidence. The join reconstructs
`History` and passes to the existing `adaptive_investigations.advance` proposal path.
Its private safety reread confirms collected contents; it cannot fill unknown checks.
`cases.review_case` binds exact generation/proposal/hash. `execution.execute` retains
transaction locks, stock reservation, compensation checks, duplicate prevention and
reconciliation. The existing browser has two distinct approval/execution confirmations.

Local evidence (ignored, not intended for public upload) is under `runs/multi-agent/`:

- `walkthrough-release/success.json`: decisions, seven reads, join and proposal.
- `walkthrough-release/partial-failure.json`: unavailable Shipment, retained Order facts,
  unresolved reservation, missing loss/history/stock and manual review; no proposal.
- `walkthrough-release/recovery-before.json` and `recovery-after.json`: same committed
  observation IDs retained after reclaim. No order redispatch or duplicate proposal.
- `clean-worker-restart/trace.json`: actual container stop, lease expiry and restart.
- `browser-clean/multi-agent-results/` and `browser-clean/multi-agent-report.json`: actual staff UI, not
  autonomous browser navigation. See the [evidence index](MULTI-AGENT-EVIDENCE.md) for exact current paths/hashes.

Inspect an existing run without dispatch (inside this isolated container only):

```bash
docker exec decisionops-multi-agent-demo-staff-investigator-1 \
  python -B -m decisionops.commerce.multi_agent inspect ARUN_REPLACE_WITH_SAVED_ID
```

The `resume JOB_ID` and `recover JOB_ID` commands use the same module. They claim only
this job partition, require an expired/queued claim, never override a live token, retain
original budgets/deadlines, and never redispatch uncertain decisions. To inspect safely,
use `inspect`; do not issue recovery while a healthy worker owns the job. After a stopped
worker's lease expires, restarting it performs reclaimed-owner recovery automatically.
Late observations remain unapplied audit records. A known settled choice must still be
within its original decision deadline before a new tool dispatch; expiry routes review.

Review the concrete protections in [specialist tests](../../tests/test_commerce_specialists.py),
[pure contract tests](../../tests/test_commerce_specialist_contracts.py),
[seven explicit reads](../../decisionops/commerce/adaptive_tools.py),
[observation validation](../../decisionops/commerce/adaptive_evidence.py),
[proposal safety](../../decisionops/commerce/adaptive_investigations.py),
[exact approval](../../decisionops/commerce/cases.py), and
[transactional execution](../../decisionops/commerce/execution.py).

The trace serializer allowlists event fields, suppresses raw reports/business rows and
credential/provider errors, and labels current versus invalid evidence. Correlation IDs
are audit links, never model features. Export is disabled. Langfuse is not installed;
a future optional adapter could export this redacted shape after explicit authorization.
Deep Agents is omitted because its planning/delegation layer would duplicate the typed
controller. LangGraph owns orchestration/checkpoint projection; PostgreSQL owns truth.

## Configuration, restart, reset and rollback

There is no public listener beyond loopback `8123`. Nginx serves the interface and
proxies `/api` to API:8000 on the internal project network. PostgreSQL:5432 is internal
only; there is no host DB port. API and workers use only fictional environment settings.
No OpenAI key is forwarded. Health: `/health`; inspect with `docker compose --env-file
/dev/null -p decisionops-multi-agent-demo -f compose.portfolio.yaml -f compose.multi-agent.yaml
ps --all` after exporting `COMMERCE_PORTFOLIO_PASSWORD` if invoking Compose directly.
The wrapper sets that variable from `COMMERCE_MULTI_AGENT_PASSWORD` automatically.

`stop` retains `decisionops-multi-agent-demo_portfolio_pgdata`; `start` resumes that
same data and does not erase compensation. An already executed order correctly cannot
receive another replacement. Preserve evidence before an operator-controlled reset:

```bash
# Deletes ONLY this fictional project's volume; not a routine restart.
COMMERCE_CONFIRM_RESET=decisionops-multi-agent-demo bash scripts/multi_agent_demo.sh reset
bash scripts/multi_agent_demo.sh start
```

Migration `0009` adds the specialist ledger/action partition. New source health requires
that schema; it does not automatically accept arbitrary newer revisions. Init migrates
only the new project. Never point it at the original migration-0004 database. To roll
back this optional demo, stop it and continue using the untouched prior portfolio release
in its existing worktree/project. Do not run an old API against the new0009 database or
blindly downgrade it: downgrade deliberately refuses remaining specialist jobs. No
original-runtime rollback/migration is necessary.

The local build uses existing locked app/browser base images and a pinned nginx/PG
image with networking disabled. A truly uncached host still needs those base images
built from the existing locked Dockerfiles (and approved dependency/image retrieval);
that fresh-host download/build has not been rehearsed here. No dependency upgrades,
hosting, HTTPS, public authentication hardening or production shop connector was added.

## Reproduce verification

Pure checks need only system Python. Database tests require the isolated test project,
not the staff demo or any original application database:

```bash
python3 -B -m unittest discover -s tests -p test_commerce_specialist_contracts.py -v
python3 -B -S scripts/commerce_ci_tests.py dependency-free
docker compose --env-file /dev/null -p decisionops-specialists-test -f compose.specialists-test.yaml up -d --pull never --wait
export COMMERCE_TEST_DATABASE_URL='postgresql+psycopg://specialists_test:fictional-specialists-test@127.0.0.1:55548/specialists_test'
../stage5-correction/.venv-decisions/bin/python -B scripts/commerce_ci_tests.py postgres
../stage5-correction/.venv-decisions/bin/python -B -m unittest discover -s tests -p test_commerce_staff_investigation.py -v
../stage5-correction/.venv-decisions/bin/python -B scripts/commerce_specialists_walkthrough.py --output runs/multi-agent/new-walkthrough
# Actual worker restart: fresh uncompensated demo; ~31 seconds waiting for old lease.
python3 -B scripts/commerce_specialists_restart.py --output runs/multi-agent/new-worker-restart
```

The sibling `.venv-decisions` is the existing optional locked environment used locally,
not a clean-checkout prerequisite: cached app/browser images contain the locked runtime.
The test database recipe is committed as `compose.specialists-test.yaml`; raw evidence
paths are local and indexed in the review bundle. Script preflight checks the test DB name/user/loopback port before any
migration. Each PostgreSQL test creates and drops its own schema. Full raw outputs retain
optional skip reasons; no skipped database test is counted as acceptance.

## Portfolio description

Built an opt-in fictional Commerce investigation using a typed LangGraph workflow and
two bounded, mocked tool-selecting specialists. PostgreSQL records scoped evidence,
leases and recovery. The mocked specialists demonstrated a successful proposal,
partial failure routed to review with peer evidence preserved, and restart without
specialist redispatch or a duplicate proposal. Exact approval and separate execution
were verified in the ordinary browser flow. Wrong-case evidence and actual conflicting
database rows were not tested through the final multi-agent join; execution after
restart was not verified. No live multi-agent quality, lower provider cost or production
deployment is claimed.
