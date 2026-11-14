# Local Commerce handoff — 2026-10-16

**Later local milestone, 2026-11-12:** [the staff assistant guide](STAFF-ASSISTANT.md)
describes the new web report/progress/evidence action on feat/commerce-staff-investigation.
The [repeatability report](../../reports/commerce-staff-assistant-repeatability-20261112/README.md) separates rules/mocked browser evidence and the [pilot handoff](PILOT-HANDOFF.md) defines the remaining shop boundary. The remainder preserves the 1a0e685 checkpoint history. Original live traces remain
unchanged; the new browser flow was tested with rules and mocked Decisions only.

Start with the [actual Decisions walkthrough](DECISIONS-LIVE-WALKTHROUGH.md). It
shows each choice, returned evidence, native usage/cost and the final review. Read
it before starting infrastructure or authorizing further development.

Historical implementation branch: `feat/commerce-openai-investigation` at 1a0e685; the
current local branch is `feat/commerce-staff-investigation`, retained at
`runs/worktrees/stage5-correction`. The canonical checkout remains on its older
`main`; no merge, publication, deployment or release was performed. Do not assume
canonical main contains this local implementation.

## What exists and what was demonstrated

The browser staff workflow uses deterministic rules, fictional records, exact human
approval, transactional replacement/stock reservation, revalidation and recovery.
Rules remain the default in browser/API/ordinary workers. Routine tests and CI need
no paid inference and import no optional model libraries.

Adaptive investigation splits evidence into seven explicit projected read tools.
PostgreSQL stores durable steps, evidence, revisions, budgets and ownership; graph
checkpoints are a recoverable projection, never business authority. Optional operator
adapters use bounded context and validated allowed actions outside database locks.
The actual Decisions insertion point is `adaptive_runner.tick` ->
`DecisionsAdapter` in `openai_decisions.py` -> official SDK
`client.decisions.with_raw_response.create` -> POST /v1/decisions. The model chooses;
read tools establish facts; deterministic services gate proposals and actions.

Richard personally ran two bounded, single-use fictional API investigations from his
SSH terminal. Both traces are retained unchanged in the indexed archive:

| Run | Observed outcome | Native usage | Cost estimate |
|---|---|---|---|
| Historical nano Responses | Two reads, then review; five conditions unknown | 934 input, 931 output; reasoning split not retained | $0.00041910 |
| Actual gpt-6-luna Decisions | Six reads, then review; inventory unread | 3,628 input, zero output/reasoning | $0.00036280 |

Neither produced a proposal. Both are negative proposal-completion results despite
safe integration behavior. Confidence never became evidence or approval. No live
approval, replacement execution, stock reservation or reconciliation business path
was exercised by these API runs; model-free regressions cover those paths separately.
The agent performed subsequent file-only hash/binding/accounting verification.

The cached Stage 5 pilot remains stopped with `resource_monitor_thread_error`.
Laya lacked the required available RAM and did no dispatch; the GLiClass pilot's
native choices/early review and negative monitor outcome are preserved. The ledger's
attempts, family clocks, expiry and stop state were not reset. No retry or full local
model comparison is authorized. **Stage 5 and deployment are not complete.**

## Starting the rules application safely

The original migration-0004 application, containers, credentials and volume were
preserved. This cleanup did not restart/migrate/reseed them. Do not run this branch's
init against that volume: current-source startup applies schema 0008.

For a deliberately new, isolated rules-only stack, these are the documented commands
(**not executed during wrapup**). Run from the implementation checkout, not canonical
main. Unique project, ports, image tags and volume keep the original stack separate:

```bash
cd <historical-checkout>
export COMPOSE_PROJECT_NAME=decisionops-commerce-wrapup
export COMMERCE_POSTGRES_PORT=55447
export COMMERCE_WEB_PORT=8087
export COMMERCE_ORIGINS=http://127.0.0.1:8087,http://localhost:8087
export COMMERCE_APP_IMAGE=decisionops-commerce-app:wrapup-rules
export COMMERCE_WEB_IMAGE=decisionops-commerce-web:wrapup-rules
python3 -B scripts/commerce_local_setup.py
docker compose --profile app build
docker compose --profile app up -d --wait
curl --fail http://127.0.0.1:8087/health
```

Open http://127.0.0.1:8087. Private .env supplies staff credentials and is ignored;
read it locally, never paste it into reports. Expected topology: browser -> loopback
web:8087 -> API:8000 on the private Compose network; API/worker -> postgres:5432.
PostgreSQL is exposed only on loopback 55447. The default network/volume belong to
`decisionops-commerce-wrapup`, not the original project. Setup creates fictional
records; no external shipping/payment/refund integrations exist.

Inspect and stop **only that same isolated project**, retaining its volume:

```bash
docker compose -p decisionops-commerce-wrapup --profile app ps
docker compose -p decisionops-commerce-wrapup --profile app logs --tail=100 api worker
docker compose -p decisionops-commerce-wrapup --profile app down
```

Use the same exported port/image settings. `down` stops/removes containers/network;
it does not delete the named data volume. Do not use `down -v` or change the original
project's data. Build/start/stop instructions are documentation, not wrapup verification.

## Paid API boundary and recovery

Live paid investigations are explicitly manual-only, one per new **RUN LIVE TEST**.
Credentials, startup, CI, tests or background workers never grant permission. The
$0.03 Decisions configuration is recorded in `examples/api-decisions-proposed.json`;
no new call is authorized by this handoff. Its previous single-use markers remain
consumed. Never reset markers, create a replacement budget, automatically resume an
uncertain call, switch models or raise caps to force completion.

Useful operator scripts now live in `scripts/commerce_decisions_operator/`; their
reviewed predecessor is archived. They retain separate preparation, paid step and
evidence-before-cleanup. They are not startup hooks. The existing configuration/run
is consumed: another authorized experiment needs an explicit plan and new command,
not deletion of retained guards. See [the API contract](OPENAI-DECISIONS.md).

## Checks and provenance

Latest API/Decisions checks were agent-executed locally on a verified disposable
PostgreSQL instance, subsequently removed: 10 Decisions SDK mocks, 18 Decisions
PostgreSQL/accounting/CLI, 11 historical Responses SDK, 9 Responses accounting and
194 required PostgreSQL passes; zero skips in those groups. Dependency-free profile:
190 passes, 252 explicit optional skips (442 collected). No live transport in CI/tests.

Historical publication CI for `699c94598a8da196ea2446e72f0c7ab992a83337` succeeded and
its raw logs/source-equivalence receipts are archived. It is **not current-API CI**.
No CI/browser or live-model verification was executed for the final local API source.
Accepted earlier-stage CI/supervisor scopes remain as recorded; do not generalize
mocked or archive-integrity review into independent PostgreSQL execution.

Wrapup reuses those results after checking implementation/lock hashes. It runs only
archive/bundle verification, source/credential/reference checks, shell syntax, and
file-only reconciliation for relocated scripts. No broad suite, model, API or runtime
operation is repeated solely to clean files.

## Evidence and remaining work

[Evidence index](../../reports/commerce-evidence/INDEX.md) maps original paths to the
private external archive, hashes, accepted snapshots, failures and both live traces.
[Runbook](RUNBOOK.md) remains the detailed historical/operator reference; historical
`runs/...` paths now resolve under the index's archived worktree root unless explicitly
marked as retained dispatch guards or newly generated output.

Remaining work includes explaining/fixing early-review behavior only after discussion,
resolving the cached monitor failure before any separately authorized native work,
current-source CI/browser review, production identity/TLS/backup/deployment planning
and actual deployment authorization. There is no supervisor, language-generation
feature or production readiness claim. Stop here for Richard's learning walkthrough.
