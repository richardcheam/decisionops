# Sequential development evaluation

Workers ran one at a time. These hand-authored examples are development data, not a held-out benchmark.

| Backend | Core correct/total | Accuracy | Coverage | Labeled challenge | Review abstained/total | Inference N | p50 | p95 | Model load | Peak RSS |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| rules | 31/32 | 0.969 | 0.969 | 4/7 | 9/9 | 48 | 21.8 µs | 38.7 µs | 2.39 ms | 21647360 bytes |
| gliclass | 31/32 | 0.969 | 1.000 | 3/7 | 0/9 | 48 | 85.31 ms | 90.74 ms | 6287.13 ms | 828891136 bytes |
| laya | 30/32 | 0.938 | 1.000 | 3/7 | 0/9 | 48 | 598.47 ms | 707.27 ms | 6435.83 ms | 3039322112 bytes |

## Worker status

- **rules**: completed (exit 0); `reports/milestone-20260927-flat-short-gliclass/rules`
- **gliclass**: completed (exit 0); `reports/milestone-20260927-flat-short-gliclass/gliclass`
- **laya**: completed (exit 0); `reports/milestone-20260927-flat-short-gliclass/laya`

## Core misses and disagreements

Core misses list labeled development cases where each backend predicted incorrectly or abstained.

| Backend | Missed core case IDs |
|---|---|
| rules | core-disk_full-05 |
| gliclass | core-disk_full-04 |
| laya | core-authentication_failure-02, core-disk_full-04 |

Cases with differing predictions across backends:

| Case | Expected | Review | Rules | GLiClass | Laya |
|---|---|---:|---|---|---|
| core-authentication_failure-02 | authentication_failure | False | authentication_failure | authentication_failure | healthy |
| core-disk_full-04 | disk_full | False | disk_full | database_failure | database_failure |
| core-disk_full-05 | disk_full | False | abstain | disk_full | disk_full |
| challenge-01 | healthy | False | healthy | healthy | database_failure |
| challenge-03 | healthy | False | healthy | database_failure | healthy |
| challenge-05 | healthy | False | abstain | database_failure | database_failure |
| challenge-06 | healthy | False | abstain | disk_full | disk_full |
| challenge-07 | healthy | False | abstain | authentication_failure | authentication_failure |
| challenge-08 | — | True | abstain | healthy | healthy |
| challenge-09 | — | True | abstain | healthy | disk_full |
| challenge-10 | — | True | abstain | authentication_failure | healthy |
| challenge-11 | — | True | abstain | database_failure | database_failure |
| challenge-12 | — | True | abstain | database_failure | database_failure |
| challenge-13 | — | True | abstain | healthy | healthy |
| challenge-14 | — | True | abstain | healthy | database_failure |
| challenge-15 | — | True | abstain | database_failure | database_failure |
| challenge-16 | — | True | abstain | healthy | healthy |

## Reading the results

Core accuracy counts abstentions as incorrect; coverage reports the share receiving a class. Labeled challenge rows have explicit labels and are scored separately. Review rows have no target class: only abstentions and forced predictions are counted. p50/p95 use prediction calls after the excluded warm-up. These 48 authored cases are small and do not establish general model quality.
