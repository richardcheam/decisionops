# Evidence-masked workflow comparison

This is a recorded synthetic regression comparison over the checked-in 12-scenario development and 12-scenario evaluation splits. The evaluation scenarios have already been inspected; these results are not untouched held-out evidence or a production accuracy estimate.

## Results

| Policy | Split | Terminal status (completed / review / failed) | Correct supported diagnoses | Correct reviews | Incorrect diagnoses | Unnecessary reviews | Unsupported diagnosis proposals |
|---|---|---:|---:|---:|---:|---:|---:|
| fixed_order | development | 7 / 5 / 0 | 7/7 | 5/5 | 0 | 0 | 0 |
| fixed_order | evaluation | 6 / 6 / 0 | 6/6 | 6/6 | 0 | 0 | 0 |
| rules | development | 8 / 4 / 0 | 7/7 | 4/5 | 1 | 0 | 0 |
| rules | evaluation | 7 / 5 / 0 | 6/6 | 5/6 | 1 | 0 | 0 |
| gliclass | development | 0 / 2 / 10 | 0/7 | 1/5 | 0 | 1 | 20 |
| gliclass | evaluation | 1 / 2 / 9 | 1/6 | 1/6 | 0 | 1 | 18 |
| gliclass_evidence_masked | development | 4 / 8 / 0 | 4/7 | 5/5 | 0 | 3 | 0 |
| gliclass_evidence_masked | evaluation | 3 / 9 / 0 | 2/6 | 5/6 | 1 | 4 | 0 |

Masking prevented all unsupported diagnosis proposals in these 24 GLiClass episodes: the unmasked policy made 38. This removed the baseline's 19 failed episodes. Correct supported diagnoses increased from 0/7 to 4/7 on development and from 1/6 to 2/6 on evaluation. Fixed-order performed best on both splits, at 7/7 and 6/6 supported diagnoses, with all reviews correct.

Masking also made the GLiClass policy request review more often. Unnecessary reviews rose from 1 to 3 on development and from 1 to 4 on evaluation. The masked policy still made one incorrect diagnosis on evaluation, so the evidence gate does not prevent premature diagnosis once the visible observations support a category. It does not fix the rules policy's separate premature-diagnosis behavior either; rules made one incorrect diagnosis on each split.

## What the counters mean

- `terminal_status_counts` records completed diagnoses, review terminals, and failed episodes. The counts sum to the episode count.
- `terminal_reason_counts` records why each episode ended: completed, review, exhausted budget, invalid proposal, tool failure, and any additional reason present in the trace. These counts also sum to the episode count.
- `correct_supported_diagnoses` counts diagnoses matching the scenario label that completed with acceptable gold evidence; its denominator is `diagnosable_count`.
- `correct_review_decisions` counts review terminals on scenarios labeled as requiring review; its denominator is `review_required_count`.
- `incorrect_diagnoses` counts terminal diagnoses that do not match the scenario label. `unnecessary_review_on_diagnosable_cases` counts review terminals on scenarios with a diagnosis label.
- `unsupported_diagnosis_proposals` counts diagnosis proposals rejected for lack of support in the currently visible observations. `invalid_proposals_rejected` counts other proposal validation rejections. A run with any failed terminal episode has `run_status: failed`, even if the invalid proposal counter is zero.

## Interpretation and limits

Candidate eligibility, the evidence mask, tool and decision budgets, repeat-tool rejection, review availability, and post-proposal validation are deterministic harness behavior. GLiClass ranks only the candidates left eligible for its variant; it chooses among those candidates, including when to request review, and there is no deterministic fallback. The results therefore show that the mask prevents a specific unsupported action choice, but they do not establish model value. On this small suite, fixed-order is more accurate.

Evidence supporting a diagnosis from observations collected so far does not prove that no additional faults exist in tools that have not been requested. A masked diagnosis can therefore pass the current evidence rule and still be premature relative to the scenario's full synthetic outcome.

Fixture execution time is not live tool latency. The GLiClass baseline and masked variant share one loaded checkpoint; each summary reports that shared load duration. RSS is the whole evaluator process high-water mark, not model-only memory. This remains an offline synthetic simulation using unchanged scenarios and budgets.

## Reports

- Full two-split comparison: [reports/gliclass-evidence-mask-20260927](reports/gliclass-evidence-mask-20260927/), with the tabular summary in [all-summary.md](reports/gliclass-evidence-mask-20260927/all-summary.md) and JSON results in [all-summary.json](reports/gliclass-evidence-mask-20260927/all-summary.json).
- Development-only comparison: [reports/gliclass-evidence-mask-development-20260927](reports/gliclass-evidence-mask-development-20260927/).
- Existing historical report preserved: [reports/diagnostic-workflow-20260927](reports/diagnostic-workflow-20260927/).
