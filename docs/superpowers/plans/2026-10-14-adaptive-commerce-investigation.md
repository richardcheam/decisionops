# Adaptive Commerce investigation — staged implementation plan

Status: Stage 1 authorized and implemented on the isolated design branch; Stage 2 accepted and separately preserved on feat/commerce-adaptive-core; Stage 3 is implemented for review; Stages 4–5 remain proposed. See the [resolved Stage 1 contract](../specs/2026-10-14-adaptive-commerce-stage1-contract.md).

**Goal:** an optional, durable, read-only investigation loop with explicit observations and deterministic terminal validation.

**Architecture:** PostgreSQL authoritative runs/steps; a separate CLI/queue/LangGraph projection; shared validated policy actions; legacy bundled application unchanged.

**Tech stack:** existing Python, SQLAlchemy/Alembic, PostgreSQL, LangGraph and optional cached CPU adapters. No new dependency is presumed necessary.

**Spec:** [design and decisions](../specs/2026-10-14-adaptive-commerce-investigation.md).

**Global constraints:** preserve original migration-0004 stack/volume and historical reports; separate demo database; rules default; no paid calls/downloads/AWS; optional model-free CI; no inference inside database transactions. No mandatory learner exercises.

**Review focus:** visibility boundaries, scope precedence, proposal binding compatibility, immutable recovery, fencing and bounded resource use.

## Stage 1 — explicit reads and evidence contract, no policies/models

- [x] Resolve tool projection/dependency schemas and authoritative-record rules from the design. Inventory every supporting query; decide shared source-version contract before changing proposal hashes.
- [x] Add focused tool/result contracts (proposed `decisionops/commerce/adaptive_tools.py`); add projected derivation alongside the untouched legacy `read_tools.py`, guarded by complete-state parity tests.
- [x] Implement seven explicit reads and active-observation assembly. Add contract versions only where necessary in `evidence.py` / `proposals.py`; historical version-1 documents retain their validator.
- [x] Add model-free tests (proposed `tests/test_commerce_adaptive_tools.py`) for visibility, missing-versus-false, dependencies, conflicting records, freshness and supersession.
- [x] Add PostgreSQL tests for wrong-order/variant binding, incomplete compensation, supported/unsupported quantities and bundled-versus-complete-adaptive parity. Spy on query projections: fulfilment cannot disclose carrier facts; no inventory/history query before its tool selection.

Acceptance: every observation has explicit provenance; complete supported assessments agree with the bundled path; partial/unknown evidence cannot propose; historical diagnostics/tests unchanged. No migration was added. PostgreSQL acceptance is executed against a verified isolated test database and reported separately; SQLite parity alone is not PostgreSQL verification.

## Stage 2 — durable model-free execution and terminal publication

- [x] Add migration after current head for runs, immutable steps/observations, active pointers, capped counters and case revision. Implement the already-resolved server-side case-revision trigger/coverage matrix in the Stage 1 contract; include provider and execution mutations, direct SQL and same-generation changes.
- [x] Add proposed `adaptive_investigations.py` with start, validate/read/append, active-context assembly and terminal publication. Transactions are short; business records remain read-only.
- [x] Implement fixed-order, cue-rules and adversarial fake policies using one typed action contract (proposed `adaptive_policies.py`). Keep existing `providers.py` two-choice routing API compatible.
- [x] Add planned operator entry point (`python -m decisionops.commerce.adaptive_demo`), explicit mode only; do not wire browser/API defaults to it.
- [x] Test proposal prerequisites, early blocker with unknown disclosure, unsupported-scope review, exhaustion/rejection/fallback caps, expiry, same-generation staff mutation, exact approval and execution regressions.
- [x] Demonstrate success and injected failure in an isolated seeded database; record commands and evidence in RUNBOOK and LEARNING with accurate agent/Richard attribution.

Acceptance: a working model-free adaptive run selects actual tools and persists their evidence; no unrequested check becomes a policy observation; approval/transaction/reconciliation tests pass. Early reports are distinguishable from complete assessments.

## Stage 3 — jobs, checkpoints and durable recommendation accounting

- [x] Extend `jobs.py` with an explicitly partitioned adaptive action/claim filter and token-fenced renewal. Existing worker continues claiming legacy actions only.
- [x] Add separate proposed `adaptive_workflow.py` graph and thread namespace; reconstruct from durable step IDs rather than replaying effects. Add operator inspect/resume/recover commands.
- [x] Generalize accounting through task-aware contracts/additive `adaptive_accounting.py` tables and schema; do not relax two-choice validation for legacy calls. Reserve before dispatch, retain uncertain reservations, and never auto-redispatch uncertainty.
- [x] Test races, expired leases, heartbeat loss, restart at each persistence boundary, stale result rejection, checkpoint loss, cancellation, read retry provenance and concurrent staff review/execution.
- [x] Extend model-free CI and fake worker tests without optional model imports; local dependency-free and required PostgreSQL profiles execute separately.
- [x] Obtain executed dependency-free/PostgreSQL GitHub CI: public source mirror 0662d051e6be5575848771ab44c4e2bbe981df18, run 38592061880; 162 passed/171 explicit optional skips and 169 passed/zero skips respectively. Runtime/test/workflow files match the local tree exactly; complete documentation remains in the local review bundle. Browser remains unexecuted.

Acceptance: crash/restart cannot reset limits, duplicate a recommendation, overwrite staff changes or publish with a stale token. No inference transaction holds business locks. Required database tests actually execute in CI.

## Stage 4 — bounded reusable local sessions, still opt-in CLI

- [x] Freeze the framed session protocol and its total/per-frame caps. Extend `worker_pipes.py` or introduce a dedicated session helper; preserve one-shot adapter behavior.
- [x] Add `session_worker.py` and reusable local adapter code while preserving `local_model_worker.py` to load one pinned family once per run, accept serialized Commerce action requests, and return native scores without incident labels. Historical request deserialization remains independent of current pins.
- [x] Add host-local family ownership, bounded preload/decision/run deadlines, cancellation/lease-loss cleanup and measured load/inference/memory phases. No invented tokens/costs.
- [x] Model-free child-process tests: stdout/stderr/both overflow during draining; malformed/truncated/wrong-correlation frames; descendant pipes; preload/decision deadlines; cancellation; restart; forced actions skip loading.
- [x] Add fake adapter contract tests to CI. Executed source SHA 57a6baa048c64796f4534c26b25b9d359a7b1eec: dependency-free 176 passed/191 explicit skips and PostgreSQL 189 passed/zero skips, run 38624510630. No checkpoint loading or downloads in routine jobs.

Acceptance: one child handles multiple decisions with one reported load phase; total loading cost is visible; cleanup is bounded; policy input excludes IDs/hashes/unrequested evidence. Both legacy routing task and fake-provider tests pass.

## Stage 5 — frozen offline integration comparison and operational handoff

- [x] Freeze records/reports/expected admissible outcomes independently of provider behavior, following the scenario matrix. Enumerate distinct meaningful decision inputs before interpreting results.
- [ ] First execute fixed order/cue rules/fakes; only after correctness gates, run bounded cached Laya and GLiClass sequentially on identical permitted inputs in the isolated environment.
- [ ] Save raw traces, native-score meanings, forced/inferred counts, correct outcomes/reviews/tool coverage/query groups/calls/full latency/memory and negative results. Label agreement as reference-policy integration, not a model-quality/business-value benchmark.
- [ ] Update `docs/commerce/RUNBOOK.md`, README/operator review guidance and accurate LEARNING attribution. Include startup/readiness/migration/seed, mode selection, step inspection, failed investigation/recovery, shutdown and safe rollback commands proven in that environment.
- [ ] Run existing dependency-free, PostgreSQL and browser regressions and viewer verification. Browser/API defaults remain unchanged; optional model tests stay optional.

Acceptance: operator can inspect why a tool was selected, diagnose an unknown/timeout, recover without duplicate dispatch and identify deterministic approval/execution boundaries. Historical reports and the original stack are untouched.

## Review gates and execution order

Stages 1–3, including the Stage 3 correction, are accepted. Stage 4 is implemented for review; Stage 5 remains pending. Settle projections/hash version before Stage 1 completion; scope/publication behavior before Stage 2; case-revision coverage is resolved in Stage 1 before Stage 2 starts; queue partition/uncertainty handling before Stage 3; protocol/caps before Stage 4. Model comparison follows model-free gates, never substitutes for them. Each stage is a coherent implementation/verification slice with a concise operational walkthrough; participation is optional.

The Stage 1 library modules exist. Stage 2 modules and opt-in CLI now exist; Stage 3 jobs/accounting/projection and operator interfaces now exist; Stage 4 reusable sessions are implemented for review; Stage 5 remains proposed. Final reproduction commands will be recorded after they actually work; no fresh-environment or model-performance claim is made by this plan.

Stage 2 decisions: [durable contract and publication bridge](../specs/2026-10-14-adaptive-commerce-stage2-contract.md). Stop at its review gate.

Stage 3 resolved contracts and recovery rulings: [job/accounting contract](../specs/2026-10-14-adaptive-commerce-stage3-contract.md). CI results are recorded separately for the actual review SHA; do not infer passes from configured jobs. Stage 3 accepted; its snapshot remains separate.

Stage 4 resolved [session/resource contract](../specs/2026-10-14-adaptive-commerce-stage4-contract.md) was frozen before implementation. Actual verification is recorded in docs/commerce/STAGE4-REVIEW.md. Stop at Stage 4 review; Stage 5 is not authorized by this implementation.

Stage5 attempted on feat/commerce-adaptive-evaluation from accepted d3c3896.
57 model-free pairs passed stricter adjudication with9 additional retained-v1
verifications. Native pilots/comparison/replay remain UNEXECUTED: isolated head0008
API health requires0005,6 browser failures, and required PostgreSQL profile red.
Dependency-free checks and viewer export executed. CI publication was rejected;
no current-source CI result. See docs/commerce/STAGE5-REVIEW.md and local bundle.
Do not mark Stage5 complete or enable models/defaults. Preserve the frozen matrix
and negative results when the separately reviewed blockers are resolved.
