# Recorded diagnostic workflow evaluation

> Offline synthetic simulation. Fixture tools return recorded observations; no shell command, live service, or host action is executed.

| Policy | Split | Supported diagnoses | Correct reviews | Incorrect diagnoses | Unnecessary review | Unsupported diagnosis proposals | Invalid proposals | Policy errors | Budget exhausted | Tool failures | Tool calls mean | Latency p50 / p95 | Model load | Peak RSS |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| fixed_order | development | 7/7 | 5/5 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 4.00 | 0.6 / 0.8 ms | 0.00 s | 31858688 bytes |
| fixed_order | evaluation | 6/6 | 6/6 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 4.00 | 0.6 / 0.6 ms | 0.00 s | 31858688 bytes |
| rules | development | 7/7 | 4/5 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 2.33 | 0.3 / 0.8 ms | 0.00 s | 31858688 bytes |
| rules | evaluation | 6/6 | 5/6 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 2.25 | 0.3 / 0.9 ms | 0.00 s | 31858688 bytes |
| gliclass | development | 0/7 | 1/5 | 0 | 1 | 20 | 0 | 0 | 0 | 0 | 0.58 | 316.4 / 717.5 ms | 6.18 s | 871301120 bytes |
| gliclass | evaluation | 1/6 | 1/6 | 0 | 1 | 18 | 0 | 0 | 0 | 0 | 0.75 | 253.8 / 701.1 ms | 6.18 s | 871301120 bytes |

Diagnosable and review-required cases use separate denominators. Review-everything is therefore visible as unnecessary review and zero supported diagnoses. Policies received the same initial reports and could request only tools or terminal choices allowed by the harness. Tool fixture timeouts/errors are observations, not simulator failures.

See `provenance.json` for code/scenario hashes, package versions, model pin, runtime, candidate order, and budgets. Each policy summary has episode outcomes; `traces/` contains one JSONL replay trace per episode. `examples/fixed-order-database-example.jsonl` is a compact example.
