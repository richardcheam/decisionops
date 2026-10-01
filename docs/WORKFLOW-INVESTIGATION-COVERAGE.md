# Investigation coverage audit

Run the model-free audit over an existing completed workflow comparison:

```sh
uv run --locked python -m decisionops workflow audit-coverage \
  --report-dir reports/workflow-model-comparison-20260927 \
  --scenario-file data/diagnostic_scenarios.jsonl \
  --output-dir reports/workflow-investigation-coverage-audit-20261001
```

The command first loads the report through the existing report loader, which replays every summary-referenced trace and checks each replayed terminal result against its episode summary. It then verifies the supplied scenario file's SHA-256 against `provenance.json` before joining any fixture annotations. It writes `investigation-coverage.json` and `investigation-coverage.md` into a new, empty output directory. It does not load models or change the source report, traces, scenarios, policies, or deployed viewer.

## Metric definitions

- **Attempted tools** come from the trace's recorded `actions_attempted` state. **Never attempted** is the remaining set of the four tools.
- **Successful current observations** require a returned observation with `status=success` and `time_scope=current`. Historical, timeout, and error observations are listed separately; none counts as successful current coverage.
- **All-four current coverage** means all four tools returned a successful current observation. It measures fixture coverage, not fact informativeness, diagnosis completeness, or evaluator correctness.
- **Correct diagnoses** use the existing evaluator rule: the terminal diagnosis matches the gold terminal action, the terminal reason is `completed`, and the recorded gold evidence is supported. Their denominator is diagnosable episodes in that coverage stratum.
- **Incorrect diagnoses** use the existing report metric: the terminal action is a diagnosis different from the gold terminal action. **Reviews** count terminal `request_review` actions. **Failed episodes** use replayed terminal status `failed`. Those last three denominators are all episodes in the coverage stratum. Any unusual residual outcome is shown separately.
- **Residual outcomes** include terminal results outside the previous four buckets, including a completed diagnosis that matches the gold action but whose evaluator gold-evidence flag is false. This does not alter the historical correct-diagnosis or incorrect-diagnosis metrics. `classified_episode_count` counts every episode assigned exactly one selected outcome bucket, including residual outcomes, and must equal that coverage group's episode denominator.
- Per-episode trace links point to the unchanged source JSONL file. The audit keeps evaluator outcomes separate from policy-visible observations and derives them from the report's episode outcomes.
- A recorded accepted diagnosis or review is the policy's selected terminal action; candidate eligibility and evidence acceptance are deterministic harness checks. A failed episode does not by itself establish that a policy deliberately chose to stop.

## Evidence boundary and interpretation

The policy-visible section is reconstructed from recorded trace state and contains only the initial report, requested observations, attempted tools, and remaining budgets. Evaluator-only hindsight is a separate output section. It includes only exact structured current facts from unrequested scenario observations matching the same category signals used by the workflow's evidence check. The audit ignores fixture message text and does not feed hidden facts into replay or policy state.

Those structured signals mirror `workflow._area_evidence`. Database fault facts are `check_database.connection_success=false`, `check_database.timeout=true`, or `check_service_health.database_probe_success=false`; their counterfacts are `connection_success=true` or `database_probe_success=true`. Authentication fault facts are `check_authentication.authentication_success=false`, `check_authentication.credentials_rejected=true`, or `check_service_health.authentication_probe_success=false`; counterfacts are `authentication_success=true`, `credentials_rejected=false`, or `authentication_probe_success=true`. Disk-full facts are `check_storage.storage_exhausted=true`, `check_storage.write_test_success=false`, or `check_service_health.storage_probe_success=false`; counterfacts are `storage_exhausted=false`, `write_test_success=true`, or `storage_probe_success=true`. Only observations whose fixture status is `success` and time scope is `current` are considered. Other fields, including `current_failure`, historical alert flags, and free-text messages, do not create audit annotations.

All-four coverage does not guarantee correctness: the facts may be contradictory, inconclusive, or unrelated to the selected diagnosis, and correctness still comes from the evaluator outcome. Fewer calls do not automatically mean greater efficiency; this synthetic fixture evaluation does not price the risk of missing a fault or measure live operational cost. The audit can show whether early stopping correlates with evaluator misses and therefore whether a stricter stopping rule merits separate study. It cannot establish that a new rule would help; no policy behavior is changed or tested here.

The committed report contains 24 inspected synthetic scenarios, not a validated real-world benchmark. The accompanying same-visible-state test is an illustration only: two fixture worlds share the same report and database observation, while an unrequested authentication fault changes the evaluator outcome. It is not included in benchmark metrics and is not a model-performance result.
