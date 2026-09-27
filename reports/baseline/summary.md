# Development evaluation: rules

Generated: 2026-09-27T13:18:26.399824+00:00

> Hand-authored development data only. These measurements are not a held-out benchmark, production accuracy estimate, or definitive speed/quality comparison.

- Cases: 48 (SHA-256 `9b799964facf378a6487610b382a51b70d7aa41d5b4c71bfa2332ce66106a119`)
- Unambiguous labeled cases: 32
- Accuracy (abstentions count as incorrect): 0.969
- Coverage: 0.969
- Model loading seconds: 0.005
- Warm-up calls excluded: 0
- Inference samples: 48
- Inference p50/p95 seconds: 0.0000 / 0.0000
- Peak worker RSS bytes: 32317440 (whole process, not just model)

## Confusion matrix

Rows are expected classes; columns are predictions plus abstain.

| Expected \ Predicted | database_failure | authentication_failure | disk_full | healthy | abstain |
|---|---:|---:|---:|---:|---:|
| database_failure | 8 | 0 | 0 | 0 | 0 |
| authentication_failure | 0 | 8 | 0 | 0 | 0 |
| disk_full | 0 | 0 | 7 | 0 | 1 |
| healthy | 0 | 0 | 0 | 8 | 0 |

## Challenge cases

| ID | Tags | Expected | Review | Predicted | Annotation rationale |
|---|---|---|---:|---|---|
| challenge-01 | challenge, negation | healthy | False | healthy | Negation explicitly denies a current database failure. |
| challenge-02 | challenge, negation | healthy | False | healthy | The credential rejection is negated. |
| challenge-03 | challenge, negation | healthy | False | healthy | The disk-full cue is explicitly denied. |
| challenge-04 | challenge, negation | healthy | False | database_failure | A current database failure is explicit despite the negated health claim. |
| challenge-05 | challenge, historical | healthy | False | abstain | The failure is historical and explicitly resolved; no current issue is labeled. |
| challenge-06 | challenge, historical | healthy | False | abstain | The past fault is resolved and current writes succeed. |
| challenge-07 | challenge, historical | healthy | False | abstain | Only historical authentication errors are reported; current state is successful. |
| challenge-08 | challenge, ambiguous_evidence | — | True | abstain | Slowness alone does not identify a database failure; needs review. |
| challenge-09 | challenge, ambiguous_evidence | — | True | abstain | High utilization does not establish exhausted storage. |
| challenge-10 | challenge, ambiguous_evidence | — | True | abstain | Access trouble has no credential-specific evidence; needs review. |
| challenge-11 | challenge, multiple_faults | — | True | abstain | Two simultaneous categories are explicit; needs review. |
| challenge-12 | challenge, multiple_faults | — | True | abstain | Two simultaneous categories are explicit; needs review. |
| challenge-13 | challenge, unrelated | — | True | abstain | Unrelated request provides no service condition; needs review. |
| challenge-14 | challenge, unrelated | — | True | abstain | Non-incident input is outside the four labels; needs review. |
| challenge-15 | challenge, insufficient_evidence | — | True | abstain | No category or current state can be inferred. |
| challenge-16 | challenge, insufficient_evidence | — | True | abstain | Subjective vague report lacks classifiable evidence. |

## Run metadata

- Versions: `{"decisionops": "0.1.0", "gliclass": "0.1.20", "huggingface-hub": "1.33.0", "laya": "0.3.20", "torch": "2.14.0+cpu", "transformers": "5.17.0"}`
- Model revision: `None`
- Hardware: `{"cpu_count": 12, "gpu": ["NVIDIA GeForce GTX 1050 Ti with Max-Q Design, 4096 MiB"], "platform": "Linux-7.0.0-34-generic-x86_64-with-glibc2.39", "processor": "x86_64", "ram_total_bytes": 8157687808}`
- Score semantics: No probabilities are produced.
