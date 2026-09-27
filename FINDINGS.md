# Bounded workflow comparison

This is a recorded synthetic regression comparison over the checked-in 12-scenario development and 12-scenario evaluation splits. The evaluation scenarios have already been inspected. It is not untouched held-out evidence or a production accuracy estimate.

## Results

| Policy | Split | Terminal status (completed / review / failed) | Supported diagnoses | Correct reviews | Incorrect diagnoses | Unnecessary reviews | Unsupported proposals | Tool calls | Mean latency (s) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| fixed_order | development | 7 / 5 / 0 | 7/7 | 5/5 | 0 | 0 | 0 | 48 | 0.0009 |
| fixed_order | evaluation | 6 / 6 / 0 | 6/6 | 6/6 | 0 | 0 | 0 | 48 | 0.0009 |
| rules | development | 8 / 4 / 0 | 7/7 | 4/5 | 1 | 0 | 0 | 28 | 0.0007 |
| rules | evaluation | 7 / 5 / 0 | 6/6 | 5/6 | 1 | 0 | 0 | 27 | 0.0009 |
| gliclass | development | 0 / 2 / 10 | 0/7 | 1/5 | 0 | 1 | 20 | 7 | 0.3719 |
| gliclass | evaluation | 1 / 2 / 9 | 1/6 | 1/6 | 0 | 1 | 18 | 9 | 0.3742 |
| gliclass_evidence_masked | development | 4 / 8 / 0 | 4/7 | 5/5 | 0 | 3 | 0 | 21 | 0.4414 |
| gliclass_evidence_masked | evaluation | 3 / 9 / 0 | 2/6 | 5/6 | 1 | 4 | 0 | 20 | 0.4072 |
| laya | development | 0 / 0 / 12 | 0/7 | 0/5 | 0 | 0 | 24 | 1 | 2.3291 |
| laya | evaluation | 0 / 0 / 12 | 0/6 | 0/6 | 0 | 0 | 24 | 3 | 2.5671 |
| laya_evidence_masked | development | 6 / 6 / 0 | 5/7 | 4/5 | 1 | 2 | 0 | 23 | 3.1765 |
| laya_evidence_masked | evaluation | 4 / 8 / 0 | 3/6 | 5/6 | 1 | 3 | 0 | 26 | 3.5078 |

Fixed order had 13/13 correct supported diagnoses and 11/11 correct reviews across the two splits, with no failures, incorrect diagnoses, or unnecessary reviews. Neither model policy exceeded it. Laya's masked variant scored 8/13 supported diagnoses and 9/11 correct reviews; GLiClass masking scored 6/13 and 10/11. The unmasked variants failed 19/24 episodes for GLiClass and all 24 for Laya after unsupported proposals exhausted the harness retry rule.

Evidence masking helped both models by eliminating unsupported diagnosis proposals: GLiClass went from 38 such proposals to zero, and Laya from 48 to zero. It also removed their unmasked failure episodes. The tradeoff was more reviews, including unnecessary reviews. On the evaluation split, GLiClass masking produced four unnecessary reviews and one incorrect diagnosis; Laya masking produced three unnecessary reviews and one incorrect diagnosis. A visible-evidence check does not establish that unrequested fixture observations contain no additional faults, so a supported diagnosis can still be premature relative to the scenario's complete synthetic outcome.

## Interpretation and limits

Candidate eligibility, evidence masking, tool and decision budgets, repeat-tool rejection, review availability, proposal validation, terminal accounting, and evidence acceptance are deterministic harness behavior. The models choose among their eligible actions; there is no deterministic argmax replacement or fallback. Fixed order is also deterministic: it checks database, authentication, storage, and service health in that order before applying the evidence check. The rules policy uses its fixed report cues, then supported evidence, then fallback order. The observed wins and errors therefore describe these policy implementations on this suite, not a general model capability comparison.

GLiClass receives visible-state text and an ordered candidate-name list. Laya receives the same visible-state text through its native named-choice API, with fixed concise descriptions. These native input formats differ, so the comparison does not isolate model architecture. Laya's native choice and probabilities are preserved alongside separate optional `confidence`, `answer_confidence`, and `act_probability` fields. None is calibrated for this workflow, and none authorizes action execution.

Model families ran in separate sequential worker processes, and each process reused its model for its two variants. GLiClass loaded in 6.77 s with worker-process peak RSS of 874,635,264 bytes. Laya loaded in 5.94 s with peak RSS of 3,041,480,704 bytes. These are process-wide Linux high-water RSS values, not model-only memory. Mean episode latency is shown above; p50/p95 latency, full terminal counts, and per-policy model load/RSS are in the Markdown and JSON reports. Fixture timing is not live tool latency.

No model confidence threshold was fitted and no prompt variants were searched. The inspected synthetic regression data, small scenario count, local pinned checkpoints, and lack of calibrated confidence limit the conclusions. The negative outcomes are retained as measured.

## Reports

- Full two-split comparison: [reports/workflow-model-comparison-20260927](reports/workflow-model-comparison-20260927/), with [all-summary.md](reports/workflow-model-comparison-20260927/all-summary.md), [all-summary.json](reports/workflow-model-comparison-20260927/all-summary.json), `run-status.json`, per-policy summaries, worker logs, provenance, and replay traces.
- Final-code development integration run: [reports/workflow-model-comparison-development-final-20260927](reports/workflow-model-comparison-development-final-20260927/).
- Earlier development integration report retained unchanged: [reports/workflow-model-comparison-development-20260927](reports/workflow-model-comparison-development-20260927/).
- Previous milestone reports remain preserved, including [reports/diagnostic-workflow-20260927](reports/diagnostic-workflow-20260927/) and [reports/gliclass-evidence-mask-20260927](reports/gliclass-evidence-mask-20260927/).
