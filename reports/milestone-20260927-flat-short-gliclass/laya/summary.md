# Development evaluation: laya

Generated: 2026-09-27T15:22:58.800832+00:00

> Hand-authored development data only. These measurements are not a held-out benchmark, production accuracy estimate, or definitive speed/quality comparison.

- Cases: 48 (SHA-256 `31de62142dba63480d78c4837323aee3063ca6cf6bae836d3cee6c651c40b6cd`)
- Unambiguous labeled cases: 30/32 correct; accuracy 0.938; coverage 1.000
- Labeled challenge cases: 3/7 correct
- Review cases: 0 abstained / 9 total; 9 forced predictions
- Model loading: 6435.83 ms
- Inference: N=48, p50=598.47 ms, p95=707.27 ms
- Peak worker RSS: 3039322112 bytes (whole process)

## Confusion matrix

Rows are expected classes; columns are predictions plus abstain.

| Expected \ Predicted | database_failure | authentication_failure | disk_full | healthy | abstain |
|---|---:|---:|---:|---:|---:|
| database_failure | 8 | 0 | 0 | 0 | 0 |
| authentication_failure | 0 | 7 | 0 | 1 | 0 |
| disk_full | 1 | 0 | 7 | 0 | 0 |
| healthy | 0 | 0 | 0 | 8 | 0 |

## Challenge cases

| ID | Tags | Expected | Review | Predicted | Annotation rationale |
|---|---|---|---:|---|---|
| challenge-01 | challenge, negation | healthy | False | database_failure | Negation explicitly denies a current database failure. |
| challenge-02 | challenge, negation | healthy | False | healthy | The credential rejection is negated. |
| challenge-03 | challenge, negation | healthy | False | healthy | The disk-full cue is explicitly denied. |
| challenge-04 | challenge, negation | database_failure | False | database_failure | A current database failure is explicit despite the negated health claim. |
| challenge-05 | challenge, historical | healthy | False | database_failure | The failure is historical and explicitly resolved; no current issue is labeled. |
| challenge-06 | challenge, historical | healthy | False | disk_full | The past fault is resolved and current writes succeed. |
| challenge-07 | challenge, historical | healthy | False | authentication_failure | Only historical authentication errors are reported; current state is successful. |
| challenge-08 | challenge, ambiguous_evidence | — | True | healthy | Slowness alone does not identify a database failure; needs review. |
| challenge-09 | challenge, ambiguous_evidence | — | True | disk_full | High utilization does not establish exhausted storage. |
| challenge-10 | challenge, ambiguous_evidence | — | True | healthy | Access trouble has no credential-specific evidence; needs review. |
| challenge-11 | challenge, multiple_faults | — | True | database_failure | Two simultaneous categories are explicit; needs review. |
| challenge-12 | challenge, multiple_faults | — | True | database_failure | Two simultaneous categories are explicit; needs review. |
| challenge-13 | challenge, unrelated | — | True | healthy | Unrelated request provides no service condition; needs review. |
| challenge-14 | challenge, unrelated | — | True | database_failure | Non-incident input is outside the four labels; needs review. |
| challenge-15 | challenge, insufficient_evidence | — | True | database_failure | No category or current state can be inferred. |
| challenge-16 | challenge, insufficient_evidence | — | True | healthy | Subjective vague report lacks classifiable evidence. |

## Provenance

- Git HEAD: `c9913f2b33c00575c6e398e072e25a589be8f433`; dirty: `True`
- Implementation hashes: `{"data/build_dataset.py": "7b367fb7e9e20258a80a143c7bcd70ed15a92365d68a085662f4295076388ef9", "decisionops/__init__.py": "332a002fc4f1a583d06cf3a3096174b7a39502bce106b088f9df41696b91ed81", "decisionops/backends.py": "a28b2b70c26c5782ce548b6400adb002e83517ad243e78e9e07172adbc2e9ac5", "decisionops/dataset.py": "68b89916808d9a4ec549b2fbc3fca86d29eefe5200e0ddf19b40e5cf67f4d5ad", "decisionops/metrics.py": "157e62dd3c8546a2454aed3eb0cc5c2847d2974cedcf9a962d3fab1f6be0096b", "decisionops/rules.py": "5a69b08ce48963218f83d988dca5c6f587c4a08ebfa6b412d788d303a12862ba", "decisionops/runner.py": "bc54ab9f59687f892ab5603f29ee7cde6aff0a2c83934373d6bf6edecb2400ab"}`
- Versions: `{"decisionops": "0.1.0", "gliclass": "0.1.20", "huggingface-hub": "1.33.0", "laya": "0.3.20", "torch": "2.14.0+cpu", "transformers": "5.17.0"}`
- Model revision: `55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851`
- Candidate representation: `{"incident": {"criteria": {"Authentication failure": "Access fails because credentials are invalid.", "Database failure": "Database connections fail or time out.", "Disk full": "Storage is exhausted and writes fail.", "Healthy": "The service operates normally without errors."}, "instructions": "Which category best describes the service condition?", "type": "choice"}}`
- Runtime: `{"hardware": {"cpu_count": 12, "gpu": ["NVIDIA GeForce GTX 1050 Ti with Max-Q Design, 4096 MiB"], "platform": "Linux-7.0.0-34-generic-x86_64-with-glibc2.39", "processor": "x86_64", "ram_total_bytes": 8157687808}, "platform": "Linux-7.0.0-34-generic-x86_64-with-glibc2.39", "python": "3.12.14", "threads": {"batch_size": 1, "pytorch_cpu_threads": 4}}`
- Score semantics: Native class probabilities, confidence, answer_confidence, and action_act_probability are retained separately; the action head is not authorization. Not calibrated validation.
