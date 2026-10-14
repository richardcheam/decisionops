# Commerce learning notes

## 2026-10-12 — Eligibility facts and precedence

Correction: the initial eligibility table, function, explanation, and example
came from ChatGPT and were relayed by Richard. They were AI-assisted, not
independently authored by him. Richard later reported running the eligible
fixture demo; no owner-authored repository patch or test execution is recorded.

Agent review: correct for the stated True/False/None domain. The submitted
function silently accepted malformed values such as the string "false".
Agent demonstrated the gap with failing tests, then added an identity-based
guard raising ValueError. Invalid input is a programming/adapter error, not
business evidence. Equality-based membership would accidentally accept 0/1.

Agent executed the tests; Richard's later reported fixture run is recorded below.
See RUNBOOK.md for exact tests and examples. The function evaluates normalized
facts only; evidence authority, unsupported partial-case routing, configurable
policy evaluation, approval and execution remain future work.

Agent verification: all six focused tests passed. Full model-free suite ran
95 tests: 93 passed and two optional-package checks skipped. Documented examples
produced eligible_to_propose, needs_review, and ineligible with both lists
retained; malformed loss_confirmed raised ValueError. Whitespace check passed.

## Operating walkthrough agreement (supersedes exercises)

Richard requests implementation in coherent slices followed by operational
walkthroughs: exact commands, expected results, relevant failures, diagnosis,
small fixes, verification and safe undo. Participation is optional; no homework
or quizzes gate progress. Syntax explanations are supplied when relevant or
requested. Preserve the architecture, evaluation and spending constraints.

Record owner actions only when he reports them or they are directly observed;
agent verification is not evidence of independent owner execution.

Owner-reported action: Richard personally ran the previous eligible-fixture
demo. No terminal output was supplied; record execution as reported without
claiming an independently observed result. Other verification remains agent-executed.

## 2026-10-12 — Evidence intake and operational demo

Agent implemented and verified the next business-core slice: trusted fictional
read-tool attestations become eligibility facts with provenance and explicit
unresolved reasons. Existing eligibility function and tests were retained.
Unsupported scope routes to review. Store persistence and raw record adapters
remain future work; the demo performs no replacement or stock writes.

Agent demonstration: a stale carrier observation caused needs_review with
unknown loss_confirmed and reason stale. A separate simulated refreshed v2
result restored eligible_to_propose. Reusing the preserved stale copy safely
returned to review. Full walkthrough commands are in RUNBOOK.md.

Agent verification: 16 commerce tests passed; full model-free suite ran 105
tests, with 103 passing and two optional-package checks skipped. Exact runbook
startup, inspection, failure, refresh and undo commands completed successfully.
No dependencies installed, paid inference used, or AWS resources provisioned.
Beyond the reported eligible-fixture demo, no owner-run commands, patches or
verification have been reported for this slice.

Local demonstration artifacts:
`runs/commerce-walkthrough-addhux3t/`.
Exact runbook execution logs:
`runs/runbook-verification-0vpw_m_5/stdout.log` and `stderr.log`.
These ignored artifacts are local verification evidence, not checked-in
independent evaluation or business records.

## 2026-10-12 — PostgreSQL record-backed read tools

Agent implemented SQLAlchemy business records, frozen Alembic revision 0001,
deterministic scenario seeding, typed read tools, a read-only assessment CLI,
Compose PostgreSQL configuration and integration tests. Existing eligibility,
fixture mode and historical diagnostic code/tests are unchanged.

Agent verification: 15 integration tests passed against actual PostgreSQL
16.15; full suite ran 120 tests, 118 passed and two optional ML-package checks
skipped. Model-free discovery without the integration URL remains independent
of PostgreSQL and its packages. Existing 44 locked package versions remain
unchanged; seven packages were added to the lock and eight commerce-only
packages installed on this platform. No models installed or loaded.

Agent demonstrated eligible, stock-shortage, compensation, partial shipment,
partial compensation, incomplete history, unconfirmed tracking and policy
denial cases. Stock/resolution records stayed unchanged by assessment.
Stopping the native PostgreSQL instance caused exit 3, database_unavailable
and seven unknown facts. Restart restored eligibility with persistent records.
Evidence: runs/postgres-walkthrough-oruogxt0 and runs/postgres-outage-w6xvm9k5.

Docker was absent and sudo required owner authentication. Compose syntax and
official image digest were verified; container startup and named-volume
behaviour have not yet been executed. SQL testing used locally unpacked
PostgreSQL under ignored runs/pg-runtime on loopback port 55433, not a system
service. RUNBOOK.md distinguishes this verified fallback from Compose commands.

Owner participation: Richard reports personally running the earlier eligible
fixture demo. No owner command output, database setup, patches or integration
verification have been supplied. These PostgreSQL results are agent-executed.
No paid API calls or AWS provisioning occurred.

Final operational verification: native RUNBOOK startup, readiness, record
inspection, assessment and shutdown commands completed successfully. Logs are
in runs/native-runbook-verification-p2t6tptm. The temporary PostgreSQL process
is stopped with data retained. Compose runtime verification remains pending
owner Docker installation; no claim of a running Compose stack is made.

## Owner Docker setup and Compose diagnosis

Richard supplied terminal output for systemctl daemon-reload and a failed
enable/start attempt: docker.service did not exist at that point. He later
supplied successful docker info output showing engine/server 29.1.3 running,
and a failed docker compose version command reporting unknown command.
These are owner-executed checks with supplied output; intermediate installation
commands are not assumed to have been performed exactly as suggested.

Agent read-only diagnosis: docker.io is installed, docker-compose-v2 is not
installed, and /usr/libexec/docker/cli-plugins contains only docker-trust.
The docker group lists Richard, though the existing agent process still has
its older supplementary groups. Compose runtime verification remains pending
installation of the missing package.

## Owner PostgreSQL run and completed Compose verification

Richard supplied output for:
- docker ps showing a healthy PostgreSQL 16.15 container bound to loopback 55432.
- Exporting COMMERCE_DATABASE_URL and invoking Alembic upgrade head.
- Running the seed command, which reported seeded, commerce-demo-v1.
- Running the database-backed assessment for ORD-1042 / SHIP-1042 /
  shirt-blue-M:1. Supplied JSON at 2026-10-12T11:09:10.892891+00:00 confirms
  database available, read_only true, all seven facts true and eligible_to_propose.

These are owner-executed actions with supplied output. Migration invocation was
reported; the agent subsequently independently confirmed revision 0001. Do not
infer additional installation, testing or patching commands from this output.

Agent completed the previously pending Compose verification:
- Compose 2.40.3 and the digest-pinned healthy container were verified.
- Actual database revision is 0001; reseeding reported already_seeded.
- Full suite against Compose PostgreSQL: 120 tests, 118 passed, two optional
  ML-package checks skipped. Integration tests used isolated schemas.
- Stopping PostgreSQL caused exit 3 and all seven unknown/unavailable facts.
- Restart restored eligibility; every persisted business record was unchanged.
- Recreating the container preserved the named volume and all business records
  and migration revision. Container ID changed from 58bbed324a4c to b3f14b6f8c27.
- The container was left healthy and running; no volume deletion was performed.

Evidence: runs/compose-verification-sy7ham2y contains unavailable, recovered and
recreated assessments, database record snapshots, mounted-volume details and
container logs. Before/after record snapshot SHA-256:
3b5a95aa0081e4c3a9beb1b02c006492a6d892f50d2ad9e0d581488b535886d9.

The earlier Docker/Compose verification limitation is resolved. Native fallback
data is retained with its process stopped. No paid calls, AWS resources,
replacement execution, approval or stock reservation were added.

## 2026-10-13: durable investigations and immutable proposals

Richard asked the agent to continue autonomously because monitoring and repeated
questions were impractical. Operational walkthroughs replace mandatory coding
exercises; end-to-end explanation can happen later. Richard did not report new
terminal commands or patches in this slice. Everything below is agent-executed.

Concept: distinguish a saved historical assessment from a current business check.
An immutable proposal binds the exact request, policy and seven evidence versions.
A stock change can invalidate that binding even while enough stock remains.
Matching evidence never grants approval or execution permission.

Agent added pure proposal binding tests/module, append-only audit tables and
migration 0002, investigation persistence and CLI, PostgreSQL integration tests,
and an isolated success/drift/undo walkthrough. Existing assessment function,
evidence checks, fixtures, historical diagnostic code and ML dependencies remain.

Verified walkthrough artifacts: runs/proposal-walkthrough-oiwryd1c. Real CLI
subprocesses produced valid_for_review, requires_reinvestigation after on_hand
10 -> 9 (stock still sufficient), and valid_for_review after safe isolated undo.
Original saved assessment retained nine available units. The disposable schema
was removed and public demo data was not edited.

Applied upgrade head and Alembic check to the owner's running demo: revision
0002, no metadata drift. Saved investigation INV-ce62bafeacb44afa950ba5da94f00a32
returned needs_review with loss_confirmed unknown; its original carrier event
is now older than the policy's 24-hour limit. No proposal was created. This is
expected freshness behavior, not regression. Agent did not refresh its timestamp.

Artifacts: runs/investigation-verification-f7smzigz contains saved/inspected JSON,
bad-URL database_error exit-3 output and before/after original business snapshots.
All nine original business tables remained byte-equivalent after canonical
serialization (SHA256 a2075d2f392313212ee332c4d71e53cfa7456d191d2ec558b319bc9dd0e94803).
Only audit tables/revision were added to the public demo. No stock was reserved,
no compensation created, and no paid API, model download or AWS action occurred.

Reproduction: follow RUNBOOK.md's Durable investigations and proposals section.

Final agent verification: 138 total tests; PostgreSQL-enabled run 136 passed and
2 optional ML checks skipped; dependency-free run 109 passed and 29 optional
checks skipped. Six pure binding and twelve investigation integration tests
pass, including migration preservation, rollback, wrong-order/partial cases,
append-only guards, stale evidence and CLI errors. Self-review was performed;
no independent reviewer or owner-run verification is claimed. Changes remain
local and uncommitted; canonical checkout and PR #6 were not modified.

## 2026-10-13: explicit review, atomic replacement, concurrency and recovery

Richard asked the agent to continue unattended and repair failures until the tasks
succeeded. No new owner commands/patches were reported. All execution here is agent
work against fictional isolated schemas; no public demo approval was fabricated.

Agent added migration 0003, case lifecycle service, approval binding, atomic
replacement/reservation/compensation service, ledger reconciliation, CLI commands,
real concurrency tests and model-free CI configuration. Existing assessment and
fixture behavior remains. No new dependencies were needed.

Tests first failed on missing services/commands. Critical tests then passed. A
reconciliation regression test exposed that ledger rows alone did not prove the
inventory counter still covered holds: it failed ('verified' vs 'inconsistent'),
then passed after checking counters against aggregate reservations and case state.

Isolated CLI walkthrough artifacts: runs/execution-walkthrough-2xo_iib7.
It approved fictional data, changed stock, observed durable approval invalidation,
restored stock and demonstrated that the old operation still could not execute.
Reinvestigation/new review committed one replacement, one reservation and one
compensation. Duplicate execute/reconcile returned the same operation; on_hand10,
reserved2 (initial unrelated reserved1 plus replacement1). Schema safely removed.

Real two-connection tests passed for duplicate execution, two cases/one order,
two orders/last stock unit, and concurrent direct refunds. Mid-transaction failure
rolled back all effects. A real committed operation followed by simulated response
loss reconciled without duplicate reservation; this does not claim a real network
fault or external fulfilment test.

Applied 0003 to public demo and verified metadata consistency. Original business
values preserved; only compensation revision/operation reference fields added.
No public case approval, replacement or stock movement occurred.
Artifacts: runs/execution-migration-rl3k_6_2/before.json and after.json.
Operating reproduction is in RUNBOOK's Local cases, explicit review and approved
execution section. No paid inference, models, AWS or publication performed.
# Agent-executed operational walkthroughs (2026-10-13)

Richard authorized autonomous continuation and practical walkthroughs. No new
owner commands, patches or verification outputs were supplied in this session.
The initial eligibility table/function remain recorded as ChatGPT-assisted, and
Richard's previously reported fixture/database commands remain his actual work.

Agent implemented and verified durable jobs/lease fencing, PostgreSQL LangGraph
checkpoints, approval pause/resume and post-commit projection repair. Worker
walkthrough: runs/worker-walkthrough-f61rwuny (owned schemas removed). Full suite
at that stage: 161 tests, 159 passed, 2 optional-model skips. Agent then added
authenticated store-bound API tests: all 5 passed, including unavailable database,
strict inputs, auth/Origin checks and actual queued approval/execution.

Agent built pinned app/web images and started the local Compose stack. Readiness
returned ready/fictional_store_rules; PostgreSQL, API and web were healthy and
worker running. No model downloads, paid inference, AWS or publishing occurred.

Agent ran `scripts/commerce_backup_walkthrough.py`: PostgreSQL dump restored in a
new database; checked order/inventory/resolution/case/operation/job records matched;
migration 0004 and checkpoint tables present. Disposable restore database removed,
private backup retained in runs/backup-walkthrough-3okv1hii. This does not establish
off-host disaster recovery or independent owner operation.

Agent browser run passed 3 tests (runs/browser-walkthrough-nj9pw0dr): actionable
proxy failure with empty password, superseded approval rejected then fresh review
and one verified operation, incomplete compensation history unknown/no approval.
Agent inspected the screenshot. Temporary business/graph schemas were removed and
the original store restored. First failure revealed static Nginx upstream DNS;
agent patched resolver configuration and useful UI errors. A diagnostic exposed
the local password field value: agent rotated credentials and redacted artifacts;
failure/success clearing and diagnostic checks now protect that path. Richard did
not perform those patches or rotations.

Agent maintenance run (runs/release-walkthrough-49i3hol8): deliberately broken
startup exited 42, proxy unavailable, restored original image/config ready; real
database stop produced 503 and restart recovered with checked records unchanged.
This is same-code config rollback evidence, not old-release migration compatibility.

Agent added/froze 12 hand-inspected AI-authored evidence regressions, tested wrong
label failure and artifact overwrite protection, and ran the zero-inference report
at runs/commerce-regression-v1-report.json: 12 passed. This is not independent
evaluation, model comparison, or proof of owner mastery. Spending plan uses fetched
official pricing; it remains proposed/unapproved. No paid/provider or AWS action.

Final agent verification after the evaluation addition: 169 tests in 55.095s,
167 passed and 2 optional-model checks skipped. Dependency-free run: 169 tests in
9.067s, 112 passed and 57 dependency/database checks skipped. Alembic check found
no schema drift. Historical uv.lock package versions were unchanged; torch,
transformers, gliclass and laya are absent from the commerce virtual environment.
Compose and CI YAML validated locally; GitHub CI itself was not run. The rebuilt
application also ran the packaged dependency-free regression report successfully,
and readiness returned ready. Canonical main still has only the preserved untracked
handoff. No commits, pushes, PR updates or merges were executed. gh is unavailable,
so a fresh external PR #6 status is not claimed from this session.

Independent read-only reviewer inspected current files (not a committed diff),
found no critical/important defect in the loopback release and two minor races.
Agent reproduced and fixed both: concurrent second-order commit produced false
inconsistency on idempotent CLI retry; one-query stock/ledger snapshot fixed it
(18 execution tests passed). Held browser response showed inbox selection remained
enabled; agent disabled selection during action/confirmation. Reviewer inspected
the patches and confirmed both findings resolved. Review did not establish public
deployment, provider performance, privileged-admin protection or cloud readiness.
All execution/reproduction remains agent work; owner participation is still optional.

After the review patches, agent final full run: 170 tests in 49.329s, 168 passed,
2 optional-model checks skipped (runs/review-final-postgres-verification.log).
Final browser run: 4 passed in 13.2s, including held-response selection regression
(runs/browser-walkthrough-g07a0n5i); original store restored and test schemas removed.
Final API/web/PostgreSQL healthy, worker running, /health ready. No original public
replacement or job was created; public orders remain eight. No paid/cloud operation.
Final dependency-free check: 170 tests in 9.986s, 112 passed and 58 dependency/DB
checks skipped (runs/review-final-model-free-verification.log).

## Nontechnical staff interface clarification (2026-10-13)

Richard clarified the intended staff users do not code or use AI agents. Agent
simplified the UI: Start review automatically checks the order; product names,
plain next steps and different false/unknown explanations; technical identifiers,
hashes, raw records and events hidden under support details. Browser errors give
staff next steps rather than database/migration instructions. Approval and creation
remain explicit, exact-binding protections unchanged. Ask for help saves a note
and tells staff to share the order with a manager, without promising a notification.

Agent built the production web image (TypeScript/Vite passed) and ran five browser
tests: all passed in 18.7s, including automatic checks, exact review supersession,
unavailable-service guidance, incomplete history, stock shortage and selection
protection. Evidence: runs/browser-walkthrough-imfutl4d; agent inspected screenshot.
Original store restored; temporary schemas removed; public replacements still
zero. Two completed public investigation jobs and two cases dated before this
browser demo were observed and preserved; their author is not established from
user-supplied verification, so no owner execution is claimed. STAFF-GUIDE.md
contains browser-only instructions; RUNBOOK.md remains for the
operator. No owner commands or patches were reported for this slice. No claim of
real-user usability research; no paid APIs, dependencies or cloud resources added.

## Source review and reproducibility preparation (2026-10-13)

Richard authorized source commits, branch push and an unmerged PR. Agent inspected
all 80 changed/new source files and scanned candidates/staged content for private
operator credentials and credential patterns; none found. Private .env, dumps,
logs, build outputs and diagnostic artifacts remain excluded. Existing tracked
historical reports/model diagnostic files and original lock package versions and
sources remain unchanged. Runtime evidence is preserved locally, not published.

Agent created a clean source checkout with a fresh locked commerce-only virtual
environment and a new PostgreSQL volume on ports 55433/8081. No historical model
packages were installed. It built the pinned Python/Node containers with uv.lock
and npm ci, migrated through 0004, seeded eight fictional orders and reached
readiness. Agent verification: required PostgreSQL suite 56 passed, zero skipped;
full historical/commerce suite 170 collected, 168 passed, two optional model checks
skipped; dependency-free suite 170 collected, 112 passed, 58 dependency/database/
model checks explicitly skipped; frozen regression 12 passed, zero inference.

Fresh isolated browser workflow: six checks passed in 19.3s, zero skipped, flaky or
unexpected tests. Reviewer found a click-timeout cleanup gap in the test login
helper; agent reproduced it with a fictional secret, then moved clearing into
finally and verified the regression. Browser JSON results enforce execution of all
six checks. Required database CI fails on any skip, absent URL or import/setup
failure; success accounting counts actual successful tests, not arithmetic that
could turn setup errors into a negative count.

Agent verified backup restoration in a disposable database and same-code bad
configuration rollback (exit 42), explicit database-outage 503 and recovery with
records unchanged. One agent orchestration attempt overlapped the worker demo
with that deliberate outage and failed with database unavailability; preserved
logs identify the cause. Sequential rerun passed lease reclaim/fencing, persisted
review pause, rejection of fake resume, approved execution and completed-outcome
replay without another reservation. CI uses independent jobs and sequential
walkthroughs within each job. Review deployments stop without deleting their
persistent volume. Original working application/data were not switched or stopped.

Evidence: runs/source-review/ in the commerce worktree; the clean-checkout path
is recorded privately in runs/source-review/fresh-path.txt. Its ignored runs/
retains required-postgres-final.log, full-suite.log, worker-rerun.log,
browser-green.log, browser-walkthrough screenshots/JSON, backup and release proof.
No new owner commands, patches or independent verification were reported. Richard's
previous personally reported fixture and database setup/assessment remain the only
owner-attributed verification. Initial contract/function were ChatGPT-assisted.
Commits are created by the agent using the repository's configured Git identity;
that metadata is not evidence of Richard independently implementing or testing.
GitHub check status belongs to the PR, separately from these agent-local results.
No model provider, paid inference or AWS resource was added or used.

## External ChatGPT review (reported by Richard)

Richard reported that ChatGPT inspected selected source paths and independently
ran 25 dependency-free Commerce tests successfully. This was a selected-path
source review and an independent dependency-free test run, not a complete audit.
The PostgreSQL and browser verification cited by that review came from GitHub CI;
ChatGPT did not independently run those environments as part of this review.
These results are distinct from Codex's agent-executed verification and Richard's
personally reported commands. No additional Richard-run tests or patches are
claimed.

Codex subsequently updated the root README to lead with the working local Commerce
application, retained the detailed historical guide and its limitations, and
verified documentation links and formatting. This documentation patch and its
verification are agent-executed.

## Optional fake-provider and durable-budget milestone

Richard requested a separate branch from current origin/main, fake providers only,
no paid calls/cloud/language generation/supervisor, and preservation of the working
rules application. Codex created feat/commerce-fake-provider from af77267 and left
the original Commerce worktree's uncommitted technical report and other files intact.

Codex inspected the actual bundled assessment and placed opt-in routing after
investigate_case, not between individual reads. The provider recommendation is
consumed: present the exact eligible proposal for staff review or escalate the case.
All facts, allowed choices, approval and execution validation remain deterministic.
The browser/worker remain rules-only; this slice has an operator CLI integration.

Codex implemented typed bounded context/results, fake faults, exact simulated
pricing, immutable budget/request configuration and a PostgreSQL reservation ledger.
Concurrency checks reserve count and maximum cost before dispatch. Known bounded
usage settles; uncertainty keeps maximum cost and never automatically redispatches.
Provider wait holds no database transaction/locks. Results revalidate current state,
evidence versions and freshness, without overwriting newer approval/execution.
No real billing/model-performance claim comes from the simulated fixtures.

Independent reviewer found a business/budget/call lock inversion and prefixed IDs
exceeding a valid 128-character run bound. Codex reproduced both RED and patched
business-before-call locking and bounded hashed request IDs. Regression tests passed.
Reviewer rechecked and independently ran eight pure tests successfully, with no
remaining material issue; PostgreSQL/deployment results are Codex-executed, not the
reviewer's independent tests. The earlier external ChatGPT 25-test review remains a
separate historical attribution.

Codex local verification: provider PostgreSQL 24 passed; full suite 202 collected,
200 passed/two optional model checks skipped; required PostgreSQL 80 passed/zero skips.
Dependency-free: 120 passed, 82 explicitly skipped (database/optional dependencies).
Frozen evaluation: 12 passed, zero inference. Final review found no further material
gap in late known-usage settlement or frozen migration DDL; the reviewer did not
independently rerun PostgreSQL tests.
The simulated provider walkthrough routes real cases, retains 0.00260000 unknown
simulated USD, denies exhausted calls and recovers with dispatch_count 1; exact staff
approval then creates one replacement/reservation even on retry. Initial walkthrough
had an incorrect existing CLI flag (--content-hash versus --hash); corrected and
rerun successfully. Contract tests are dependency-free. Browser six passed; original
execution/worker recovery, isolated backup restore, exit 42 config rollback and DB
outage/recovery passed. Evidence is in ignored runs/provider and walkthrough folders.

Testing used a separate project/volume, ports 55434/8082 and app/web image tags. The
original app container IDs remain unchanged and its store remains revision 0004.
This branch's additive migration 0005 has frozen DDL and matching health/backup
expectations. No dependency/lock changes, models, paid inference or AWS resources.
No new Richard-run commands, patches or tests were reported; no owner mastery is
claimed. All implementation/publication/verification not explicitly reviewer-run
above is agent-executed. Operational participation remains optional, not homework.


## External provider review and integration (reported by Richard)

Richard reported that ChatGPT inspected the provider, routing and budget source
and independently ran eight pure provider tests successfully. Database/browser
verification cited by that external review came from GitHub CI; ChatGPT did not
independently run those environments. This review is separate from Codex's
agent-executed verification and the independent implementation reviewer above.
No new Richard-run commands or tests are claimed.

Integration does not deploy this source into the original running store. Its
revision-0004 database, application containers and persistent volume stay intact.
Using the provider functionality requires Alembic migration 0005 in the intended
environment with the matching application release; follow RUNBOOK's isolated
provider setup before experimenting. Do not automatically migrate or restart the
original stack merely because the PR is merged.

## Optional cached Commerce local-provider milestone (2026-10-14)

Richard requested optional Laya/GLiClass operator adapters and an offline comparison,
not real API/cloud/supervisor work. Codex created feat/commerce-local-providers from
current origin/main e1a7f67287c32d65538faa769e4b7876823557a6. Original containers,
migration-0004 volume, unrelated draft/worktrees and historical reports are preserved.

Codex reused the committed cached checkpoint resolver and corrected flat-label
GLiClassActionRanker/LayaActionAgent. Offline flags precede library imports; CPU,
four threads, batch1, one family per bounded process; loading counted in deadline.
Models see normalized facts/allowed choices/task, never IDs/hashes/evaluator labels.
One-choice cases force review with no dispatch. Typed results record native
uncalibrated scores, measured phases/RSS, model pin and validation/routing effects;
local budgets have explicit zero API charge and null token usage. Existing fake
simulated budgets/tests remain distinct and unchanged in meaning.

Agent actually ran both cached models through direct probes and operator CLI in
an owned schema on a separate PostgreSQL project/volume at 55435. Both requested
review for all-true evidence instead of the reference rules' present choice. Actual
cases became escalated; zero approval/operations and unchanged stock were verified.
Unknown history forced review without model loading. There is only one meaningful
scored vector; repeats are execution checks, not extra model-quality examples.
No held-out generalisation/business-value claim follows. First/final comparison
results are committed under reports/commerce-local-providers-20261014; probe/CLI
trace artifacts remain ignored under runs. No prompt tuning followed disagreement.

Independent read-only reviewer found exited-parent descendant cleanup and failed-
inference timing attribution bugs. Codex reproduced both RED and patched them.
Reviewer independently ran nine local pure and eight existing provider tests after
cleanup repair, and verified separate failure timing using model-free mocks. No
models or PostgreSQL checks were independently run by that reviewer. This is
separate from Richard's previously reported external ChatGPT provider review.

Agent's failure walkthrough first exposed datetime serialization in a saved trace;
using the existing canonical serializer fixed it. Missing optional dependencies,
request exhaustion and slow-child cleanup/recovery were then demonstrated without
model loading. Same-run recovery preserved dispatch_count=1; no operations/API
charges. Native real comparison and model-free test doubles are labelled separately.
No new Richard-run commands, patches or model verification have been reported.
All implementation/model/database/CLI verification in this milestone is agent-
executed unless expressly attributed to the reviewer above. No dependency/lock
upgrades, checkpoint downloads, OpenAI calls or AWS provisioning occurred.

A verification run overlapped Codex's typed-rules boundary edit and mixed old
imported modules with new source, so that result was discarded. Codex stopped
source edits and reran the final checks in fresh processes. This was agent work,
not a store runtime failure; the running application was unaffected.

Final fresh-process agent verification: 217 collected, 215 passed/two optional
model checks skipped. Required PostgreSQL: 84 passed, zero skips, including 28
provider database tests. Dependency-free: 131 passed, 86 explicitly skipped
database/optional checks. Eleven local pure contracts and all eight existing fake
pure tests pass. Frozen evaluation: 12 passed, zero inference. Browser/backup/worker
checks are performed by model-free GitHub CI on the published branch, separately
from the actual cached local model comparison. No owner-run verification is claimed.

## PR #9 checkpoint-provenance and pipe-output review fixes

Richard requested both unresolved P2 findings be fixed on the existing branch,
with no model runs/downloads/upgrades/OpenAI/AWS. Codex reproduced pin hydration
failure and stdout/stderr overflows that formerly waited for the deadline.
Historical deserialization now validates recorded structure independently of new
request/current-pin policy; old reserved model calls receive explicit no-dispatch
fallback, while settled/in-flight/forced history remains readable without pins.

Codex added concurrent binary draining with per-stream byte caps and bounded
prefix diagnostics, preserving deadlines, group termination and direct-child reap.
Overflow regressions demonstrate detection during consumption (cap+1 byte), not
post-exit inspection, and database records show fallback without duplicate dispatch.

Independent read-only reviewer ran 16 local pure tests and eight existing provider
contracts, without models or PostgreSQL. It found an additional pin-file race in
worker-to-loader startup. Codex added RED-to-GREEN stub regressions and passed the
admitted revision directly to cached loaders; their default historical behavior is
unchanged. Historical model reports/negative results remain unmodified, not rerun.
All patch/test/publication work here is agent-executed. No new Richard-run commands
or verification are claimed; prior external review attribution remains separate.

Final P2 patch verification (agent-executed, fresh processes): 20 local pure tests;
32 provider PostgreSQL tests within the required suite of 88 passed/zero skips.
Full regression: 230 collected, 228 passed/two optional model checks skipped.
Dependency-free: 140 passed, 90 explicitly reported database/optional skips.
Frozen evaluation: 12 passed with zero inference. Model-free failure and preserved
fake walkthroughs passed. No actual model comparison was rerun for these fixes.

## External ChatGPT verification of PR #9 fixes (reported by Richard)

Richard reported that ChatGPT reviewed the fixes' source and independently passed
20 model-free adapter tests. PostgreSQL/browser verification cited by that review
came from GitHub CI; ChatGPT did not independently run those environments. This
is separate from Codex's agent-executed regression checks and the independent
implementation reviewers above. No new Richard-run commands/tests are claimed.

Source integration leaves the original running migration-0004 application,
containers and persistent volume intact. Optional provider functionality requires
migration 0005 and the matching source in the intended environment; merging does
not automatically migrate or restart the original stack. Historical comparison
reports/negative results remain preserved, with no model reruns during integration.
