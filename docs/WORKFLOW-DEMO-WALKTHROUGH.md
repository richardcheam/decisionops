# Five-minute workflow demo

Start by generating the offline viewer from the checked-in report:

```sh
python3 -m decisionops workflow export-html \
  --report-dir reports/workflow-model-comparison-20260927 \
  --output runs/decisionops-workflow-demo.html
```

Open the HTML file directly in a browser. The viewer makes no network requests. The dataset is a small, inspected synthetic regression suite; fixture timestamps and latency measurements are not live tool timing.

## 0:00–0:45 · Orient

Point out the evaluation execution status, then the per-policy run status and terminal counts. These are different: evaluation execution completed, while some policies ended episodes as failed. A completed episode is only a termination category; the separate diagnosis and review counts show whether the result matched the evaluator, each with its own denominator.

Candidate eligibility, budgets, evidence masking, fixture returns, evidence checks, proposal acceptance, and terminal accounting come from deterministic harness rules. A learned policy chooses from the candidates made available to it. The fixed-order baseline follows its documented database, authentication, storage, service-health sequence. On this suite, fixed order achieved 13/13 supported diagnoses and 11/11 correct reviews, so it remains the strongest baseline.

## 0:45–1:45 · The harness blocks an unsupported diagnosis

Choose **A diagnosis the harness blocks**. This opens Laya on dev-database-clear before any observation has been requested. At step 1 the report mentions database timeouts, but the policy-visible observation list is empty. Laya selects Database failure. The harness rejects the proposal because current observations do not support that diagnosis and returns that feedback to the next decision. Laya selects the same diagnosis again; the bounded retry rule ends the episode as failed.

The score is shown as recorded native output and labeled uncalibrated. It neither overrides the evidence check nor grants permission to perform an action.

Trace: [unmasked Laya, dev-database-clear](../reports/workflow-model-comparison-20260927/traces/laya/dev-001.jsonl).

## 1:45–2:45 · Evidence masking leaves a useful tool-first action

Choose **Masking leaves a useful tool-first choice**. This is the same scenario with laya_evidence_masked. Unsupported diagnoses are removed from its scored choices with recorded exclusion reasons; the model then chooses Check database. The fixture returns a current database timeout. With that observation available, Laya chooses Database failure and the harness accepts it. Here the harness handles the candidate mask, tool response, and support check deterministically; choosing Check database and then the diagnosis comes from the model.

Compare the unmasked trace above: the initial report is the same, but diagnosis choices were still scored before evidence masking and led to two rejected proposals.

Trace: [evidence-masked Laya, dev-database-clear](../reports/workflow-model-comparison-20260927/traces/laya_evidence_masked/dev-001.jsonl).

## 2:45–4:15 · A supported diagnosis can still be premature

Choose **Supported by one observation, premature for two faults**. Turn on **Compare with fixed order**. Both timelines now show eval-multiple-current-faults. Masked Laya requests the database and authentication checks; both return current failure observations. It then selects Database failure. The harness accepts that diagnosis because the visible database observation supports it. The evaluator label for the scenario is review because the fixture contains multiple current faults.

Fixed order follows its deterministic check sequence and finishes by requesting review. This paired trace distinguishes support for one diagnosis from completeness of the diagnosis. The diagnosis passed the visible-evidence rule but did not match the evaluator’s full scenario outcome.

Traces: [masked Laya](../reports/workflow-model-comparison-20260927/traces/laya_evidence_masked/eva-007.jsonl) and [fixed order](../reports/workflow-model-comparison-20260927/traces/fixed_order/eva-007.jsonl).

## 4:15–5:00 · Read the result carefully

The separate evaluator-only panel identifies gold outcomes used after each episode. Gold labels and unrequested observations were not inputs to the policy. Raw trace sections preserve the exact policy input, scored candidates, exclusions, native metadata, and harness response; the viewer adds no model reasoning or explanations.

Evidence masking removed unsupported diagnosis proposals and failures for both model families, but masked policies still made premature diagnoses or unnecessary reviews. Neither beat fixed order here. Confidence metadata is not calibrated, the inspected scenarios are synthetic, and the fixture timing does not estimate live operational latency. Full metrics and caveats are recorded in [FINDINGS.md](../FINDINGS.md).
