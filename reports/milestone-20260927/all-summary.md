# Sequential development evaluation

Workers ran one at a time. These hand-authored examples are development data, not a held-out benchmark.

| Backend | Core correct/total | Accuracy | Coverage | Labeled challenge | Review abstained/total | Inference N | p50 | p95 | Model load | Peak RSS |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| rules | 31/32 | 0.969 | 0.969 | 4/7 | 9/9 | 48 | 22.9 µs | 44.6 µs | 2.40 ms | 21618688 bytes |
| gliclass | 10/32 | 0.312 | 1.000 | 1/7 | 0/9 | 48 | 110.26 ms | 120.58 ms | 6384.00 ms | 843587584 bytes |
| laya | 30/32 | 0.938 | 1.000 | 3/7 | 0/9 | 48 | 583.10 ms | 665.42 ms | 6005.62 ms | 3038326784 bytes |

## Worker status

- **rules**: completed (exit 0); `reports/milestone-20260927/rules`
- **gliclass**: completed (exit 0); `reports/milestone-20260927/gliclass`
- **laya**: completed (exit 0); `reports/milestone-20260927/laya`

## Core misses and disagreements

Core misses list labeled development cases where each backend predicted incorrectly or abstained.

| Backend | Missed core case IDs |
|---|---|
| rules | core-disk_full-05 |
| gliclass | core-authentication_failure-01, core-authentication_failure-02, core-authentication_failure-04, core-authentication_failure-05, core-authentication_failure-06, core-authentication_failure-08, core-disk_full-01, core-disk_full-02, core-disk_full-03, core-disk_full-04, core-disk_full-05, core-disk_full-06, core-disk_full-07, core-disk_full-08, core-healthy-01, core-healthy-02, core-healthy-03, core-healthy-04, core-healthy-05, core-healthy-06, core-healthy-07, core-healthy-08 |
| laya | core-authentication_failure-02, core-disk_full-04 |

Cases with differing predictions across backends:

| Case | Expected | Review | Rules | GLiClass | Laya |
|---|---|---:|---|---|---|
| core-authentication_failure-01 | authentication_failure | False | authentication_failure | database_failure | authentication_failure |
| core-authentication_failure-02 | authentication_failure | False | authentication_failure | database_failure | healthy |
| core-authentication_failure-04 | authentication_failure | False | authentication_failure | database_failure | authentication_failure |
| core-authentication_failure-05 | authentication_failure | False | authentication_failure | database_failure | authentication_failure |
| core-authentication_failure-06 | authentication_failure | False | authentication_failure | database_failure | authentication_failure |
| core-authentication_failure-08 | authentication_failure | False | authentication_failure | database_failure | authentication_failure |
| core-disk_full-01 | disk_full | False | disk_full | database_failure | disk_full |
| core-disk_full-02 | disk_full | False | disk_full | database_failure | disk_full |
| core-disk_full-03 | disk_full | False | disk_full | database_failure | disk_full |
| core-disk_full-04 | disk_full | False | disk_full | database_failure | database_failure |
| core-disk_full-05 | disk_full | False | abstain | database_failure | disk_full |
| core-disk_full-06 | disk_full | False | disk_full | database_failure | disk_full |
| core-disk_full-07 | disk_full | False | disk_full | database_failure | disk_full |
| core-disk_full-08 | disk_full | False | disk_full | database_failure | disk_full |
| core-healthy-01 | healthy | False | healthy | database_failure | healthy |
| core-healthy-02 | healthy | False | healthy | database_failure | healthy |
| core-healthy-03 | healthy | False | healthy | database_failure | healthy |
| core-healthy-04 | healthy | False | healthy | database_failure | healthy |
| core-healthy-05 | healthy | False | healthy | database_failure | healthy |
| core-healthy-06 | healthy | False | healthy | database_failure | healthy |
| core-healthy-07 | healthy | False | healthy | database_failure | healthy |
| core-healthy-08 | healthy | False | healthy | database_failure | healthy |
| challenge-01 | healthy | False | healthy | database_failure | database_failure |
| challenge-02 | healthy | False | healthy | database_failure | healthy |
| challenge-03 | healthy | False | healthy | database_failure | healthy |
| challenge-05 | healthy | False | abstain | database_failure | database_failure |
| challenge-06 | healthy | False | abstain | database_failure | disk_full |
| challenge-07 | healthy | False | abstain | database_failure | authentication_failure |
| challenge-08 | — | True | abstain | database_failure | healthy |
| challenge-09 | — | True | abstain | database_failure | disk_full |
| challenge-10 | — | True | abstain | database_failure | healthy |
| challenge-11 | — | True | abstain | database_failure | database_failure |
| challenge-12 | — | True | abstain | database_failure | database_failure |
| challenge-13 | — | True | abstain | database_failure | healthy |
| challenge-14 | — | True | abstain | database_failure | database_failure |
| challenge-15 | — | True | abstain | database_failure | database_failure |
| challenge-16 | — | True | abstain | database_failure | healthy |

## Reading the results

Core accuracy counts abstentions as incorrect; coverage reports the share receiving a class. Labeled challenge rows have explicit labels and are scored separately. Review rows have no target class: only abstentions and forced predictions are counted. p50/p95 use prediction calls after the excluded warm-up. These 48 authored cases are small and do not establish general model quality.
