# Evidence summary, not a model benchmark

Accepted implementation: `1240345fa37a72f5409b4fb3e88a1719e16ce041`; final accepted
wording: `07904d19e6192560461c0ff84c25a885a1afea31`. Release packaging retains its
business logic. Raw logs, SQL exports, stopped ledgers, review ZIPs and live traces
are preserved in the [external archive](ARCHIVE.md). Only a sanitized outcome summary
and fictional screenshots are served by the public walkthrough.

| Claim | Saved evidence and scope |
|---|---|
| Successful mocked collaboration | `walkthrough-release/success.json`:7/7 conditions,7 reads,proposal; `test_seven_facts_publish_existing_proposal_and_require_exact_approval` |
| Exact approval and separate execution | Ordinary browser test `specialist choices and sources remain visible before exact approval and execution`; unapproved execution409; two confirmations;1 executed event. Success investigation trace stops at proposal; summary records subsequent staff operations. |
| Peer survives unavailable specialist | `walkthrough-release/partial-failure.json`:Order payment/fulfilment retained,4 conditions known;Shipment uncertain;review,no proposal. Executable walkthrough asserts these outcomes. Cancellation unit test is related but not the unavailable-provider join. |
| Restart without redispatch/duplicate proposal | `test_actual_graph_interrupt_after_order_commit_replays_no_effects`;actual container restart trace:2 Order observations retained,7 reads,3 calls each dispatched once,no approval/operation. Execution after restart remains unverified. |
| Adversarial boundaries | Wrong-case rejected at admission;expired/injected unknown-conflict observations tested through graph. Wrong-case through final join,actual conflicting database rows through final join and standalone adversarial traces remain unverified. |

Tests are in [specialist tests](../tests/test_commerce_specialists.py) and
[browser tests](../frontend/multi-agent-tests/specialists.spec.ts); code and exact
saved test/trace mapping are in [the closeout](commerce/MULTI-AGENT.md).

The accepted local record includes212 required PostgreSQL passes,18 focused specialist
passes,8 pure contract passes,13 staff regression passes,3 browser passes and12 frozen
eligibility cases. Dependency-free checks reported236 passes/297 optional skips.
These are historical agent-executed results,not a current CI assertion; see
[release verification](RELEASE.md) for packaging-source executions.

Same-input baseline: existing fixed-order adaptive rules,not a live single-model agent.
Both paths used7 policy-visible reads and8 decisions. One local mocked measurement was
783ms rules versus1660ms specialists,including local persistence/checkpoint work.
More agents have no measured efficiency or business-value advantage here;opt-in only.

## Separate historical live evidence

Two manual Commerce API investigations ended in review,not proposals. The Decisions
run left inventory unread; a safe early review is not completed replacement eligibility.
The separate browser experiment does not power the staff workflow: live001 rejected
multiple decisions before applying any action;live002 followed two Site A links but
its finish was rejected,leaving five cases unexecuted. Offline citation correction did
not retroactively make that run successful. No live cross-site transfer is established.
Cached local-model pilots remain stopped after a resource-monitor failure.

[Sanitized machine-readable summary](../frontend/public/evidence/summary.json).
No new model calls,paid access probes,training or telemetry export accompanied packaging.
