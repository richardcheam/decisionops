# Approved Local Execution Implementation Plan

**Goal:** Complete the fictional-store case -> investigation -> review -> atomic
replacement -> reconciliation flow and prove transaction/race behavior.
**Spec:** docs/superpowers/specs/2026-10-13-approved-local-execution.md
**Execution:** Native in existing commerce worktree; owner authorized autonomous
local decisions, no mandatory exercises. Existing changes stay intact.

- [x] Add frozen 0003 migration and metadata for cases, review/events, operations,
replacement orders/lines, reservations and compensation guards. No new dependencies.
- [x] Test then implement cases.py with explicit lifecycle, locked business snapshots,
review binding, supersession and permanent invalidation.
- [x] Test then implement execution.py: approved-only transaction, unique operation,
atomic reservation/compensation, read-only reconciliation and duplicate protection.
- [x] Extend existing CLI, add isolated full walkthrough, run real concurrent tests,
rollback and lost-response recovery; preserve existing assessment/fixtures.
- [x] Apply additive migration preserving public business values; add model-free CI
and update operational docs with exact commands and known remaining milestones.
- [x] Full dependency-free and PostgreSQL tests, separate self-review, fix failures
until passing. Record exact evidence; no paid calls or external publishing.

Review focus: stale approval remains revoked after source restoration; same order
across two cases; inventory races across two orders; rolled-back operation IDs;
failed lookups never become empty compensation history; arbitrary caller operation
ID cannot execute another approval; direct SQL compensation guard serializes writes.
