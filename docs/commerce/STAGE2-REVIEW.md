# Stage 2 review gate — durable model-free investigation

Branch: `feat/commerce-adaptive-core`. HEAD/accepted Stage 1 snapshot:
`fde904f627df2cf7301089059e700f691cdbd5d5`. Fetched origin/main baseline:
`b27e2d7cda764ef6e52f99eff3e5a9f30a45d0f5`. Stage 2 remains an uncommitted,
separate diff. No Stage 3 changes or supervisor acceptance claim.

Contract: [publication, persistence and deadlines](../superpowers/specs/2026-10-14-adaptive-commerce-stage2-contract.md).
Operations: [RUNBOOK](RUNBOOK.md#stage-2-opt-in-durable-model-free-investigation).

## Review map

- Migration/revision: `migrations/versions/0006_adaptive_core.py`, `schema.py`;
  core tests for no-op SQL, provider/execution mutations, immutable bindings,
  resulting start revision, revoked approval and concurrent starts.
- Policy privacy/actions: `adaptive_policies.py`, `request_for`, `allowed`;
  pure policy tests, incomplete-proposal safety exclusion, cue/fake actual effects.
- Bridge: `safety_check`/`publish`; drift refresh, expiry and stale publication
  tests. Private v2 recheck confirms contents/dependencies before constructing
  separate unchanged v1 attestation. It cannot fill policy collection gaps.
- Durable steps/recovery: `advance`, `recover`, `snapshot`; concurrent same-context
  advancement, late terminal discard and newer-pending-token tests. Immutable
  history remains distinct from active pointers and invalidation events.
- Bounded progress: per-tool SQL counter and run caps; tests for 12 reads,
  16 rejected decisions, two failures/tool, UTF-8 report/projection caps, real
  business-table and case-row lock timeouts. Expired audit cleanup is separately
  bounded and cannot dispatch new reads.
- Blocker/scope precedence: early payment blocker with unread scope remains
  needs_review; supported stock blocker becomes blocked; partial compensation
  remains review. Terminal reports disclose unknown/unread/unresolved scope.
- Legacy guarantees: successful adaptive proposal uses existing exact approval,
  execution revalidation/reservation/duplicate prevention/reconciliation services.
  Required PostgreSQL profile also runs legacy API/job/provider regressions.

## Agent-executed verification

Working directory: `/home/richard/projects/decisionops/runs/worktrees/adaptive-core`.
Existing interpreter, no dependency changes:
`/home/richard/projects/decisionops/runs/worktrees/local-providers/.venv/bin/python`.
Set COMMERCE_TEST_DATABASE_URL to
`postgresql+psycopg://commerce_stage2:stage2-fictional-only@127.0.0.1:55437/commerce_stage2_test`.
This fictional credential belongs only to the disposable test container.

```bash
python3 -B -S scripts/commerce_ci_tests.py dependency-free
/home/richard/projects/decisionops/runs/worktrees/local-providers/.venv/bin/python -B scripts/commerce_ci_tests.py postgres
/home/richard/projects/decisionops/runs/worktrees/local-providers/.venv/bin/python -B -m unittest discover -s tests
/home/richard/projects/decisionops/runs/worktrees/local-providers/.venv/bin/python -B -m decisionops.commerce.evaluation
/home/richard/projects/decisionops/runs/worktrees/local-providers/.venv/bin/python -B scripts/commerce_adaptive_walkthrough.py
git diff --check
```

Results: dependency-free 303 collected, 160 passed, 143 explicitly skipped
(database/SQLAlchemy integration and two optional Laya-package checks).
Required PostgreSQL 141 passed, zero failures/errors/skips, metadata migration
check reports no new upgrade operations. Full suite 303 collected, 301 passed,
two optional Laya-package checks skipped. Frozen legacy cases 12 passed/zero
failed. No model inference or checkpoint loading in these checks.

Full logs are under `runs/stage2-verification/`; complete durable CLI traces and
exact subprocess commands are under `runs/stage2-walkthrough-ek594la7/`.
Success: proposed, seven reads/eight decisions, staff approval still required.
Injected manifest SQL division error: two unavailable attempts/three decisions,
review with seven unknown requirements; no invented false fact. Each inspect was
performed in a fresh CLI process, demonstrating durable state. Disposable schema
was dropped by the demo, after trace export.

Source-only agent review found one deadline gap. Added regression reproduced
5.014 seconds of case-lock waiting; patch now passes a <1.5-second bound for a
0.5-second run without dispatch. Review of the correction found no remaining
material issue; this is agent source review, not supervisor verification.

Database identity, loopback port and tmpfs storage were verified before migrations.
Only owned test/demo schemas were migrated to 0006/seeded. The owned container
was stopped/removed after checks. Original four container IDs and named volume
remain present, unchanged; no original-runtime migration/restart/reseed occurred.
CI and browser checks were not executed. No Richard-executed commands were added.
Supervisor Stage 1 verification remains limited to archive integrity/reconstruction,
16 pure observations and 12 frozen cases.

## Remaining limits

Opt-in CLI only; no adaptive queues, graph, lease renewal, providers or model
sessions. Admission/header lookup and historical/expired cleanup have separate
five-second statement bounds; active work uses remaining-deadline timeouts.
Connection failure can prevent audit persistence; inspect and explicitly recover
once availability returns, never auto-redispatch. A discarded late result may
have an audit sequence beyond the terminal context, without rewriting that run.
Migration downgrade is destructive and not recovery. Stage 2 awaits supervisor
review; Stage 3 remains pending.


## Targeted terminal/admission correction (2026-10-14)

The earlier results above describe the initial Stage 2 review snapshot, preserved
unchanged as `runs/decisionops-commerce-stage2-review.zip` (SHA-256
`7d848d0629bd30c6365b2fbf6158ea7d87376c28625c4c00eb59c95196bd8509`).
This correction changes only adaptive_investigations.py, its core tests, the
resolved Stage 2 contract and this report; no migrations or defaults changed.

Final blocker publication now confirms current bound false evidence and, where
needed to justify blocked, already-collected supported-scope evidence. The private
query set is the blocker/scope dependency closure, using projected row locks and
remaining-deadline timeouts. No unread conditions are fetched or new private
observations persisted. Freshness is checked after validation/lock waits. Changed
or expired bindings create safety_drift invalidation; explicit refresh must fit
existing caps, otherwise review. Zero current blockers cannot produce an observed
blocker or blocked. Unresolved/unsupported scope continues to force needs_review.

Post-lock result admission now also checks fresh database time. Expired successful
results are unapplied audit records and do not update active pointers. Cleanup is
claim-fenced: an old result cannot clear a newer pending token; owning results or
explicit recovery perform bounded expiry cleanup. No reset, extension or redispatch.

### Actual correction verification — agent-executed

Verified isolated URL/database identity: host 127.0.0.1, port 55437,
commerce_stage2_test/user commerce_stage2/server port 5432. The owned Docker
container used the same cached image digest, 512MiB tmpfs, and no volume. Every
PostgreSQL test created/migrated/seeded and removed its own schema. No original
application/database/container/volume operation was performed.

From adaptive-core, exact test commands:

```bash
export COMMERCE_TEST_DATABASE_URL='postgresql+psycopg://commerce_stage2:stage2-fictional-only@127.0.0.1:55437/commerce_stage2_test'
/home/richard/projects/decisionops/runs/worktrees/local-providers/.venv/bin/python -B -m unittest discover -s tests -p test_commerce_adaptive_core.py -v
/home/richard/projects/decisionops/runs/worktrees/local-providers/.venv/bin/python -B scripts/commerce_ci_tests.py postgres
git diff --check
```

Focused core: 28 passed, no failures/errors/skips. Required PostgreSQL: 148
collected, 148 passed, zero failures/errors/skips; no new metadata upgrade
operations detected. `git diff --check` passed. Seven new regressions cover:
expiry between choice and finish; expiry while private validation waits on an
inventory row lock; blocker source drift without case changes with SQL spying
(no policy/shipment/inventory/history reads for an early payment blocker);
supported-scope drift and unsupported-scope review; budget-exhausted drift;
successful late result retained unapplied with no active pointer; expired old
result preserving a newer pending token. Existing terminal, revision, approval,
execution, recovery and provider-routing PostgreSQL regressions also passed.

The initial five new tests failed against the prior implementation (26 tests,
five failures). The additional expired-newer-token regression then exposed old
cleanup clearing a newer claim (28 tests, one failure), and passed after fencing.
Full outputs: `runs/stage2-correction/red.log`, `token-red.log`, `focused.log`,
`postgres-required.log`. These are intentional regression failures followed by
successful correction verification, not supervisor verification.

CI/browser were not executed. Full-suite, dependency-free, model checks and runtime
walkthroughs were not rerun for packaging/correction. No models, downloads,
dependency upgrades, paid calls or AWS operations. Richard has reported no new
commands; all new verification is agent-executed. Stage 3 remains pending.

Remaining operational limit: if the database is unavailable or a deadline prevents
persistence, a reserved attempt remains durable; inspect and explicitly recover
once available. An older discarded result never owns recovery of a newer token.
Expired audit-only cleanup retains the documented separate five-second statement
bound; it cannot dispatch more reads. Stage 2 stays at the review gate.
