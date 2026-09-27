# GLiClass input-format diagnosis

## Question and fixed experiment

The previous 48-case evaluation showed a strong `database_failure` bias for GLiClass using hierarchical `name: description` labels. This experiment isolated candidate text from hierarchy and candidate order. Before running the model, it selected two existing unambiguous cases per class: `core-database_failure-01/02`, `core-authentication_failure-01/02`, `core-disk_full-01/02`, and `core-healthy-01/02`. It compared four input formats under all four cyclic rotations of the same candidate order, for 128 diagnostic predictions. Three exact earlier smoke inputs were evaluated separately under the same 16 conditions, for 48 more predictions. One checkpoint instance was loaded once; all calls used CPU, four PyTorch threads, batch size one, and offline mode.

## Installed pipeline observations

The pinned checkpoint is `knowledgator/gliclass-small-v1.0@21edefaf7951f68c68c505f9139ba536d3b448f7`, loaded with GLiClass 0.1.20, Transformers 5.17.0, PyTorch 2.14.0+cpu, and Python 3.12.14. It uses `UniEncoderZeroShotClassificationPipeline`, maximum input length 1024, and `.` as the hierarchy separator.

The installed `flatten_hierarchical_labels` joins hierarchy keys and leaf labels with `.`. `prepare_input` appends each flattened string as `<<LABEL>>{label}`, then `<<SEP>>`. Tokenization truncates at 1024. All diagnostic inputs were 22–67 tokens, with no truncation. Every call contained four literal and tokenized `<<LABEL>>` markers. Flat labels are preserved without a prefix; hierarchical labels gain `incident.` before model tokenization.

In single-label mode, the pipeline takes the model logits at the candidate positions, applies `torch.softmax` over those logits, and zips the probabilities with the same ordered flattened labels. `return_hierarchical=True` reshapes this score map; it does not change logits or probabilities. Across all 176 calls, the returned score maps matched softmax recomputed from captured raw logits to within `9.2e-8`; there were no missing or misplaced candidate scores. The model-type warning emitted by the installed Transformers integration was nonfatal in these loads. The experiment does not establish whether that warning has any effect beyond this observed run.

## Results

Core totals below pool eight preselected examples across four rotations (32 prediction trials). Order sensitivity counts the eight cases whose predicted canonical class varied across rotations. Mean probability delta is the mean per-class absolute score change against rotation zero, averaged over the other three rotations and eight cases.

| Format | Candidate input | Correct trials | Correct by rotation 0 / 1 / 2 / 3 (of 8) | Order-sensitive cases | Mean probability delta |
|---|---|---:|---:|---:|---:|
| A | Flat short names | 32/32 | 8 / 8 / 8 / 8 | 0/8 | 0.0099 |
| B | Hierarchical short names | 23/32 | 6 / 5 / 4 / 8 | 5/8 | 0.1574 |
| C | Flat `name: description` | 16/32 | 5 / 3 / 4 / 4 | 2/8 | 0.0858 |
| D | Hierarchical `name: description` (previous adapter) | 9/32 | 2 / 2 / 2 / 3 | 1/8 | 0.0554 |

The separate anchors, at the default candidate order, were:

| Anchor | A | B | C | D |
|---|---|---|---|---|
| Database timeout | correct | correct | correct | correct |
| Healthy operation | correct | correct | correct | database failure |
| Disk full | correct | correct | database failure | database failure |

The full per-call record, including exact candidate structures and prepared input text, raw logits, complete softmax values, returned pipeline maps, token counts, runtime, and provenance, is in [`diagnostic.json`](diagnostic.json).

## Finding and adapter decision

The canonical score mapping and the complete map agree with the installed pipeline’s raw logits; no mapping defect was found. There was no truncation, and all formats used the same four candidates. Flat short names classified all 32 selected trials correctly with no predicted-class changes across the four rotations. Both adding hierarchy and adding descriptions reduced performance on this fixed diagnostic set; described flat labels alone also degraded the disk-full anchor. This supports an input-format limitation for this checkpoint. It does not establish whether colon punctuation, extra description words, the hierarchy prefix, or their interaction is individually responsible for every error.

The primary adapter now uses **format A: flat short human-readable names**. This is supported by the prior interactive smoke observation and this preselected controlled experiment, rather than by tuning against the 48-case development score. It retains the inspected single-label softmax path and full returned score map. Laya continues to receive the same shared names and descriptions in its required choice schema; model-native input representations are documented as different, not equivalent.

The follow-up full sequential evaluation in [`../milestone-20260927-flat-short-gliclass/all-summary.md`](../milestone-20260927-flat-short-gliclass/all-summary.md) scored GLiClass at 31/32 core and 3/7 labeled challenge cases, compared with 10/32 core and 1/7 challenge for the previous format. Rules remained 31/32 core and scored 4/7 challenge; Laya remained 30/32 and 3/7. GLiClass and Laya each forced predictions on all nine review cases, while rules abstained on all nine. These are development-set measurements, not a generalization test.

The post-change GLiClass smoke check reported API/load success separately from semantic expectations and matched all three anchors. This confirms those calls and those three labels only. Given the full development result equal to rules on core cases, substantially faster CPU inference than Laya, and the explicit format finding, GLiClass is suitable as an experimental candidate in the next bounded workflow comparison alongside rules. Its forced predictions on review cases require the workflow to preserve human review/abstention handling; these results do not justify automatic operational decisions.

The GLiClass Transformers warning remains an unresolved compatibility question, but it does not explain the observed format differences in this experiment: the same loaded model, code path, environment, and warning were used across all formats. No dependency downgrade or further tuning was attempted. This diagnosis does not demonstrate reliable quality on broader inputs.

## Reproduction

From the repository root, with the pinned checkpoint cached:

```sh
uv run --locked python scripts/gliclass_format_diagnostic.py
uv run --locked python scripts/model_smoke.py gliclass
uv run --locked python -m unittest discover -s tests -v
uv run --locked python -m decisionops evaluate --backend all --output-dir reports/milestone-20260927-flat-short-gliclass
```

The last command reproduces the subsequent full evaluation after the adapter switched to flat short names. It runs workers sequentially and retains the prior `reports/milestone-20260927/` evidence unchanged.
