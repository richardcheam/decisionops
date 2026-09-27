# Development evaluation: rules

Generated: 2026-09-27T15:01:12.222113+00:00

> Hand-authored development data only. These measurements are not a held-out benchmark, production accuracy estimate, or definitive speed/quality comparison.

- Cases: 48 (SHA-256 `31de62142dba63480d78c4837323aee3063ca6cf6bae836d3cee6c651c40b6cd`)
- Unambiguous labeled cases: 31/32 correct; accuracy 0.969; coverage 0.969
- Labeled challenge cases: 4/7 correct
- Review cases: 9 abstained / 9 total; 0 forced predictions
- Model loading: 2.40 ms
- Inference: N=48, p50=22.9 µs, p95=44.6 µs
- Peak worker RSS: 21618688 bytes (whole process)

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
| challenge-04 | challenge, negation | database_failure | False | database_failure | A current database failure is explicit despite the negated health claim. |
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

## Provenance

- Git HEAD: `bc56acb51110bec8e1bfc92905c041caaf0245d1`; dirty: `True`
- Implementation hashes: `{"data/build_dataset.py": "7b367fb7e9e20258a80a143c7bcd70ed15a92365d68a085662f4295076388ef9", "decisionops/__init__.py": "332a002fc4f1a583d06cf3a3096174b7a39502bce106b088f9df41696b91ed81", "decisionops/backends.py": "6dec626cae745bb238d79a4f86bad6e5ebce56b5f9986fdd373343fdaa1e253e", "decisionops/dataset.py": "68b89916808d9a4ec549b2fbc3fca86d29eefe5200e0ddf19b40e5cf67f4d5ad", "decisionops/metrics.py": "157e62dd3c8546a2454aed3eb0cc5c2847d2974cedcf9a962d3fab1f6be0096b", "decisionops/rules.py": "5a69b08ce48963218f83d988dca5c6f587c4a08ebfa6b412d788d303a12862ba", "decisionops/runner.py": "0fea4110d935ad541d1c7cdc5e77d6664e9939b60146a5234404deacbe911cbc"}`
- Versions: `{"decisionops": "0.1.0", "gliclass": "0.1.20", "huggingface-hub": "1.33.0", "laya": "0.3.20", "torch": "2.14.0+cpu", "transformers": "5.17.0"}`
- Model revision: `None`
- Candidate representation: `{"format": "canonical candidate specifications", "ordered_values": [{"description": "Database connections fail or time out.", "id": "database_failure", "name": "Database failure"}, {"description": "Access fails because credentials are invalid.", "id": "authentication_failure", "name": "Authentication failure"}, {"description": "Storage is exhausted and writes fail.", "id": "disk_full", "name": "Disk full"}, {"description": "The service operates normally without errors.", "id": "healthy", "name": "Healthy"}]}`
- Runtime: `{"hardware": {"cpu_count": 12, "gpu": ["NVIDIA GeForce GTX 1050 Ti with Max-Q Design, 4096 MiB"], "platform": "Linux-7.0.0-34-generic-x86_64-with-glibc2.39", "processor": "x86_64", "ram_total_bytes": 8157687808}, "platform": "Linux-7.0.0-34-generic-x86_64-with-glibc2.39", "python": "3.12.14", "threads": {"batch_size": 1, "pytorch_cpu_threads": null}}`
- Score semantics: No probabilities are produced.
