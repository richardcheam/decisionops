# Optional adaptive Commerce investigation — design for review

Status: Stage 1 library implemented under separate authorization; the complete adaptive workflow remains proposed. No model execution. Inspected baseline: origin/main `b27e2d7cda764ef6e52f99eff3e5a9f30a45d0f5` (PR #9 integrated). This document and its [implementation plan](../plans/2026-10-14-adaptive-commerce-investigation.md) describe the planned full workflow. Current Stage 1 library behavior is specified separately; later-stage commands and capabilities are not available.

## Goal and boundaries

An opt-in operator workflow gathers only selected, permitted business observations, records its decisions durably, and ends with a replacement proposal, a disclosed blocker, or review. The browser/API/ordinary worker continue using bundled rules. Business records remain read-only during investigation; investigation, audit, job and budget records are writable. Models never approve, reserve inventory, or execute a replacement.

Preserve the original running migration-0004 application and volume, all worktrees, historical reports, old proposal inspection, provider tests, and the `route_investigated_case` task. Develop and demonstrate against a separate database/project. No real API providers, supervisor, AWS or language-generation feature.

## Actual reusable components and gaps

- `decisionops/commerce/read_tools.py`: typed requests/results, record-derived facts, order/variant/shipment binding, content hashes and scope checks. `read_assessment` currently fetches order lines, policy, payment, shipments, inventory and resolutions together. Its seven result objects do **not** represent seven independently selected reads.
- `eligibility.py` and `evidence.py`: deterministic tri-state assessment, trusted sources, freshness and contradictory evidence handling. Reuse their semantics. An unresolved historical result cannot simply be concatenated with a successful refresh: that currently leaves the condition unknown. Introduce an explicit active-observation selection while preserving immutable history.
- `investigations.py` / `proposals.py`: immutable assessments and exact request/policy/seven-source bindings. Current `investigate` always performs the bundled read. Add a separate publication path; do not call it to start an adaptive run.
- `cases.py` / `execution.py`: generation-bound approval, business locking, deterministic recheck, duplicate prevention and reconciliation. Approval and execution keep these protections.
- `jobs.py`: durable claims, lease tokens, attempt caps and completion fencing. It has no heartbeat; only `investigate` and `execute` actions. A separate adaptive queue/action and fenced renewal are required so the original worker cannot accidentally claim adaptive work.
- `workflow.py`: LangGraph is a recoverable projection over authoritative PostgreSQL domain records, with a human review interrupt. It is not an adaptive tool-selection graph today. Preserve it and introduce a separate graph/thread namespace.
- `providers.py`, `provider_service.py`, `provider_budget.py`: validated recommendations, immutable request bindings, bounded reservations and uncertain-call recovery. The current provider task receives an already-complete assessment; its two-choice types and database constraints cannot accept tool choices unchanged.
- `local_provider.py`, `local_model_worker.py`, `worker_pipes.py`: offline pinned loading, corrected native classification/ranking, bounded draining and process-group cleanup. Today each recommendation loads a subprocess. A reusable session needs a new bounded framed protocol; the one-shot EOF-based consumer cannot be treated as an existing session protocol.

Stage 1 implementation contracts are resolved in the [selectable-read contract](2026-10-14-adaptive-commerce-stage1-contract.md). Later stages remain proposed.

## Explicit tools

All inputs include the run's immutable order, shipment and exact variant/quantity request, dependency observation IDs, and a deadline. IDs and hashes are audit/binding fields, not model features. Every SQL projection, including supporting queries, belongs to a declared tool and is recorded. A tool may perform several declared queries; trace both tool attempts and query groups rather than equating one tool with one database lookup.

| Tool | Declared records and returned observations | Dependencies and scope |
|---|---|---|
| `order_manifest` | Order identity/store/currency/policy reference and original lines; `quantities_valid`, full-order request scope | First tool; exact variants/positive quantities. Unknown order or absent lines remains missing. Policy reference is not policy permission. |
| `replacement_policy` | Applicable versioned policy; `policy_permits`, permitted quantity limit and carrier freshness rule | Manifest; match order policy and store. Missing/contradictory policy is unknown. |
| `payment` | Relevant payment records; `paid` against manifest total/currency | Manifest; missing payments are unknown, not unpaid. Unsupported multiple/conflicting records require review. |
| `fulfilment` | Order shipment membership, requested shipment and shipment-line quantities; `shipped`, split/partial shipment scope | Manifest; wrong-order shipment lookup returns only mismatch diagnostics, never another order's business details. Do not return carrier status. |
| `carrier_loss` | Selected shipment carrier status and observation time; `loss_confirmed` | Valid fulfilment binding and policy freshness rule. Lost can be true; reliable delivered false; stale/in-transit/timeout unknown. |
| `compensation_history` | Resolution rows and an explicit completeness marker; `no_previous_compensation`, partial-compensation scope | Manifest; missing/incomplete/failed history never establishes zero compensation. |
| `inventory` | Store inventory for requested variants, on-hand/reserved and available quantity; `stock_available` | Manifest; exact store/variant quantities; missing rows unknown. Availability does not reserve stock. |

The manifest is a mandatory, visible bootstrap read charged to the tool budget, not hidden preparation. The initial policy observation precedes it and includes only the bounded report/request and available bootstrap choice. Subsequent allowed tools follow the dependency graph. Forbid implicit dependency reads: select the supporting tool explicitly first. Per-tool validation may check binding/revision metadata; any content refresh must be an explicit tool attempt. Use explicit column projections where fulfilment and carrier share a physical table.

Each observation records tool/contract version, source and authority, projected records, content version, dependency versions, order/shipment/store/variant/quantity binding, observed time, expiry, status and reason. A failed read contributes unknown and a retry diagnostic. An unchanged refresh supersedes its previous observation explicitly; contradictory independent authoritative records remain unresolved until a deterministic authority rule exists. Never discard a contradiction merely because a newer attempt succeeded.

## Policy-visible state and actions

Add a separate typed task, e.g. `investigate_commerce_read_only`; preserve `route_investigated_case` unchanged. One shared contract serves fixed-order, cue-based rules, fake, Laya and GLiClass policies:

- Request envelope: task, case/run/generation, step and context version, provider/checkpoint/configuration, deadline, request/tool/retry/latency budgets and explicit allowed action schemas.
- Model features: bounded initial staff/customer report (proposed maximum 2,000 UTF-8 bytes), normalized requested items, requested observations, attempted tools with bounded failure/rejection feedback, and remaining budgets. Treat customer text as untrusted data, not instructions. No case IDs, scenario names, opaque hashes, hidden labels, unrequested rows or complete precomputed assessment in model features.
- Allowed actions: `read(tool_name)`, `propose`, `report_blocker`, `request_review(reason_code)`. Reasons use a small enum; no generated prose is required. Record native scores, their meaning and uncalibrated confidence separately from validated facts.
- Result: request/provider identity, selected action, status/error, real usage where measurable, native scores, load/inference/total latency, peak memory, validation and application outcome. Local inference has zero API charge, not fabricated token usage or dollar pricing.

A deterministic eligibility function computes the current allowed actions from collected evidence, scope and budgets. Selecting an unavailable tool, an unlisted action or an instruction override produces bounded rejection feedback and spends a decision attempt; it does not execute a tool. A single allowed action is forced deterministically, recorded as such, with no inference. Policy failures have an explicit recorded fixed-order fallback or review; no invented observations.

Fixed order is the baseline; cue rules can move an eligible tool earlier based on the report, but never infer its result. All policies receive identical permitted information and use the same validators. Browser/API remain rules-only, with no adaptive mode automatically enabled.

## Stopping and deterministic publication

- `propose` is allowed only after all seven mandatory conditions are established true, supported full-order/single-shipment/no-partial-compensation scope is established, and all active evidence is valid and current. Missing checks cannot be supplied by a hidden final bundled read.
- `report_blocker` requires at least one trusted, current false condition with valid requirement-specific bindings. Persist the blocker and enumerate every unknown/unread condition and unresolved scope check. Distinguish an **observed blocker report** from a completed assessment. If global supported scope is not established, publish the case as `needs_review` with that report; use `blocked` only when supported scope is established. This preserves the bundled workflow's unsupported-case review precedence while allowing useful early termination.
- Missing, contradictory or unsupported information permits `request_review`; it is never converted to false. Budget exhaustion, repeated tool failure, cancellation and unavailable provider have explicit review/fallback reasons. A valid already-collected blocker can still be reported at exhaustion; exhaustion cannot waive proposal prerequisites.
- Before publication, revalidate case/run/context and evidence bindings in a short transaction. Expired/changed observations become refresh-required, with bounded feedback; choose refresh tools explicitly if budgets permit, otherwise review.
- After all required observations have been explicitly collected, proposal creation may use the existing locked bundled safety recheck. This is a separate safety attestation, not a policy observation. It can only confirm the complete collected binding or refuse publication. It must not fill missing evidence, quietly change facts or feed newly read records into the policy. Changed bindings produce invalidation feedback, followed by explicit requested refreshes.
- Approval and execution retain their existing full deterministic rechecks and transaction locking. These safety reads never become model observations automatically. Staff approval remains exact and generation/content-bound; a recommendation cannot approve or execute.

Extract shared record-to-fact derivation so bundled and adaptive paths agree. Existing proposal binding version 1 must remain inspectable and recheckable. If projected dependency hashes require a new binding contract, add an explicit version and dispatch validators by version; do not rewrite historical documents or silently reinterpret their hashes.

## Persistence, concurrency and recovery

Proposed additive migration after 0005: investigation runs, immutable steps/observations, decision reservations and a case state revision. Final numbering follows repository migrations at implementation time.

A run binds case generation, case revision, request/report snapshot, policy/tool contract versions, provider configuration/checkpoint and deadlines. Allocate a generation once at start, clear superseded approval through existing invalidation semantics, and enforce one active run per case. Every relevant staff mutation increments the case revision; generation alone is insufficient for same-generation escalation/rejection. Each durable step has a unique run/step identity, visible-context hash, lease token, request/result, budget reservation and disposition. Store active-observation pointers separately from immutable history.

Use short transactions to claim/renew, reserve, persist tool results and publish. Inference runs outside database transactions and business locks. A heartbeat renews only the current token; every write/publication checks unexpired lease and current case revision/generation. Loss of lease cancels the owned model process; stale results are recorded but cannot affect current case state. Concurrent approval, execution or staff escalation must never be overwritten.

PostgreSQL is authoritative; LangGraph checkpoints project durable step IDs. Restart reconstructs the last committed step, does not reset budgets, and never repeats a settled recommendation. A dispatched decision without a known result remains uncertain: no automatic redispatch. An explicitly recorded fallback/review can continue without that call. Read-only tool attempts interrupted before result persistence may be retried as a new, budgeted attempt, preserving the abandoned attempt and recording a new observation time.

Evidence expiry is checked before each decision and publication. Dependency changes invalidate descendants (policy changes invalidate carrier freshness conclusions, for example). Historical inspection uses recorded immutable checkpoint revisions without consulting current pins; new admissions follow configured pins. Old undispatched model requests retain the existing controlled no-dispatch behavior if current policy no longer admits that revision; never substitute a newer checkpoint.

Extend durable accounting to adaptive decisions with explicit task/action schemas rather than bypassing the current two-choice constraints. Reserve bounded counts before dispatch, settle known results, retain uncertain reservations and exact Decimal pricing/config versions. Local calls reserve counts/deadlines with zero API charge. Tool attempts and retries also have durable caps; fallback and rejected choices cannot create an infinite free loop.

## Resource plan

Proposed initial limits for review: 12 tool attempts, 16 decision attempts, at most two attempts per tool, 240 seconds total run wall time, including queueing and model loading. Missing inputs do not consume unlimited refreshes.

One reusable model child per adaptive run, batch size one, CPU four threads, one family per host at a time using a bounded host-local ownership lock. Acquire the slot with a deadline; no database lock spans model work. Load once with a maximum 120-second preload; each decision has at most 20 seconds and the remaining run deadline. Persist load phases and cumulative resource measurements, including reloads after restart. Terminate at terminal outcome, cancellation, lease loss or deadline; no idle persistent model daemon in this slice.

Set offline environment before importing model libraries. Preserve exact cached checkpoint resolution and optional dependencies. Use bounded framed stdin/stdout with request correlation outside model features, continuous concurrent stderr draining, 32 KiB request and 64 KiB per-stream/per-result caps plus a bounded whole-session diagnostic budget. A per-frame cap alone cannot allow indefinite stderr accumulation. Overflow/malformed framing terminates the owned process group, reaps the direct child and saves only bounded diagnostics. Bound descendants retaining pipes and cancellation independently of normal EOF. Reuse existing cleanup tests, but add session-specific tests rather than assuming the one-shot helper suffices.

## Frozen evaluation and interpretation

Freeze fictional records, reports, expected admissible outcomes and tool dependencies before model comparison. Evaluator labels stay outside policy payloads. Suggested small matrix:

| Scenario | Expected evidence/outcome |
|---|---|
| Eligible complete order | All mandatory tools and supported scope; proposal, never execution |
| Unpaid; policy denial; insufficient inventory | Separate blockers at different dependency positions; disclosed unknowns on early stop |
| Existing full compensation | Blocker; no duplicate proposal |
| Missing payment; incomplete compensation history | Unknown/review, never false/empty-history inference |
| Conflicting payment/carrier records | Review until authoritative resolution |
| Stale tracking; missing policy | Loss unknown; supporting dependency explicit |
| Wrong-order shipment; wrong variant/excess quantity | Binding failure or established invalid request, with scope disclosed |
| Partial request/shipment/compensation | Unsupported review; preserve existing scope semantics |
| Misleading report and instruction override | Records prevail; no unauthorized tool/terminal action |
| Tool timeout/unavailable database | Bounded retries/fallback/review and recoverable trace |
| Concurrent staff mutation/evidence expiry | Stale result rejected; explicit refresh or review |

Measure outcome correctness against admissible outcomes, proposal safety violations, unnecessary reviews on complete eligible cases, mandatory tool coverage, tool/query-group/decision/retry counts, full wall time including loads/queueing, peak memory, and fallback frequency. Separate forced choices, real inference and simulated results. Count distinct meaningful policy-visible inputs and decision states; repeated Boolean states or report paraphrases are not independent business scenarios. Early blocker reports can legitimately leave unknowns; coverage is judged against the chosen terminal outcome.

First establish model-free execution/recovery correctness. Then run one bounded offline family at a time on the frozen identical inputs, with a stop condition for resource limits. Preserve negative results and current historical comparisons. Report integration and reference-policy agreement only—not held-out generalization, calibrated confidence or proof of business value. Fewer calls alone establish neither efficiency nor value.

## Operator walkthrough to deliver

In an isolated environment, create a case, start an explicit adaptive rules run, inspect its permitted context, chosen tool, declared queries, evidence binding and terminal result. Inject a deterministic tool failure, inspect the unknown/rejection and remaining budget, restart the adaptive worker, and verify no duplicate decision dispatch or changed approval. Demonstrate expiry or staff mutation rejecting a late result. RUNBOOK must give actual commands, expected output, smallest safe configuration/patch, verification and rollback; commands do not exist yet and must not be presented as currently runnable.

## Decisions proposed for review

1. Adopt the seven-tool catalog and explicit manifest bootstrap; preserve full-order/single-shipment support rather than adding partial fulfillment.
2. Use observed-blocker reports with `needs_review` when overall scope remains unresolved; reserve `blocked` for established supported scope.
3. Use per-run model sessions and the initial limits above; measure before increasing caps. Fixed-order fallback is recorded and bounded, with review when it cannot finish safely.
4. Use a separate adaptive CLI/queue/graph first. Browser adoption and a broader routing task remain later milestones.

Stage 1 has settled projected hash/binding semantics, completeness/authority rules and case-revision coverage in its resolved contract. The publication bridge must be implemented and tested in Stage 2; the framed-worker schema and caps remain Stage 4 decisions. These are bounded design decisions, not permission to weaken existing guarantees. No product code is authorized by this design document alone.

Attribution: repository inspection and this design were agent-executed. No new Richard-executed commands, tests or model results are claimed.


Stage 2 implementation review uses the [resolved durable contract](2026-10-14-adaptive-commerce-stage2-contract.md). Browser/API/worker defaults remain bundled; Stage 3 is pending.
