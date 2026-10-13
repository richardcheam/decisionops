# Durable Worker Implementation Plan

**Goal:** Recoverable no-model workflow with PostgreSQL leases and durable review interrupts.
**Spec:** docs/superpowers/specs/2026-10-13-durable-worker.md
**Method:** Native autonomous execution; no owner exercises or paid calls.

- [x] Test then implement job metadata/0004 migration and fencing service.
- [x] Build typed LangGraph nodes, separate checkpoint schema, review interrupt,
replay from committed job outcomes; disable optional hosted tracing.
- [x] Worker CLI with one-shot/polling, inspection, explicit resume/replay; only
trusted durable case review can resume approval projection.
- [x] Real restart/lease/checkpoint-failure tests and isolated operational walkthrough.
- [x] Migration/metadata, dependency-free regression, full PostgreSQL tests; preserve
public business data; document exact setup/run/recovery/shutdown and known limits.
