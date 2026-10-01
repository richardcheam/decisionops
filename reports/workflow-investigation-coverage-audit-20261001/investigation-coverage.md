# Investigation coverage audit

**Offline, model-free audit of the committed synthetic comparison.** Coverage is based on recorded trace observations; correctness remains the report's evaluator outcome.

Source report: `workflow-model-comparison-20260927` · scenario SHA-256 verified: `087c6e243c5df89c56e22ef0d081b0a1667ef44dc160d66058ab6ef571db2bc0` · replayed traces: 144/144.

## Definitions

An episode has **all-four current coverage** when each of the four tools returned a successful observation with `time_scope=current`. Historical, timeout, and error observations are listed separately and do not count toward coverage. Missing tool observations are not treated as healthy or faulty.

Correct diagnoses use the existing evaluator definition: terminal diagnosis equals the scenario gold action, termination reason is `completed`, and recorded gold evidence is supported. Incorrect diagnoses use the existing metric: a terminal diagnosis differs from the gold terminal action. Reviews count terminal `request_review` actions; failed episodes use replayed terminal status `failed`. A separate residual exposes any unusual outcome outside those four groups.

Successful current observations measure how much of the fixture was checked. They do not guarantee informative facts, a complete diagnosis, or correctness. Fewer tool calls do not automatically mean greater efficiency: this audit does not assign utility to latency, risk, or missed faults, and tool calls have no live operational cost here.

## Coverage and evaluator outcomes

Correct diagnoses are shown as count / diagnosable episodes within that coverage group. Other outcomes use count / all episodes in the group. `n` is the episode denominator; empty groups have no rate.

| Policy | Split | Coverage | n | Correct diagnoses / diagnosable | Incorrect diagnoses / n | Reviews / n | Failed / n | Other / n |
|---|---|---|---:|---:|---:|---:|---:|---:|
| `fixed_order` | development | partial | 1 | 0 / 0 | 0 / 1 | 1 / 1 | 0 / 1 | 0 / 1 |
| `fixed_order` | development | all four | 11 | 7 / 7 | 0 / 11 | 4 / 11 | 0 / 11 | 0 / 11 |
| `fixed_order` | evaluation | partial | 2 | 0 / 0 | 0 / 2 | 2 / 2 | 0 / 2 | 0 / 2 |
| `fixed_order` | evaluation | all four | 10 | 6 / 6 | 0 / 10 | 4 / 10 | 0 / 10 | 0 / 10 |
| `rules` | development | partial | 7 | 5 / 5 | 1 / 7 | 1 / 7 | 0 / 7 | 0 / 7 |
| `rules` | development | all four | 5 | 2 / 2 | 0 / 5 | 3 / 5 | 0 / 5 | 0 / 5 |
| `rules` | evaluation | partial | 7 | 4 / 4 | 1 / 7 | 2 / 7 | 0 / 7 | 0 / 7 |
| `rules` | evaluation | all four | 5 | 2 / 2 | 0 / 5 | 3 / 5 | 0 / 5 | 0 / 5 |
| `gliclass` | development | partial | 12 | 0 / 7 | 0 / 12 | 2 / 12 | 10 / 12 | 0 / 12 |
| `gliclass` | development | all four | 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| `gliclass` | evaluation | partial | 12 | 1 / 6 | 0 / 12 | 2 / 12 | 9 / 12 | 0 / 12 |
| `gliclass` | evaluation | all four | 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| `gliclass_evidence_masked` | development | partial | 11 | 4 / 7 | 0 / 11 | 7 / 11 | 0 / 11 | 0 / 11 |
| `gliclass_evidence_masked` | development | all four | 1 | 0 / 0 | 0 / 1 | 1 / 1 | 0 / 1 | 0 / 1 |
| `gliclass_evidence_masked` | evaluation | partial | 12 | 2 / 6 | 1 / 12 | 9 / 12 | 0 / 12 | 0 / 12 |
| `gliclass_evidence_masked` | evaluation | all four | 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| `laya` | development | partial | 12 | 0 / 7 | 0 / 12 | 0 / 12 | 12 / 12 | 0 / 12 |
| `laya` | development | all four | 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| `laya` | evaluation | partial | 12 | 0 / 6 | 0 / 12 | 0 / 12 | 12 / 12 | 0 / 12 |
| `laya` | evaluation | all four | 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| `laya_evidence_masked` | development | partial | 10 | 3 / 5 | 1 / 10 | 6 / 10 | 0 / 10 | 0 / 10 |
| `laya_evidence_masked` | development | all four | 2 | 2 / 2 | 0 / 2 | 0 / 2 | 0 / 2 | 0 / 2 |
| `laya_evidence_masked` | evaluation | partial | 10 | 3 / 6 | 1 / 10 | 6 / 10 | 0 / 10 | 0 / 10 |
| `laya_evidence_masked` | evaluation | all four | 2 | 0 / 0 | 0 / 2 | 2 / 2 | 0 / 2 | 0 / 2 |

## Interpretation

Across 144 policy-episode runs, 108 ended without all four successful current observations; 22 were evaluator-correct diagnoses, 5 were incorrect diagnoses, 38 ended in review, and 43 were failed episodes. Failed episodes are not necessarily deliberate early-stop choices; they include traces whose harness outcome was failure. The accepted diagnosis/review actions are policy choices, while action eligibility and evidence support are deterministic harness checks. The 5 incomplete-coverage incorrect diagnoses support studying a stricter stopping rule as a separate question. They do not establish that such a rule would improve outcomes; no stopping behavior was changed or evaluated here.

The traces show only report text, requested observations, tool attempts, and recorded budgets. The section below is evaluator-only hindsight: the policy did not see unrequested observations. Its annotations use only exact structured current facts that match the existing workflow evidence rules; free-text fixture messages are not interpreted.

## Per-episode trace evidence

Links open the recorded JSONL traces. Each row lists the observed coverage and terminal result; hidden fixture annotations are kept in the evaluator-only section below.

| Policy | Split / scenario | Coverage | Terminal action / reason | Evaluator outcome | Trace |
|---|---|---|---|---|---|
| `fixed_order` | development / `dev-authentication-clear` | all four | `diagnose_authentication_failure` / `completed` | correct_diagnoses | [fixed_order dev-002](../workflow-model-comparison-20260927/traces/fixed_order/dev-002.jsonl) |
| `rules` | development / `dev-authentication-clear` | partial | `diagnose_authentication_failure` / `completed` | correct_diagnoses | [rules dev-002](../workflow-model-comparison-20260927/traces/rules/dev-002.jsonl) |
| `gliclass` | development / `dev-authentication-clear` | partial | `none` / `invalid_proposal` | failed_episodes | [gliclass dev-002](../workflow-model-comparison-20260927/traces/gliclass/dev-002.jsonl) |
| `gliclass_evidence_masked` | development / `dev-authentication-clear` | partial | `diagnose_authentication_failure` / `completed` | correct_diagnoses | [gliclass_evidence_masked dev-002](../workflow-model-comparison-20260927/traces/gliclass_evidence_masked/dev-002.jsonl) |
| `laya` | development / `dev-authentication-clear` | partial | `none` / `invalid_proposal` | failed_episodes | [laya dev-002](../workflow-model-comparison-20260927/traces/laya/dev-002.jsonl) |
| `laya_evidence_masked` | development / `dev-authentication-clear` | partial | `diagnose_authentication_failure` / `completed` | correct_diagnoses | [laya_evidence_masked dev-002](../workflow-model-comparison-20260927/traces/laya_evidence_masked/dev-002.jsonl) |
| `fixed_order` | development / `dev-contradictory-evidence` | all four | `request_review` / `review` | reviews | [fixed_order dev-008](../workflow-model-comparison-20260927/traces/fixed_order/dev-008.jsonl) |
| `rules` | development / `dev-contradictory-evidence` | partial | `diagnose_database_failure` / `completed` | incorrect_diagnoses | [rules dev-008](../workflow-model-comparison-20260927/traces/rules/dev-008.jsonl) |
| `gliclass` | development / `dev-contradictory-evidence` | partial | `none` / `invalid_proposal` | failed_episodes | [gliclass dev-008](../workflow-model-comparison-20260927/traces/gliclass/dev-008.jsonl) |
| `gliclass_evidence_masked` | development / `dev-contradictory-evidence` | partial | `request_review` / `review` | reviews | [gliclass_evidence_masked dev-008](../workflow-model-comparison-20260927/traces/gliclass_evidence_masked/dev-008.jsonl) |
| `laya` | development / `dev-contradictory-evidence` | partial | `none` / `invalid_proposal` | failed_episodes | [laya dev-008](../workflow-model-comparison-20260927/traces/laya/dev-008.jsonl) |
| `laya_evidence_masked` | development / `dev-contradictory-evidence` | partial | `request_review` / `review` | reviews | [laya_evidence_masked dev-008](../workflow-model-comparison-20260927/traces/laya_evidence_masked/dev-008.jsonl) |
| `fixed_order` | development / `dev-database-clear` | all four | `diagnose_database_failure` / `completed` | correct_diagnoses | [fixed_order dev-001](../workflow-model-comparison-20260927/traces/fixed_order/dev-001.jsonl) |
| `rules` | development / `dev-database-clear` | partial | `diagnose_database_failure` / `completed` | correct_diagnoses | [rules dev-001](../workflow-model-comparison-20260927/traces/rules/dev-001.jsonl) |
| `gliclass` | development / `dev-database-clear` | partial | `none` / `invalid_proposal` | failed_episodes | [gliclass dev-001](../workflow-model-comparison-20260927/traces/gliclass/dev-001.jsonl) |
| `gliclass_evidence_masked` | development / `dev-database-clear` | partial | `diagnose_database_failure` / `completed` | correct_diagnoses | [gliclass_evidence_masked dev-001](../workflow-model-comparison-20260927/traces/gliclass_evidence_masked/dev-001.jsonl) |
| `laya` | development / `dev-database-clear` | partial | `none` / `invalid_proposal` | failed_episodes | [laya dev-001](../workflow-model-comparison-20260927/traces/laya/dev-001.jsonl) |
| `laya_evidence_masked` | development / `dev-database-clear` | partial | `diagnose_database_failure` / `completed` | correct_diagnoses | [laya_evidence_masked dev-001](../workflow-model-comparison-20260927/traces/laya_evidence_masked/dev-001.jsonl) |
| `fixed_order` | development / `dev-database-timeout` | partial | `request_review` / `review` | reviews | [fixed_order dev-009](../workflow-model-comparison-20260927/traces/fixed_order/dev-009.jsonl) |
| `rules` | development / `dev-database-timeout` | partial | `request_review` / `review` | reviews | [rules dev-009](../workflow-model-comparison-20260927/traces/rules/dev-009.jsonl) |
| `gliclass` | development / `dev-database-timeout` | partial | `none` / `invalid_proposal` | failed_episodes | [gliclass dev-009](../workflow-model-comparison-20260927/traces/gliclass/dev-009.jsonl) |
| `gliclass_evidence_masked` | development / `dev-database-timeout` | partial | `request_review` / `review` | reviews | [gliclass_evidence_masked dev-009](../workflow-model-comparison-20260927/traces/gliclass_evidence_masked/dev-009.jsonl) |
| `laya` | development / `dev-database-timeout` | partial | `none` / `invalid_proposal` | failed_episodes | [laya dev-009](../workflow-model-comparison-20260927/traces/laya/dev-009.jsonl) |
| `laya_evidence_masked` | development / `dev-database-timeout` | partial | `request_review` / `review` | reviews | [laya_evidence_masked dev-009](../workflow-model-comparison-20260927/traces/laya_evidence_masked/dev-009.jsonl) |
| `fixed_order` | development / `dev-healthy-clear` | all four | `diagnose_healthy` / `completed` | correct_diagnoses | [fixed_order dev-004](../workflow-model-comparison-20260927/traces/fixed_order/dev-004.jsonl) |
| `rules` | development / `dev-healthy-clear` | all four | `diagnose_healthy` / `completed` | correct_diagnoses | [rules dev-004](../workflow-model-comparison-20260927/traces/rules/dev-004.jsonl) |
| `gliclass` | development / `dev-healthy-clear` | partial | `none` / `invalid_proposal` | failed_episodes | [gliclass dev-004](../workflow-model-comparison-20260927/traces/gliclass/dev-004.jsonl) |
| `gliclass_evidence_masked` | development / `dev-healthy-clear` | partial | `request_review` / `review` | reviews | [gliclass_evidence_masked dev-004](../workflow-model-comparison-20260927/traces/gliclass_evidence_masked/dev-004.jsonl) |
| `laya` | development / `dev-healthy-clear` | partial | `none` / `invalid_proposal` | failed_episodes | [laya dev-004](../workflow-model-comparison-20260927/traces/laya/dev-004.jsonl) |
| `laya_evidence_masked` | development / `dev-healthy-clear` | partial | `request_review` / `review` | reviews | [laya_evidence_masked dev-004](../workflow-model-comparison-20260927/traces/laya_evidence_masked/dev-004.jsonl) |
| `fixed_order` | development / `dev-historical-resolved` | all four | `diagnose_healthy` / `completed` | correct_diagnoses | [fixed_order dev-006](../workflow-model-comparison-20260927/traces/fixed_order/dev-006.jsonl) |
| `rules` | development / `dev-historical-resolved` | all four | `diagnose_healthy` / `completed` | correct_diagnoses | [rules dev-006](../workflow-model-comparison-20260927/traces/rules/dev-006.jsonl) |
| `gliclass` | development / `dev-historical-resolved` | partial | `none` / `invalid_proposal` | failed_episodes | [gliclass dev-006](../workflow-model-comparison-20260927/traces/gliclass/dev-006.jsonl) |
| `gliclass_evidence_masked` | development / `dev-historical-resolved` | partial | `request_review` / `review` | reviews | [gliclass_evidence_masked dev-006](../workflow-model-comparison-20260927/traces/gliclass_evidence_masked/dev-006.jsonl) |
| `laya` | development / `dev-historical-resolved` | partial | `none` / `invalid_proposal` | failed_episodes | [laya dev-006](../workflow-model-comparison-20260927/traces/laya/dev-006.jsonl) |
| `laya_evidence_masked` | development / `dev-historical-resolved` | all four | `diagnose_healthy` / `completed` | correct_diagnoses | [laya_evidence_masked dev-006](../workflow-model-comparison-20260927/traces/laya_evidence_masked/dev-006.jsonl) |
| `fixed_order` | development / `dev-multiple-current-faults` | all four | `request_review` / `review` | reviews | [fixed_order dev-007](../workflow-model-comparison-20260927/traces/fixed_order/dev-007.jsonl) |
| `rules` | development / `dev-multiple-current-faults` | all four | `request_review` / `review` | reviews | [rules dev-007](../workflow-model-comparison-20260927/traces/rules/dev-007.jsonl) |
| `gliclass` | development / `dev-multiple-current-faults` | partial | `none` / `invalid_proposal` | failed_episodes | [gliclass dev-007](../workflow-model-comparison-20260927/traces/gliclass/dev-007.jsonl) |
| `gliclass_evidence_masked` | development / `dev-multiple-current-faults` | all four | `request_review` / `review` | reviews | [gliclass_evidence_masked dev-007](../workflow-model-comparison-20260927/traces/gliclass_evidence_masked/dev-007.jsonl) |
| `laya` | development / `dev-multiple-current-faults` | partial | `none` / `invalid_proposal` | failed_episodes | [laya dev-007](../workflow-model-comparison-20260927/traces/laya/dev-007.jsonl) |
| `laya_evidence_masked` | development / `dev-multiple-current-faults` | partial | `diagnose_authentication_failure` / `completed` | incorrect_diagnoses | [laya_evidence_masked dev-007](../workflow-model-comparison-20260927/traces/laya_evidence_masked/dev-007.jsonl) |
| `fixed_order` | development / `dev-next-tool-changes` | all four | `diagnose_authentication_failure` / `completed` | correct_diagnoses | [fixed_order dev-011](../workflow-model-comparison-20260927/traces/fixed_order/dev-011.jsonl) |
| `rules` | development / `dev-next-tool-changes` | partial | `diagnose_authentication_failure` / `completed` | correct_diagnoses | [rules dev-011](../workflow-model-comparison-20260927/traces/rules/dev-011.jsonl) |
| `gliclass` | development / `dev-next-tool-changes` | partial | `none` / `invalid_proposal` | failed_episodes | [gliclass dev-011](../workflow-model-comparison-20260927/traces/gliclass/dev-011.jsonl) |
| `gliclass_evidence_masked` | development / `dev-next-tool-changes` | partial | `diagnose_authentication_failure` / `completed` | correct_diagnoses | [gliclass_evidence_masked dev-011](../workflow-model-comparison-20260927/traces/gliclass_evidence_masked/dev-011.jsonl) |
| `laya` | development / `dev-next-tool-changes` | partial | `none` / `invalid_proposal` | failed_episodes | [laya dev-011](../workflow-model-comparison-20260927/traces/laya/dev-011.jsonl) |
| `laya_evidence_masked` | development / `dev-next-tool-changes` | all four | `diagnose_authentication_failure` / `completed` | correct_diagnoses | [laya_evidence_masked dev-011](../workflow-model-comparison-20260927/traces/laya_evidence_masked/dev-011.jsonl) |
| `fixed_order` | development / `dev-storage-clear` | all four | `diagnose_disk_full` / `completed` | correct_diagnoses | [fixed_order dev-003](../workflow-model-comparison-20260927/traces/fixed_order/dev-003.jsonl) |
| `rules` | development / `dev-storage-clear` | partial | `diagnose_disk_full` / `completed` | correct_diagnoses | [rules dev-003](../workflow-model-comparison-20260927/traces/rules/dev-003.jsonl) |
| `gliclass` | development / `dev-storage-clear` | partial | `none` / `invalid_proposal` | failed_episodes | [gliclass dev-003](../workflow-model-comparison-20260927/traces/gliclass/dev-003.jsonl) |
| `gliclass_evidence_masked` | development / `dev-storage-clear` | partial | `diagnose_disk_full` / `completed` | correct_diagnoses | [gliclass_evidence_masked dev-003](../workflow-model-comparison-20260927/traces/gliclass_evidence_masked/dev-003.jsonl) |
| `laya` | development / `dev-storage-clear` | partial | `none` / `invalid_proposal` | failed_episodes | [laya dev-003](../workflow-model-comparison-20260927/traces/laya/dev-003.jsonl) |
| `laya_evidence_masked` | development / `dev-storage-clear` | partial | `diagnose_disk_full` / `completed` | correct_diagnoses | [laya_evidence_masked dev-003](../workflow-model-comparison-20260927/traces/laya_evidence_masked/dev-003.jsonl) |
| `fixed_order` | development / `dev-unrelated` | all four | `request_review` / `review` | reviews | [fixed_order dev-012](../workflow-model-comparison-20260927/traces/fixed_order/dev-012.jsonl) |
| `rules` | development / `dev-unrelated` | all four | `request_review` / `review` | reviews | [rules dev-012](../workflow-model-comparison-20260927/traces/rules/dev-012.jsonl) |
| `gliclass` | development / `dev-unrelated` | partial | `request_review` / `review` | reviews | [gliclass dev-012](../workflow-model-comparison-20260927/traces/gliclass/dev-012.jsonl) |
| `gliclass_evidence_masked` | development / `dev-unrelated` | partial | `request_review` / `review` | reviews | [gliclass_evidence_masked dev-012](../workflow-model-comparison-20260927/traces/gliclass_evidence_masked/dev-012.jsonl) |
| `laya` | development / `dev-unrelated` | partial | `none` / `invalid_proposal` | failed_episodes | [laya dev-012](../workflow-model-comparison-20260927/traces/laya/dev-012.jsonl) |
| `laya_evidence_masked` | development / `dev-unrelated` | partial | `request_review` / `review` | reviews | [laya_evidence_masked dev-012](../workflow-model-comparison-20260927/traces/laya_evidence_masked/dev-012.jsonl) |
| `fixed_order` | development / `dev-vague-insufficient` | all four | `request_review` / `review` | reviews | [fixed_order dev-010](../workflow-model-comparison-20260927/traces/fixed_order/dev-010.jsonl) |
| `rules` | development / `dev-vague-insufficient` | all four | `request_review` / `review` | reviews | [rules dev-010](../workflow-model-comparison-20260927/traces/rules/dev-010.jsonl) |
| `gliclass` | development / `dev-vague-insufficient` | partial | `none` / `invalid_proposal` | failed_episodes | [gliclass dev-010](../workflow-model-comparison-20260927/traces/gliclass/dev-010.jsonl) |
| `gliclass_evidence_masked` | development / `dev-vague-insufficient` | partial | `request_review` / `review` | reviews | [gliclass_evidence_masked dev-010](../workflow-model-comparison-20260927/traces/gliclass_evidence_masked/dev-010.jsonl) |
| `laya` | development / `dev-vague-insufficient` | partial | `none` / `invalid_proposal` | failed_episodes | [laya dev-010](../workflow-model-comparison-20260927/traces/laya/dev-010.jsonl) |
| `laya_evidence_masked` | development / `dev-vague-insufficient` | partial | `request_review` / `review` | reviews | [laya_evidence_masked dev-010](../workflow-model-comparison-20260927/traces/laya_evidence_masked/dev-010.jsonl) |
| `fixed_order` | development / `dev-vague-to-database` | all four | `diagnose_database_failure` / `completed` | correct_diagnoses | [fixed_order dev-005](../workflow-model-comparison-20260927/traces/fixed_order/dev-005.jsonl) |
| `rules` | development / `dev-vague-to-database` | partial | `diagnose_database_failure` / `completed` | correct_diagnoses | [rules dev-005](../workflow-model-comparison-20260927/traces/rules/dev-005.jsonl) |
| `gliclass` | development / `dev-vague-to-database` | partial | `request_review` / `review` | reviews | [gliclass dev-005](../workflow-model-comparison-20260927/traces/gliclass/dev-005.jsonl) |
| `gliclass_evidence_masked` | development / `dev-vague-to-database` | partial | `request_review` / `review` | reviews | [gliclass_evidence_masked dev-005](../workflow-model-comparison-20260927/traces/gliclass_evidence_masked/dev-005.jsonl) |
| `laya` | development / `dev-vague-to-database` | partial | `none` / `invalid_proposal` | failed_episodes | [laya dev-005](../workflow-model-comparison-20260927/traces/laya/dev-005.jsonl) |
| `laya_evidence_masked` | development / `dev-vague-to-database` | partial | `request_review` / `review` | reviews | [laya_evidence_masked dev-005](../workflow-model-comparison-20260927/traces/laya_evidence_masked/dev-005.jsonl) |
| `fixed_order` | evaluation / `eval-auth-direct` | all four | `diagnose_authentication_failure` / `completed` | correct_diagnoses | [fixed_order eva-002](../workflow-model-comparison-20260927/traces/fixed_order/eva-002.jsonl) |
| `rules` | evaluation / `eval-auth-direct` | partial | `diagnose_authentication_failure` / `completed` | correct_diagnoses | [rules eva-002](../workflow-model-comparison-20260927/traces/rules/eva-002.jsonl) |
| `gliclass` | evaluation / `eval-auth-direct` | partial | `diagnose_authentication_failure` / `completed` | correct_diagnoses | [gliclass eva-002](../workflow-model-comparison-20260927/traces/gliclass/eva-002.jsonl) |
| `gliclass_evidence_masked` | evaluation / `eval-auth-direct` | partial | `diagnose_authentication_failure` / `completed` | correct_diagnoses | [gliclass_evidence_masked eva-002](../workflow-model-comparison-20260927/traces/gliclass_evidence_masked/eva-002.jsonl) |
| `laya` | evaluation / `eval-auth-direct` | partial | `none` / `invalid_proposal` | failed_episodes | [laya eva-002](../workflow-model-comparison-20260927/traces/laya/eva-002.jsonl) |
| `laya_evidence_masked` | evaluation / `eval-auth-direct` | partial | `diagnose_authentication_failure` / `completed` | correct_diagnoses | [laya_evidence_masked eva-002](../workflow-model-comparison-20260927/traces/laya_evidence_masked/eva-002.jsonl) |
| `fixed_order` | evaluation / `eval-authentication-timeout` | partial | `request_review` / `review` | reviews | [fixed_order eva-009](../workflow-model-comparison-20260927/traces/fixed_order/eva-009.jsonl) |
| `rules` | evaluation / `eval-authentication-timeout` | partial | `request_review` / `review` | reviews | [rules eva-009](../workflow-model-comparison-20260927/traces/rules/eva-009.jsonl) |
| `gliclass` | evaluation / `eval-authentication-timeout` | partial | `none` / `invalid_proposal` | failed_episodes | [gliclass eva-009](../workflow-model-comparison-20260927/traces/gliclass/eva-009.jsonl) |
| `gliclass_evidence_masked` | evaluation / `eval-authentication-timeout` | partial | `request_review` / `review` | reviews | [gliclass_evidence_masked eva-009](../workflow-model-comparison-20260927/traces/gliclass_evidence_masked/eva-009.jsonl) |
| `laya` | evaluation / `eval-authentication-timeout` | partial | `none` / `invalid_proposal` | failed_episodes | [laya eva-009](../workflow-model-comparison-20260927/traces/laya/eva-009.jsonl) |
| `laya_evidence_masked` | evaluation / `eval-authentication-timeout` | partial | `request_review` / `review` | reviews | [laya_evidence_masked eva-009](../workflow-model-comparison-20260927/traces/laya_evidence_masked/eva-009.jsonl) |
| `fixed_order` | evaluation / `eval-contradictory-evidence` | all four | `request_review` / `review` | reviews | [fixed_order eva-008](../workflow-model-comparison-20260927/traces/fixed_order/eva-008.jsonl) |
| `rules` | evaluation / `eval-contradictory-evidence` | all four | `request_review` / `review` | reviews | [rules eva-008](../workflow-model-comparison-20260927/traces/rules/eva-008.jsonl) |
| `gliclass` | evaluation / `eval-contradictory-evidence` | partial | `none` / `invalid_proposal` | failed_episodes | [gliclass eva-008](../workflow-model-comparison-20260927/traces/gliclass/eva-008.jsonl) |
| `gliclass_evidence_masked` | evaluation / `eval-contradictory-evidence` | partial | `request_review` / `review` | reviews | [gliclass_evidence_masked eva-008](../workflow-model-comparison-20260927/traces/gliclass_evidence_masked/eva-008.jsonl) |
| `laya` | evaluation / `eval-contradictory-evidence` | partial | `none` / `invalid_proposal` | failed_episodes | [laya eva-008](../workflow-model-comparison-20260927/traces/laya/eva-008.jsonl) |
| `laya_evidence_masked` | evaluation / `eval-contradictory-evidence` | all four | `request_review` / `review` | reviews | [laya_evidence_masked eva-008](../workflow-model-comparison-20260927/traces/laya_evidence_masked/eva-008.jsonl) |
| `fixed_order` | evaluation / `eval-database-direct` | all four | `diagnose_database_failure` / `completed` | correct_diagnoses | [fixed_order eva-001](../workflow-model-comparison-20260927/traces/fixed_order/eva-001.jsonl) |
| `rules` | evaluation / `eval-database-direct` | partial | `diagnose_database_failure` / `completed` | correct_diagnoses | [rules eva-001](../workflow-model-comparison-20260927/traces/rules/eva-001.jsonl) |
| `gliclass` | evaluation / `eval-database-direct` | partial | `none` / `invalid_proposal` | failed_episodes | [gliclass eva-001](../workflow-model-comparison-20260927/traces/gliclass/eva-001.jsonl) |
| `gliclass_evidence_masked` | evaluation / `eval-database-direct` | partial | `diagnose_database_failure` / `completed` | correct_diagnoses | [gliclass_evidence_masked eva-001](../workflow-model-comparison-20260927/traces/gliclass_evidence_masked/eva-001.jsonl) |
| `laya` | evaluation / `eval-database-direct` | partial | `none` / `invalid_proposal` | failed_episodes | [laya eva-001](../workflow-model-comparison-20260927/traces/laya/eva-001.jsonl) |
| `laya_evidence_masked` | evaluation / `eval-database-direct` | partial | `diagnose_database_failure` / `completed` | correct_diagnoses | [laya_evidence_masked eva-001](../workflow-model-comparison-20260927/traces/laya_evidence_masked/eva-001.jsonl) |
| `fixed_order` | evaluation / `eval-healthy-direct` | all four | `diagnose_healthy` / `completed` | correct_diagnoses | [fixed_order eva-004](../workflow-model-comparison-20260927/traces/fixed_order/eva-004.jsonl) |
| `rules` | evaluation / `eval-healthy-direct` | all four | `diagnose_healthy` / `completed` | correct_diagnoses | [rules eva-004](../workflow-model-comparison-20260927/traces/rules/eva-004.jsonl) |
| `gliclass` | evaluation / `eval-healthy-direct` | partial | `none` / `invalid_proposal` | failed_episodes | [gliclass eva-004](../workflow-model-comparison-20260927/traces/gliclass/eva-004.jsonl) |
| `gliclass_evidence_masked` | evaluation / `eval-healthy-direct` | partial | `request_review` / `review` | reviews | [gliclass_evidence_masked eva-004](../workflow-model-comparison-20260927/traces/gliclass_evidence_masked/eva-004.jsonl) |
| `laya` | evaluation / `eval-healthy-direct` | partial | `none` / `invalid_proposal` | failed_episodes | [laya eva-004](../workflow-model-comparison-20260927/traces/laya/eva-004.jsonl) |
| `laya_evidence_masked` | evaluation / `eval-healthy-direct` | partial | `request_review` / `review` | reviews | [laya_evidence_masked eva-004](../workflow-model-comparison-20260927/traces/laya_evidence_masked/eva-004.jsonl) |
| `fixed_order` | evaluation / `eval-historical-resolved` | all four | `diagnose_healthy` / `completed` | correct_diagnoses | [fixed_order eva-006](../workflow-model-comparison-20260927/traces/fixed_order/eva-006.jsonl) |
| `rules` | evaluation / `eval-historical-resolved` | all four | `diagnose_healthy` / `completed` | correct_diagnoses | [rules eva-006](../workflow-model-comparison-20260927/traces/rules/eva-006.jsonl) |
| `gliclass` | evaluation / `eval-historical-resolved` | partial | `none` / `invalid_proposal` | failed_episodes | [gliclass eva-006](../workflow-model-comparison-20260927/traces/gliclass/eva-006.jsonl) |
| `gliclass_evidence_masked` | evaluation / `eval-historical-resolved` | partial | `request_review` / `review` | reviews | [gliclass_evidence_masked eva-006](../workflow-model-comparison-20260927/traces/gliclass_evidence_masked/eva-006.jsonl) |
| `laya` | evaluation / `eval-historical-resolved` | partial | `none` / `invalid_proposal` | failed_episodes | [laya eva-006](../workflow-model-comparison-20260927/traces/laya/eva-006.jsonl) |
| `laya_evidence_masked` | evaluation / `eval-historical-resolved` | partial | `request_review` / `review` | reviews | [laya_evidence_masked eva-006](../workflow-model-comparison-20260927/traces/laya_evidence_masked/eva-006.jsonl) |
| `fixed_order` | evaluation / `eval-insufficient-facts` | all four | `request_review` / `review` | reviews | [fixed_order eva-011](../workflow-model-comparison-20260927/traces/fixed_order/eva-011.jsonl) |
| `rules` | evaluation / `eval-insufficient-facts` | all four | `request_review` / `review` | reviews | [rules eva-011](../workflow-model-comparison-20260927/traces/rules/eva-011.jsonl) |
| `gliclass` | evaluation / `eval-insufficient-facts` | partial | `none` / `invalid_proposal` | failed_episodes | [gliclass eva-011](../workflow-model-comparison-20260927/traces/gliclass/eva-011.jsonl) |
| `gliclass_evidence_masked` | evaluation / `eval-insufficient-facts` | partial | `request_review` / `review` | reviews | [gliclass_evidence_masked eva-011](../workflow-model-comparison-20260927/traces/gliclass_evidence_masked/eva-011.jsonl) |
| `laya` | evaluation / `eval-insufficient-facts` | partial | `none` / `invalid_proposal` | failed_episodes | [laya eva-011](../workflow-model-comparison-20260927/traces/laya/eva-011.jsonl) |
| `laya_evidence_masked` | evaluation / `eval-insufficient-facts` | partial | `request_review` / `review` | reviews | [laya_evidence_masked eva-011](../workflow-model-comparison-20260927/traces/laya_evidence_masked/eva-011.jsonl) |
| `fixed_order` | evaluation / `eval-multiple-current-faults` | all four | `request_review` / `review` | reviews | [fixed_order eva-007](../workflow-model-comparison-20260927/traces/fixed_order/eva-007.jsonl) |
| `rules` | evaluation / `eval-multiple-current-faults` | partial | `diagnose_database_failure` / `completed` | incorrect_diagnoses | [rules eva-007](../workflow-model-comparison-20260927/traces/rules/eva-007.jsonl) |
| `gliclass` | evaluation / `eval-multiple-current-faults` | partial | `none` / `invalid_proposal` | failed_episodes | [gliclass eva-007](../workflow-model-comparison-20260927/traces/gliclass/eva-007.jsonl) |
| `gliclass_evidence_masked` | evaluation / `eval-multiple-current-faults` | partial | `diagnose_database_failure` / `completed` | incorrect_diagnoses | [gliclass_evidence_masked eva-007](../workflow-model-comparison-20260927/traces/gliclass_evidence_masked/eva-007.jsonl) |
| `laya` | evaluation / `eval-multiple-current-faults` | partial | `none` / `invalid_proposal` | failed_episodes | [laya eva-007](../workflow-model-comparison-20260927/traces/laya/eva-007.jsonl) |
| `laya_evidence_masked` | evaluation / `eval-multiple-current-faults` | partial | `diagnose_database_failure` / `completed` | incorrect_diagnoses | [laya_evidence_masked eva-007](../workflow-model-comparison-20260927/traces/laya_evidence_masked/eva-007.jsonl) |
| `fixed_order` | evaluation / `eval-storage-direct` | all four | `diagnose_disk_full` / `completed` | correct_diagnoses | [fixed_order eva-003](../workflow-model-comparison-20260927/traces/fixed_order/eva-003.jsonl) |
| `rules` | evaluation / `eval-storage-direct` | partial | `diagnose_disk_full` / `completed` | correct_diagnoses | [rules eva-003](../workflow-model-comparison-20260927/traces/rules/eva-003.jsonl) |
| `gliclass` | evaluation / `eval-storage-direct` | partial | `none` / `invalid_proposal` | failed_episodes | [gliclass eva-003](../workflow-model-comparison-20260927/traces/gliclass/eva-003.jsonl) |
| `gliclass_evidence_masked` | evaluation / `eval-storage-direct` | partial | `request_review` / `review` | reviews | [gliclass_evidence_masked eva-003](../workflow-model-comparison-20260927/traces/gliclass_evidence_masked/eva-003.jsonl) |
| `laya` | evaluation / `eval-storage-direct` | partial | `none` / `invalid_proposal` | failed_episodes | [laya eva-003](../workflow-model-comparison-20260927/traces/laya/eva-003.jsonl) |
| `laya_evidence_masked` | evaluation / `eval-storage-direct` | partial | `diagnose_disk_full` / `completed` | correct_diagnoses | [laya_evidence_masked eva-003](../workflow-model-comparison-20260927/traces/laya_evidence_masked/eva-003.jsonl) |
| `fixed_order` | evaluation / `eval-storage-tool-error` | partial | `request_review` / `review` | reviews | [fixed_order eva-010](../workflow-model-comparison-20260927/traces/fixed_order/eva-010.jsonl) |
| `rules` | evaluation / `eval-storage-tool-error` | partial | `request_review` / `review` | reviews | [rules eva-010](../workflow-model-comparison-20260927/traces/rules/eva-010.jsonl) |
| `gliclass` | evaluation / `eval-storage-tool-error` | partial | `none` / `invalid_proposal` | failed_episodes | [gliclass eva-010](../workflow-model-comparison-20260927/traces/gliclass/eva-010.jsonl) |
| `gliclass_evidence_masked` | evaluation / `eval-storage-tool-error` | partial | `request_review` / `review` | reviews | [gliclass_evidence_masked eva-010](../workflow-model-comparison-20260927/traces/gliclass_evidence_masked/eva-010.jsonl) |
| `laya` | evaluation / `eval-storage-tool-error` | partial | `none` / `invalid_proposal` | failed_episodes | [laya eva-010](../workflow-model-comparison-20260927/traces/laya/eva-010.jsonl) |
| `laya_evidence_masked` | evaluation / `eval-storage-tool-error` | partial | `request_review` / `review` | reviews | [laya_evidence_masked eva-010](../workflow-model-comparison-20260927/traces/laya_evidence_masked/eva-010.jsonl) |
| `fixed_order` | evaluation / `eval-unrelated` | all four | `request_review` / `review` | reviews | [fixed_order eva-012](../workflow-model-comparison-20260927/traces/fixed_order/eva-012.jsonl) |
| `rules` | evaluation / `eval-unrelated` | all four | `request_review` / `review` | reviews | [rules eva-012](../workflow-model-comparison-20260927/traces/rules/eva-012.jsonl) |
| `gliclass` | evaluation / `eval-unrelated` | partial | `request_review` / `review` | reviews | [gliclass eva-012](../workflow-model-comparison-20260927/traces/gliclass/eva-012.jsonl) |
| `gliclass_evidence_masked` | evaluation / `eval-unrelated` | partial | `request_review` / `review` | reviews | [gliclass_evidence_masked eva-012](../workflow-model-comparison-20260927/traces/gliclass_evidence_masked/eva-012.jsonl) |
| `laya` | evaluation / `eval-unrelated` | partial | `none` / `invalid_proposal` | failed_episodes | [laya eva-012](../workflow-model-comparison-20260927/traces/laya/eva-012.jsonl) |
| `laya_evidence_masked` | evaluation / `eval-unrelated` | all four | `request_review` / `review` | reviews | [laya_evidence_masked eva-012](../workflow-model-comparison-20260927/traces/laya_evidence_masked/eva-012.jsonl) |
| `fixed_order` | evaluation / `eval-vague-to-database` | all four | `diagnose_database_failure` / `completed` | correct_diagnoses | [fixed_order eva-005](../workflow-model-comparison-20260927/traces/fixed_order/eva-005.jsonl) |
| `rules` | evaluation / `eval-vague-to-database` | partial | `diagnose_database_failure` / `completed` | correct_diagnoses | [rules eva-005](../workflow-model-comparison-20260927/traces/rules/eva-005.jsonl) |
| `gliclass` | evaluation / `eval-vague-to-database` | partial | `request_review` / `review` | reviews | [gliclass eva-005](../workflow-model-comparison-20260927/traces/gliclass/eva-005.jsonl) |
| `gliclass_evidence_masked` | evaluation / `eval-vague-to-database` | partial | `request_review` / `review` | reviews | [gliclass_evidence_masked eva-005](../workflow-model-comparison-20260927/traces/gliclass_evidence_masked/eva-005.jsonl) |
| `laya` | evaluation / `eval-vague-to-database` | partial | `none` / `invalid_proposal` | failed_episodes | [laya eva-005](../workflow-model-comparison-20260927/traces/laya/eva-005.jsonl) |
| `laya_evidence_masked` | evaluation / `eval-vague-to-database` | partial | `request_review` / `review` | reviews | [laya_evidence_masked eva-005](../workflow-model-comparison-20260927/traces/laya_evidence_masked/eva-005.jsonl) |

## Evaluator-only hindsight

These annotations are derived from unrequested fixture observations after the scenario hash check. They are not policy-visible evidence and do not change replay, proposal selection, or the historical evaluator metrics.

| Policy / split / scenario | Tool | Relationship | Exact structured facts | Trace |
|---|---|---|---|---|
| `rules` / development / `dev-contradictory-evidence` | `check_service_health` | contradicts_terminal_diagnosis (database_failure) | `database_probe_success=true` | [trace](../workflow-model-comparison-20260927/traces/rules/dev-008.jsonl) |
| `laya_evidence_masked` / development / `dev-multiple-current-faults` | `check_storage` | additional_fault (disk_full) | `storage_exhausted=true`, `write_test_success=false` | [trace](../workflow-model-comparison-20260927/traces/laya_evidence_masked/dev-007.jsonl) |
| `rules` / evaluation / `eval-multiple-current-faults` | `check_authentication` | additional_fault (authentication_failure) | `authentication_success=false`, `credentials_rejected=true` | [trace](../workflow-model-comparison-20260927/traces/rules/eva-007.jsonl) |
| `gliclass_evidence_masked` / evaluation / `eval-multiple-current-faults` | `check_authentication` | additional_fault (authentication_failure) | `authentication_success=false`, `credentials_rejected=true` | [trace](../workflow-model-comparison-20260927/traces/gliclass_evidence_masked/eva-007.jsonl) |
| `laya_evidence_masked` / evaluation / `eval-multiple-current-faults` | `check_authentication` | additional_fault (authentication_failure) | `authentication_success=false`, `credentials_rejected=true` | [trace](../workflow-model-comparison-20260927/traces/laya_evidence_masked/eva-007.jsonl) |
