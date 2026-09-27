# Recorded diagnostic workflow evaluation

> Offline synthetic simulation. Fixture tools return recorded observations; no shell command, live service, or host action is executed.

| Policy | Split | Episodes | Run | Terminal statuses (completed/review/failed) | Terminal reasons | Failed | Supported diagnoses | Correct reviews | Incorrect diagnoses | Unnecessary review | Unsupported proposals | Invalid proposals | Policy errors | Budget exhausted | Tool failures | Tool calls mean | Latency p50 / p95 | Model load | Peak RSS |
|---|---|---:|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| fixed_order | development | 12 | passed | 7/5/0 | completed=7, review=5, exhausted_budget=0, invalid_proposal=0, tool_failure=0 | 0 | 7/7 | 5/5 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 4.00 | 0.9 / 1.2 ms | 0.00 s | 32464896 bytes |
| rules | development | 12 | passed | 8/4/0 | completed=8, review=4, exhausted_budget=0, invalid_proposal=0, tool_failure=0 | 0 | 7/7 | 4/5 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 2.33 | 0.5 / 1.3 ms | 0.00 s | 32464896 bytes |
| gliclass | development | 12 | failed | 0/2/10 | completed=0, review=2, exhausted_budget=0, invalid_proposal=10, tool_failure=0 | 10 | 0/7 | 1/5 | 0 | 1 | 20 | 0 | 0 | 0 | 0 | 0.58 | 234.0 / 644.0 ms | 5.84 s | 867004416 bytes |
| gliclass_evidence_masked | development | 12 | passed | 4/8/0 | completed=4, review=8, exhausted_budget=0, invalid_proposal=0, tool_failure=0 | 0 | 4/7 | 5/5 | 0 | 3 | 0 | 0 | 0 | 0 | 0 | 1.75 | 406.4 / 821.5 ms | 5.84 s | 880500736 bytes |

`correct_supported_diagnoses` requires the terminal action to match the gold diagnosis, the harness to accept it, and cited visible evidence to match a gold evidence alternative. `correct_review_decisions` counts review outcomes for review-required scenarios. `incorrect_diagnoses` counts any terminal diagnosis different from the gold terminal action; `unnecessary_review_on_diagnosable_cases` counts review choices on diagnosable scenarios. Terminal-status counts and terminal-reason counts each sum to episode count. `failed_episodes` counts terminal status `failed`; `unsupported_diagnosis_proposals` counts evidence-check rejections, while `invalid_proposals_rejected` counts malformed, out-of-candidate, or otherwise harness-invalid outputs. `run_status` is failed whenever any episode fails. Policy execution errors and simulator failures are reported separately. Review-everything therefore has zero supported diagnoses and its unnecessary reviews remain visible. Tool fixture timeouts/errors are observations, not simulator failures.

Policies receive the same scenario reports and harness action eligibility. The evidence-masked variant removes diagnoses unsupported by observations collected so far; this does not prove that unrequested tools contain no additional faults. Fixture execution latency is not live tool latency.

See `provenance.json` for code/scenario hashes, package versions, model pin, runtime, candidate order, and budgets. Each policy summary has episode outcomes; `traces/` contains one JSONL replay trace per episode. `examples/fixed-order-database-example.jsonl` is a compact example.
