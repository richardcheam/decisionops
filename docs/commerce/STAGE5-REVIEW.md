# Stage 5 review — partial, blocked before native models

Stage 5 is **not complete**. Do not merge, release, enable adaptive defaults or run
native models from this snapshot. Accepted Stage 4 is preserved at
`d3c3896e3ca47af7bcf3542744f642f6d7e6c1e9` on adaptive-sessions. Stage 5 worktree:
`runs/worktrees/stage5-evaluation`, branch `feat/commerce-adaptive-evaluation`.
Origin/main was rechecked as b27e2d7cda764ef6e52f99eff3e5a9f30a45d0f5. Original
canonical checkout remains on0d0aa1e with Richard's untracked handoff preserved.

## Correction status (2026-10-15)

The bounded follow-up is documented in [STAGE5-CORRECTION.md](STAGE5-CORRECTION.md).
It corrects readiness and synchronizes demonstrated test boundaries; original
failures below remain historical evidence. Native loading/comparison is still
closed pending supervisor review. Current-source public CI remains blocked; no
upload was retried. Frozen fixtures,57 verified pairs and attestations are unchanged.

## Original stop conditions actually reached

1. The isolated browser project migrated its new fictional database to actual head
   **0008**. Unchanged `decisionops/commerce/api.py:131` requires exact **0005** in
   `/health`, returning503: `Apply the current business migration before starting
   this release`. Compose could not start web; six browser tests attempted and
   failed with connection refused. Their business assertions were not verified.
   No downgrade, accepted-source patch or original-runtime operation was used to
   hide this incompatibility. Align schema readiness with the intended current
   API/schema contract and add a positive migration-0008 health regression before
   retrying this gate. Never automatically migrate the original application.
2. Required local PostgreSQL profile: **189 collected,185 passed,1 failure,3
   errors,zero skips**. One justified focused recheck after baseline/browser
   workloads ended: **4 collected,1 passed,1 failure,2 errors**. Do not dismiss
   these as contention or claim the profile passed. No application code was fixed.
   Reproductions identify:
   - provider real-deadline test returned settled rather than uncertain;
   - staff approval/execution during cancellation raised Stale dispatch context;
   - checkpoint-lock and terminal publication/lease paths raised deadline/lease
     errors (one checkpoint path passed on focused recheck).
   Exact names, commands, tracebacks and both outputs are retained.
3. Current-source CI was **not executed**. Automatic approval review rejected
   uploading the large fictional enumeration artifact to the public GitHub repo:
   "current Stage5 authorization requests local review and model-free CI rather
   than explicitly authorizing remote repository writes or publication."
   No alternate transport, artifact omission or repeat upload was attempted. Some
   source blobs were created before rejection; no Stage5 commit/ref/branch was
   published. Local review documentation and the complete archive remain available.
   Prior accepted Stage4 CI is not evidence for this new source SHA.

These stop conditions closed the real-model gate. **Zero native compatibility
pilots, checkpoint loads, comparisons or replay decisions occurred.** Existing
cache/package metadata was inspected only: torch2.14.0+cpu, transformers5.17.0,
laya0.3.20, gliclass0.1.20, huggingface-hub1.33.0. Both pinned snapshot directories
exist under /mnt/hdd/data/hf. No substitution/download/upgrade/model training,
paid calls or AWS. No model latency, memory, calibrated confidence, quality or
business-value result is available.

## Frozen evaluation and completed model-free work

Frozen before dispatch in ee206c1: data/commerce/adaptive-evaluation-v1/manifest.json
and its SHA256. Seed-source hash plus fixed setup SQL and relative-time semantics
specify fictional records. Per-run full snapshots are retained.19 entries consist
of14 ordinary record/request states plus5 robustness variants. Eligible, blockers
at policy/payment/stock/compensation, missing/history incomplete, stale tracking,
wrong shipment/variant, partial request/compensation, instruction override,
conflicting/missing projected records, tool failure/retry and staff change are
covered. Projection conflicts are explicit adapter faults, not impossible duplicate
physical primary-key rows. Labels/IDs stay outside policy features.

Fixed order, cue rules and fake-session each completed19 fixtures:57 initial runs.
Raw calls, requested observations, actual tool sequences, declared query groups,
private validation distinction, retries, budgets, phases and terminal traces are
preserved. All raw records were read-only during investigation. No staff approval,
replacement execution or stock reservation occurred. Each policy had9 repeated
read attempts across its fixtures,0 fallbacks/rejections/uncertain calls/duplicate
dispatches and0 unnecessary eligible reviews. Every final verified outcome is
admissible; no unsafe or unverified proposal remains in the verified set.

Initial evaluator review exposed missing audit retention and permissive scoring.
The agent corrected ONLY evaluation/reporting, with RED-to-GREEN regressions:
unfinished runs cannot count as review; blocked requires supported scope and
unknown/unread/unresolved-scope disclosure; a proposed result requires a retained
v1 attestation. The48 original non-proposal traces were re-adjudicated offline;
exactly9 proposing fixture/policy combinations received additional verification
retaining real v1 documents, linked investigations and successful current rechecks.
Their hashes/bindings were also checked offline. This is57 verified fixture/policy
pairs with9 additional verification runs, not66 independent scenarios. Original
57 traces remain immutable, including their original incomplete evaluator metrics.

Fake child native-field inference_performed=true describes simulated integration
work: all138 decisions are **simulated**, actual native inference=0. Aggregate
analysis corrects that label without rewriting raw traces. Waiting/load/inference/
total fields and peak RSS are fake-process measurements only. Fixed/cue/fake wall
times include schema/migration/seed overhead and overlapping host workloads; no
relative efficiency claim is justified. API charge is exactly zero; no token counts
or artificial pricing.

The replay sampling plan was frozen in de304f8 before any native run.16 exact
six-field policy feature objects were selected from baseline states and hashed;
they have not been replayed to native models. Identical initial fixtures do not
imply identical later adaptive trajectories. Preserve complete features/exact
hashes. Original running baseline process used descriptive normalizer v1 (drop
report/seconds),123 groups. Explicit v2 retains cue/override classes and drops
fractional elapsed time,152 groups; corpus/enumeration/test use v2. Join analyses
by unchanged exact-feature hashes. Neither count is independent business cases,
all possible language meanings or a model-quality sample. Native model inputs
would receive exact features, never these descriptive hashes or evaluator labels.

Predeclared limits remain unchanged:1200s experiment,600s/family,1 pilot/family,
19 end-to-end fixtures/admitted family plus16 exact-input replay decisions;
120s preload/20s decision/240s run,4 CPU threads,batch1. Host reserve512MiB,
preflight3584MiB Laya/1536MiB GLiClass, RSS ceilings3072/1024MiB. These were not
exercised by native models because correctness failed first. Package/cache/resource
inspection is not a compatibility pilot.

## Actual commands and checks

From runs/worktrees/stage5-evaluation, no dependency installation:

```bash
export COMMERCE_TEST_PYTHON=/home/richard/projects/decisionops/runs/worktrees/local-providers/.venv/bin/python
export COMMERCE_TEST_DATABASE_URL='postgresql+psycopg://commerce_stage5:stage5-fictional-only@127.0.0.1:55441/commerce_stage5_test'
"$COMMERCE_TEST_PYTHON" -B scripts/commerce_adaptive_evaluation.py --mode baselines --output runs/stage5-baselines-2
"$COMMERCE_TEST_PYTHON" -B scripts/commerce_stage5_walkthrough.py
"$COMMERCE_TEST_PYTHON" -B scripts/commerce_ci_tests.py postgres
python3 -B -S -m unittest discover -s tests -p test_commerce_adaptive_evaluation.py -v
python3 -B -S scripts/commerce_ci_tests.py dependency-free
python3 -B -S -m decisionops workflow export-html --report-dir reports/workflow-model-comparison-20260927 --output runs/stage5-viewer/index.html
python3 -B -S -m decisionops.commerce.evaluation --output runs/stage5-commerce-regression.json
```

| Check | Actual result |
|---|---|
| Current evaluator pure tests |10 passed; RED/green evidence retained |
| Final dependency-free profile |377 collected,186 passed,191 explicit skips |
| Required PostgreSQL |185 passed,1 failed,3 errored; zero skips |
| Focused PostgreSQL recheck |1 passed,1 failed,2 errored |
| Frozen baselines |57 verified fixture/policy pairs;9 extra attestation verifications |
| Fake CLI recovery |Success8 decisions/7 reads/1 load; uncertain9 decisions/1 retained unknown/zero redispatch; all children reaped |
| Browser |6 attempted,6 failed; API health prevents web startup |
| Historical viewer |One index.html; offline-synthetic and uncalibrated notices preserved |
| Frozen legacy Commerce regression |Executed successfully, zero inference |
| Native pilots/comparison/replay |Not executed: correctness gate blocked |
| Current-source CI |Not executed: publication rejected by automatic approval review |

The191 dependency-free skips are189 opt-in database tests and2 optional Laya
package tests. They are not database passes. See verification/*.log and retained
commands for exact outputs; the report does not replace them.

## Isolation, operations and next gate

Only new disposable tmpfs databases/containers/projects were operated on:
- decisionops-adaptive-stage5-tests, loopback55441, commerce_stage5_test,
  commerce_stage5 user; per-run schemas upgraded/seeded/dropped independently.
- decisionops-stage5-browser project, loopback55442 database and8082 web,
  unique Compose network; cached app image with current Python source mounted
  read-only; cached frontend asset, current browser tests. No fresh web build is
  claimed. First attempt referenced removed image IDs and failed; cached available
  tags were then used, with no pull/build/retag or original-container change.
Both isolated projects were removed after evidence collection. Container/volume
inventories and accepted Stage4 archive hash are retained. Original4 container
IDs, migration-0004 volume, worktrees, canonical handoff and historical reports
remain intact. Investigation modifies audit/case/job records only; case execution
in browser tests never reached its business assertions.

RUNBOOK contains demonstrated startup/readiness/migration/seed, mode selection,
inspection, recovery and shutdown commands, and the failing readiness diagnosis.
Staff approval remains exact generation/proposal/content-bound. Adaptive choices
cannot approve/execute; deterministic revalidation, transaction locks, reservations,
duplicate prevention and reconciliation remain unchanged. Rollback is to stop
opting into adaptive CLI; never downgrade or alter original runtime.

Next: review this blocked bundle and authorize the bounded readiness/deadline/
concurrency corrections before any model comparison. CI publication needs explicit
approval for the reviewed source/fictional data in the public repository. Keep the
same frozen evaluation and preserve these negative results on continuation.

Attribution: Richard authorized Stage5 but supplied no new personally run commands.
Agent executed every local command and nine additional verifications. Supervisor
Stage4 scope was14 fake-child tests, archive/patch integrity, CI/source identity;
not PostgreSQL, native models or browser. Fresh Stage5 reviewer inspected source
only; corrections were agent-tested, not independently rerun by that reviewer.
