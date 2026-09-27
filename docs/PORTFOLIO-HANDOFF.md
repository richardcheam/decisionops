# DecisionOps portfolio handoff

This is project information for the portfolio maintainer. It describes the work and evidence; it does not prescribe a portfolio layout or implementation.

## Project summary

- **Suggested title:** DecisionOps: Bounded Diagnostic Workflow Evaluation
- **Description:** An offline experiment comparing fixed-order, rules-based, GLiClass, and Laya policies in a bounded synthetic diagnostic workflow, with replayable traces and a standalone report viewer.
- **Repository:** [github.com/richardcheam/decisionops](https://github.com/richardcheam/decisionops)
- **Demo URL:** Pending GitHub Pages setup and first successful deployment. Intended URL: `https://richardcheam.github.io/decisionops/`.
- **Engineering question:** Can a policy select useful next actions in a bounded diagnostic workflow while respecting visible evidence and fixed tool and decision budgets?
- **Intended use:** A reproducible engineering demonstration of evaluation design, traceability, evidence constraints, and model failure modes. It is not a live incident-response system.

## What is implemented

- Four bounded fixture tools reveal checked-in database, authentication, storage, and service-health observations. They do not call live services or change systems.
- Deterministic evidence checks validate diagnoses against current observations, enforce budgets, reject unsupported proposals, and account for outcomes.
- Fixed-order and rules baselines, plus unmasked and evidence-masked GLiClass and Laya policies.
- Separate sequential worker processes for GLiClass and Laya, with each process reused for its two policy variants.
- Versioned, model-free replay of recorded decision traces.
- A standard-library exporter that builds a self-contained HTML viewer from the committed reports. The viewer does not need model weights, PyTorch, a server, or network access.
- A GitHub Actions workflow that verifies the tests and exports the site for pull requests, then deploys only the generated site output from `main` after verification or through manual dispatch. Repository Pages setup is still pending; see the status above and README.

The harness deterministically controls candidate eligibility, evidence masking, tool returns, proposal acceptance or rejection, budgets, and terminal accounting. The learned policy selects among the actions made available to it; the harness does not replace a model's choice with an argmax or hidden-label fallback. Fixed order is itself deterministic. The evaluator keeps gold outcomes and unrequested observations away from policies.

## Recorded results

The final committed [comparison report](../reports/workflow-model-comparison-20260927/all-summary.md) covers 12 development and 12 evaluation scenarios per policy. Values below sum the two splits; denominators are shown explicitly for supported diagnoses and review-required scenarios.

| Policy | Correct supported diagnoses | Correct reviews | Incorrect diagnoses | Unnecessary reviews | Failed episodes | Unsupported diagnosis proposals | Tool calls |
|---|---:|---:|---:|---:|---:|---:|---:|
| fixed_order | 13/13 | 11/11 | 0 | 0 | 0 | 0 | 96 |
| rules | 13/13 | 9/11 | 2 | 0 | 0 | 0 | 55 |
| gliclass | 1/13 | 2/11 | 0 | 2 | 19 | 38 | 16 |
| gliclass_evidence_masked | 6/13 | 10/11 | 1 | 7 | 0 | 0 | 41 |
| laya | 0/13 | 0/11 | 0 | 0 | 24 | 48 | 4 |
| laya_evidence_masked | 8/13 | 9/11 | 2 | 5 | 0 | 0 | 49 |

Fixed order remained strongest on this suite. Evidence masking reduced unsupported diagnosis proposals to zero for both model families and removed their failed episodes, while increasing unnecessary reviews. The masked models still made incorrect diagnoses.

For context, the report records GLiClass model loading at 6.77 seconds with worker-process peak RSS of 874,635,264 bytes, and Laya at 5.94 seconds with peak RSS of 3,041,480,704 bytes. These are process-wide measurements from the recorded local evaluation. Fixture timing is not live tool latency.

## Guided viewer examples

1. **A diagnosis the harness blocks** — unmasked Laya proposes a database diagnosis before requesting any observation. The harness rejects it as unsupported; repeating the proposal reaches the bounded failure rule.
2. **Masking leaves a useful tool-first choice** — for the same development scenario, evidence-masked Laya chooses the database check, receives the recorded timeout, then chooses a supported database diagnosis.
3. **Supported by one observation, premature for two faults** — on `eval-multiple-current-faults`, masked Laya checks only the database before its accepted database diagnosis. Authentication has not been checked. The evaluator requires review because the complete scenario contains multiple faults; fixed order gathers database, authentication, storage, and service-health observations and requests review.

Guided examples are included only when their split, policy trace, and required comparison trace exist in the loaded report. Thus the development-only report export does not offer the evaluation-only third example.

## Limitations

- The 24 scenarios are inspected synthetic regression cases, not untouched held-out data or evidence of production accuracy.
- The fixture tools do not perform live remediation or contact operational systems.
- Model scores and confidence metadata are uncalibrated and never authorize action execution.
- GLiClass and Laya receive different native input formats; this comparison does not isolate model architecture.
- Fixed order outperformed the learned policies here. Do not present the experiment as a positive model result.
- The reported worker RSS is process-wide. The report's fixture timings are not live operational latency.

## Sources

- [Findings and interpretation](../FINDINGS.md)
- [Full comparison report](../reports/workflow-model-comparison-20260927/all-summary.md) and [machine-readable summary](../reports/workflow-model-comparison-20260927/all-summary.json)
- [Replay traces](../reports/workflow-model-comparison-20260927/traces/)
- [Five-minute walkthrough](WORKFLOW-DEMO-WALKTHROUGH.md)
- [Workflow simulator, evidence checks, and replay](../decisionops/workflow.py)
- [Policy adapters and shared candidate selection](../decisionops/workflow_policies.py)
- [Evaluation, worker isolation, and metrics](../decisionops/workflow_eval.py)
- [Offline report exporter](../decisionops/workflow_report.py)
- [Workflow tests](../tests/test_workflow.py), [Laya workflow tests](../tests/test_laya_workflow.py), and [report viewer tests](../tests/test_workflow_report.py)

## Verification provenance

### Previously reported verification

The prior feature milestone reported 69 model-free tests passing, successful exports of both the full and development-only reports, and Firefox/geckodriver interaction checks for split selection, guided examples, policy selection, fixed-order comparison, and raw-data expansion. These are recorded results from that development run.

### Independently performed for this handoff

Using Python 3.12.3 with site packages disabled, the complete unittest discovery ran 69 tests: 67 passed and the two Laya-package API checks were skipped because ML dependencies were deliberately absent. The existing exporter generated an HTML index from the committed report; the generated output contained only `index.html`, and the synthetic-simulation and uncalibrated-score notices were present. The final report summaries and traces were read directly to recalculate the aggregate table above. The Pages workflow YAML was parsed locally; GitHub Actions has not run for this change. A successful Pages deployment and its actual URL remain pending the repository Pages setting and merge to `main`.
