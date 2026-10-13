# Durable Investigations Implementation Plan

> **For agentic workers:** Use native execution in the existing commerce worktree. Richard authorized autonomous local work; no owner exercises required.

**Goal:** Save investigations and immutable evidence-bound replacement proposals with a CLI for inspection and current-state checks.
**Architecture:** Existing read_assessment remains the source of facts. New audit tables store snapshots; proposal binding is a pure Python projection. Check is read-only and never grants execution permission.
**Tech Stack:** Existing Python, SQLAlchemy, Alembic, PostgreSQL; no new dependencies.
**Spec:** docs/superpowers/specs/2026-10-13-durable-investigations.md

## Global constraints

Preserve original domain/evidence/fixture behavior and historical diagnostics.
No paid APIs, model downloads, AWS, approvals, reservations or replacements.
Keep canonical checkout and PR #6 untouched. Separate agent and owner verification.

## Review focus

Carrier events expire even when content versions match.
Changes that leave stock sufficient still invalidate a bound proposal.
Incomplete history and wrong-order shipments must never produce proposals.
Failed audit persistence rolls back both records and sanitizes credentials.
CLI exit 0 for persisted review differs from check exit 4 for reinvestigation.

## Tasks

- [x] Pure proposal binding: decision-gated immutable document, deterministic digest, compare current binding and eligibility; test without database dependencies.
- [x] Persistence: metadata plus frozen 0002 migration, append-only triggers; service investigate/save/inspect/check; isolated PostgreSQL tests for binding, drift, rollback, immutability, no business mutations and populated upgrade.
- [x] CLI and operations: exact investigate/inspect/check commands, missing/outage errors, isolated local success/stock-drift demonstration; update RUNBOOK, LEARNING and DECISIONS.
- [x] Verification: model-free suite, full PostgreSQL suite, migration metadata check, self-review, diff whitespace check. Preserve all existing uncommitted slices; no automatic publication or merge.

## Execution evidence

Native agent execution. Tests written and observed failing before implementation.
Record actual commands/results and any deviations here after verification.


Completed 2026-10-13 by native agent execution. Pure tests first failed on the
missing proposal module, then passed 6/6. Integration tests first failed on
missing persistence/CLI modules, then passed 12/12. The tamper-test fixture was
corrected to use an investigation without an existing proposal, respecting the
unique investigation/proposal constraint; no product behavior was weakened.

Verification commands: python3 -B -S -m unittest discover -s tests -> 138 run,
109 passed / 29 optional database/ML skips. COMMERCE_TEST_DATABASE_URL=<local demo>
.venv/bin/python -B -m unittest discover -s tests -> 138 run, 136 passed / 2 ML skips.
Alembic check -> no drift; public revision 0002; all original business records
unchanged. Walkthrough demonstrated success -> drift exit 4 -> isolated undo
success. Real unavailable URL returned sanitized database error exit 3.

Final self-review checked request binding, source versions, carrier expiry,
read-only check/inspect, transaction commit-before-success, append-only triggers,
and migration compatibility. No independent reviewer was used. No new dependencies,
commit/push/merge or cloud spending. Existing uncommitted slices were preserved.
