# Two local browser fixtures and model-free harness

Preserve frozen b85a23e Site A/worktree/runtime and d2f174e release. New worktree
feat/browser-investigation only. Reuse frozen Shop component byte-for-byte for an
isolated evaluation copy of A with neutral records; implement B as dashboard →
Purchases tab → receipt → Delivery disclosure → parcel record/event table. Existing
staff app/DB/approval services unchanged; evaluation fixtures use read-only static
records, no PostgreSQL dependency or staff data. No new packages/models/downloads.

Freeze six cases/records/as-of/grading and resource/controller contract before any
model run. No model runs authorized. Agent features only structured goal and start
URL, then rendered bounded observations/current controls; private evaluator data is
not imported by controller. All fixture selectors/scripts remain test-only.

Transport: fresh browser context, SW blocked, all HTTP requests intercepted before
sending. Exact loopback origins, separate document/resource allowlists, GET/HEAD only,
no query/encoded/path escape, credentials, workers/popups/downloads/websockets. Fetch
permitted requests with maxRedirects0; ALL redirects rejected (stricter initial
contract, fixtures need none). Never expose response bodies to policy. Server projects
only requested customer fields. No private/admin APIs.

Observer: visible text + semantic blocks + current accessible controls, no hidden DOM
or script/data stores. References expire on any observed document change. Citation
validation requires exact visible spans in saved untruncated blocks with unambiguous
order/parcel binding. Errors/stops distinct; safe early stop isn't task completion.
60s/run,12 action attempts,16 observations,8KiB/frame,32KiB cumulative policy context;
5s/read;1 known-read retry;32 total tool attempts including rejected/finish attempts.
No locks/DB or Commerce attestation; browser evidence is untrusted page evidence.

1. Freeze fixture/evaluation/controller JSON and hashes; build isolated A/B, scripted
fixture tests and screenshots using cached frontend/browser images.
2. Implement open/observe/act/finish; meaningful model-free network sent-count,
visibility/citation/binding/stale reference/budget/failure tests. Run six scripted
harness contract cases labelled model-free integration, not transfer performance.
3. Review/fix concrete failures; preserve raw negative outputs. Verify frozen A bytes,
locks and Commerce code unchanged. Local commits and docs, no publication.
4. Only after model-free gate, inspect existing SDK + official docs; prepare manual
bounded six-case API controller/runner with mocks, durable reservation/uncertainty,
source/config admission and no automatic retry. Stop for explicit spending approval.
5. Inspect existing LangGraph persistence, propose smallest orchestration + PostgreSQL
browser-run authority and sanitized Langfuse export, no install/external telemetry.
