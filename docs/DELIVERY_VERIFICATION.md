# Delivery workspace verification

This release uses fictional records and simulated choices. The report in
[`reports/delivery-workspace/comparison.json`](../reports/delivery-workspace/comparison.json)
contains33 real PostgreSQL product runs across11 frozen cases, with the same source
hashes and budgets for rules, one chooser and coordinator plus specialists. It also
contains a separately labelled controller simulation for adversarial invalid actions,
early review and timeout/fallback. These are distinct evidence populations.

| Mode | Expected outcome matches | Policy reads | Projected safety reads | Bundled safety assessments | Median local runtime |
|---|---:|---:|---:|---:|---:|
| Rules |10/11|76|27|1|934ms|
| Single chooser |9/11|73|25|1|890ms|
| Specialists |10/11|71|25|1|2344ms|

Four mismatches are retained as scored failures: rules review policy-denied rather
than report a blocker; single chooser reviews policy-denied and out-of-stock early;
specialists review stock drift after safety invalidation. No unsafe proposal was
observed in this set. These11 designed fixtures are engineering regression evidence,
not a statistical quality study or proof of specialist superiority. Local runtime
includes actual database/controller work and specialist checkpoint setup; model
calls are zero. Live model decision quality, live inference latency and live API
cost are **unmeasured**. The report records explicit evidence-validity and timing
boundaries, per-run audits, freshness/retry counts, outcomes, budgets and source
hashes. Follow-up session handling is verified separately by chat/browser tests.

Reproduce from an isolated PostgreSQL setup in [DELIVERY_WORKSPACE.md](DELIVERY_WORKSPACE.md):

```bash
mkdir -p runs
.venv/bin/python -B -m decisionops.commerce.comparison --postgres --adversarial > runs/delivery-comparison.json
```

A future authorized live comparison must use these frozen cases, source snapshots,
expected labels and budgets unchanged, with explicit bounded model transports and
observed usage/cost. Retain invalid/timeout/early-review attempts. Do not tune against
these fixtures and then claim fresh held-out quality.

## Acceptance evidence

Commands below were run locally with PostgreSQL16.15 in a user-owned loopback test
cluster, CPython3.12 and Node24/system Brave. Docker socket access is unavailable to
this account; a fresh Docker image build/start is not claimed. The same application
source was launched directly using `commerce_delivery_local.py`. Historical fixtures,
other worktrees, remote branches and external systems were preserved.

| Gate | Evidence command / assertions |
|---|---|
| A1 | `python -m unittest discover -s tests -p test_commerce_delivery.py -v`: fresh/0009 upgrade, metadata, replay, immutable conflicts, duplicate and reordered events; isolated schemas. |
| A2 | Same suite: Paris week/event boundary and DST. `scripts/commerce_delivery_browser.py`: browser known3/9/8/9 totals, date bounds/freshness, correct report-to-case links. |
| A3 | Delivery suite: background overdue/nonreceipt dedup, delivered nonreceipt, split scope, recovery/escalation history, missing parcel manifest and concurrent scanner/business locks. Browser split order asks for the exact parcel. |
| A4 | Fresh real browser Lyon flow: both tracks/evidence, proposal ID/hash approval, separate confirmation, verified result. Browser runner asserts exactly one operation, replacement, reservation and reserved unit directly in PostgreSQL. |
| A5 | `test_commerce_specialist_acceptance.py`: actual persisted wrong-scope observation and actual conflicting carrier event rows fail join safely; transient unavailable carrier retries within caps. Existing specialist tests that inject malformed/expired observations remain narrower adapter-boundary tests. Delivery/comparison/eligibility tests cover replaced/outage/history/stock/policy/drift. |
| A6 | `test_commerce_conversations.py`: distinct sessions/actors, ambiguous order, out-of-store cases, old generation and changed source evidence, bounded routing, status preserving proposal/approval. Browser checks independent sessions, split selection, genuine staff role403 and another actor's conversation404. |
| A7 | `scripts/commerce_delivery_recovery.py`: actual process exit73 after committed order work; fresh worker reuses2 committed steps; duplicate confirmation shares a job; one proposal/operation/reservation. `commerce_worker_walkthrough.py` and `commerce_execution_walkthrough.py` separately verify execution restart/replay/reconciliation. |
| A8 | `comparison --postgres --adversarial` and comparison tests:33 actual runs plus separately labelled adversarial controller simulation, matching hashes/caps and measured policy-attempt accounting. |
| A9 | Dependency-free profile, required no-skip PostgreSQL profile, full locked Commerce repository suite, frontend build, real browser runner, local commits, diff checks and independent reviews. Exact final totals and commit appear in the final local handoff. |

Independent review reproduced and prompted fixes for scanner lock inversion, a
missing shipment manifest starving workers, old-generation evidence displayed as
current, and historical investigation freshness overriding a verified execution.
Focused regressions cover those fixes. Authority remains Commerce-owned throughout;
no model or report response can approve or execute.
