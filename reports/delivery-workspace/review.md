# Independent review record

This is the historical implementation review. The dedicated follow-up supervisor
audit and additional corrections are described in
[DELIVERY_SUPERVISION.md](../../docs/DELIVERY_SUPERVISION.md).

Base:3eccbdf2db4a5db1a8a749c6c3a3112b751648c3. Reviews and fixes stayed local.
No external messaging, paid product/evaluation calls, model downloads or real
merchant/carrier integrations were used.

| Review | Profile used | Scope and final verdict |
|---|---|---|
| Inventory | GPT-6 Luna/high | Read-only source/test mapping at the base; identified missing A1–A9 capabilities. |
| Data and concurrency review | GPT-6.1 Sol/high | Pinned562efff; actual PostgreSQL probes confirmed scanner starvation, lock inversion and stale-generation display. All fixed and covered by regressions. |
| Browser review | GPT-6.1 Sol/medium | Pinned UI d34faa6, then scoped a03b730 re-review plus actual browser. Verified-operation guidance finding closed. Coverage limits led to stronger actionable-state staff and existing foreign-store tests. |
| Final whole-branch review | GPT-6 Astra/high | Pinned a03b730; three additional A6 status findings fixed at3e5b088. Independent four regressions and actual HTTP follow-up probe passed. Final narrow d16f55c review approved with no confirmed findings remaining. |

Bounded implementation used GPT-6.1 Sol/medium for frontend and GPT-6.1 Sol/high
for database/orchestration work. The lead retained the harness's inherited session
profile; it cannot change its own model/effort. The available named profiles were
supported, so no subagent model fallback was needed. Delegation stayed one level
deep, at most three concurrent subagents, with disjoint writing file sets.

Confirmed findings and corrections:

- Missing parcel lines could stop scanning before staff jobs were claimed. A bound
  order-manifest request now leaves missing fulfilment evidence unresolved; unrelated
  work proceeds. Completely absent order scope is logged and cannot authorize action.
- Scanner order-FK locks could invert Commerce's case→order order. Existing linked
  cases are now locked before new case inserts; a synchronized real PostgreSQL test
  exercises a scanner against a concurrent split-order reviewer.
- Old-generation and changed active-source evidence could be labelled current.
  Active and terminal views now share scope/generation/source freshness checks,
  mask invalid facts, and derive unknown/blocker summaries from those masked facts.
- Historical investigation freshness overrode a verified replacement. Execution
  reconciliation now controls completion guidance; historical findings are labelled.
- Rules-baseline proposals/approvals were reported missing in chat. Status now
  recognizes and checks the existing bound proposal without creating another run.
- Safely rejected malformed/wrong-scope committed evidence made chat status fail.
  Follow-ups now use the safe shared projection and return a review explanation.
- Direct browser instructions lacked the new foreign-store fixture. The isolated
  runner is now the documented verification entry point.

The final evidence matrix and measured comparison boundaries are in
[DELIVERY_VERIFICATION.md](../../docs/DELIVERY_VERIFICATION.md). Raw local diagnostic
logs/checkpoints remain outside tracked product source in
`/tmp/decisionops-delivery-session/`. Final broad-suite results are recorded by the
lead after completion; reviewer approval alone is not a substitute for those checks.
