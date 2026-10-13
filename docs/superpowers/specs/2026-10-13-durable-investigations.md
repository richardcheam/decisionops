# Durable investigations and immutable proposals

Richard authorized autonomous local development on 2026-10-13, with operational
walkthroughs recorded for later discussion. No mandatory exercises or review gates.

## Scope

Persist the existing record-derived assessment and, only for eligible supported
cases, an immutable replacement proposal. Preserve existing read-only assessment,
fixture CLI, evidence rules, historical diagnostics and model-free checks.
No approval, replacement creation, stock reservation, job worker or paid inference.

## Design

Two append-only PostgreSQL tables: commerce_investigations stores the exact request
and assessment with database timestamp; commerce_proposals stores an immutable
version-1 replacement document, its SHA256, and a unique investigation reference.
The document binds order/shipment/quantities, policy ID and all seven evidence
content versions. PostgreSQL triggers reject UPDATE/DELETE of saved rows.
An investigation and its optional proposal commit in one repeatable-read
transaction. Business tables are queried only. Missing orders can be recorded
for diagnosis, so investigation.order_id has no order FK.

A separate CLI offers investigate, inspect and check. Check reloads current
business evidence read-only and compares the binding against the proposal while
requiring current eligibility. It is valid_for_review only when both conditions
hold. It is never authorization to execute; state can change after check.
Changed source records or expired carrier evidence produce requires_reinvestigation;
unavailable database exits 3, missing identifiers/invalid requests exit 2.
Unknown transaction outcome is reported explicitly; do not blindly retry a write.
Each investigate invocation intentionally creates a new investigation, not a
business replacement. Durable operation idempotency belongs to M3.

## Acceptance

Preserve business records during investigation/check. Eligible cases produce one
proposal; ineligible/unknown/unsupported cases produce none. Original saved output
survives later record changes. Stock changes, compensation, policy changes and
carrier expiry block continued review even if some changes leave eligibility true.
Database rejects mutation of saved documents. Rollback leaves neither investigation
nor proposal after a failed insert. No PostgreSQL dependency in pure binding tests.
Migration upgrades populated 0001 data without change, matches metadata, and its
downgrade deletes only the new audit tables (never an outage remedy).

## Deferred boundaries

Hashes establish content identity, not authentication. Demo database administrator
can bypass triggers and insert fabricated records; roles/authentication must precede
public exposure. No lifecycle transitions, staff identities or approval yet.
Investigation records are business audit snapshots, not LangGraph checkpoints.
Stock race prevention and compensation uniqueness remain required before writes.
