# Boundary to a one-shop read-only pilot

The fictional local staff demo is ready to try. It is not connected to a real shop.
Rules and mocked Decisions now exercise the new browser workflow; the preserved
live model runs ended early in review. No real-shop safety or model-quality claim
follows from fictional tests. The cached-pilot monitor failure remains unresolved
and need not be retried to build a rules-based read-only pilot.

The smallest next implementation milestone is **one authorized read-only shop
connector plus an explicit evidence mapping**, initially with rules and execution
disabled. Choose the shop/platform and reviewed data scope before implementing it.
No speculative connector or deployment was added in this milestone.

| Concrete gap | Required pilot boundary/evidence |
|---|---|
| All records currently seeded | Read-only order/line, exact variant/quantity, payment, fulfilment and shipment identity mappings for one shop; no write credentials. |
| Fictional carrier statuses | Linked carrier events with documented authority, timestamp/expiry, conflicting-status and explicit-loss handling. Delayed tracking alone is insufficient. |
| Demo policy | Shop-approved versioned replacement rules and applicability; missing permission remains unknown. |
| Demo inventory and history | Correct available-unreserved stock semantics; refunds/replacements mapped to covered quantities. Prove completeness before treating empty history as no compensation. |
| Local shared fictional login | Named staff access and single-shop scope, credential handling and an agreed minimal-data/retention policy. Bounded reports may contain customer data; do not upload them as public artifacts. |
| Local-only job operation | An operator-owned isolated environment, bounded read timeouts, audit inspection, restart/recovery procedure and source-change monitoring. Pilot must reject stale/incomplete evidence. |
| Execution routes exist in demo | Enforce read-only pilot server-side: prevent approval/execution writes, not just hide buttons. Preserve proposal preview as advisory and separately test refusal of write routes. |

Before any later real execution, verify exact proposal/generation/hash approval,
revocation after staff/evidence changes, final authoritative recheck, inventory
reservation and compensation atomicity/idempotency, and reconciliation against the
shop's actual write APIs. The local transaction cannot be assumed atomic across an
external platform. Those are later scope, not permission to perform a live action.

Pilot acceptance: inspect one eligible and one incomplete/redacted real-shop read
through the existing seven tools, show provenance/unknowns, demonstrate stale/failed
reads, prove zero business writes and prove cross-shop rejection. Use recorded or
mocked transport first. Paid model access remains separately manual-authorized; a
read-only connector milestone requires no paid calls. No production launch is implied.
