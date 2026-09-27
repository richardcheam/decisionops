# DecisionOps: local incident classification evaluation

This is a small CPU-only development harness comparing a readable rules baseline with GLiClass and Laya. It classifies recorded text only and never runs operational actions. The 48 hand-authored examples are development data, not a held-out benchmark or evidence of production accuracy.

## Offline workflow portfolio demo

The engineering question is whether a policy can choose useful next actions in a bounded diagnostic workflow while respecting visible evidence and fixed tool/decision budgets. The recorded comparison shows where learned action selection fails, how evidence masking changes those choices, and why fixed order remains the strongest baseline on this inspected synthetic suite. See [FINDINGS.md](FINDINGS.md) for measured outcomes and limitations.

The hosted GitHub Pages demo is pending the repository's first Pages setup and successful deployment. The expected URL is `https://richardcheam.github.io/decisionops/`; it will be linked here after the deployed page is verified. See the [portfolio handoff](docs/PORTFOLIO-HANDOFF.md) for project context, source links, and current publication status.

Create a self-contained viewer from the committed report:

```sh
python3 -m decisionops workflow export-html \
  --report-dir reports/workflow-model-comparison-20260927 \
  --output runs/decisionops-workflow-demo.html
```

Open `runs/decisionops-workflow-demo.html` directly in a browser. Export uses the Python standard library and the existing JSON summaries/traces; it needs no model weights, PyTorch, internet connection, web server, or browser-side fetches. It validates every referenced trace with model-free replay, checks the displayed metrics against each policy summary, and writes the HTML outside the historical report directory. The guided path through the three examples is in [the five-minute walkthrough](docs/WORKFLOW-DEMO-WALKTHROUGH.md). The source [traces](reports/workflow-model-comparison-20260927/traces/) and report [limitations](FINDINGS.md#interpretation-and-limits) remain available for review.

Reproducing the model comparison is a separate, optional step. It uses the pinned local checkpoints and runs each model family in its own sequential worker; it can take several minutes and requires the existing model cache:

```sh
uv run --locked python -m decisionops workflow evaluate --split development \
  --output-dir reports/workflow-model-comparison-development-local
uv run --locked python -m decisionops workflow evaluate --split all \
  --output-dir reports/workflow-model-comparison-local
```

Evaluation uses fresh output directories. The HTML demo command above does not run evaluation.

## Environment and files

Python 3.12.14 is selected by `.python-version`. Install the exact resolved packages with:

```sh
uv sync --locked
```

`pyproject.toml` describes direct requirements and explicitly routes PyTorch to its CPU index. `uv.lock` records the complete resolved dependency graph and exact versions. `.venv` is the local installed environment and is ignored by git. `--locked` checks that the lockfile is current and refuses to rewrite it; `--frozen` skips that freshness check, so it is not used here.

The project already includes the pinned packages and CPU index configuration. This implementation adds no runtime dependencies. Model revision IDs are parsed as plain key/value data from `model-revisions.env`; the file is never executed as shell or Python. The model adapters ask Hugging Face Hub for the cached `model.safetensors` file at the pinned revision and use its parent directory. They set `HF_HUB_OFFLINE=1` before importing Hugging Face libraries. No weights are downloaded by these commands.

## Checks and smoke tests

Run model-free unit tests:

```sh
uv run --locked python -m unittest discover -s tests
```

Run the explicit offline smoke check for each model, in separate commands/processes:

```sh
uv run --locked python scripts/model_smoke.py gliclass
uv run --locked python scripts/model_smoke.py laya
```

Each smoke run loads one model, performs one excluded warm-up call, then predicts a database-timeout, healthy, and disk-full example. Output separates API/load success from semantic expectation results: exit status reports that calls completed, while `semantic_expectations` reports label matches. These three examples are a smoke check, not a quality evaluation.

## Evaluations

Run one backend per process:

```sh
uv run --locked python -m decisionops evaluate --backend rules --output-dir reports/baseline
uv run --locked python -m decisionops evaluate --backend gliclass --output-dir runs/gliclass
uv run --locked python -m decisionops evaluate --backend laya --output-dir runs/laya
```

Run all three workers sequentially, each in a fresh process. Use a new output directory for each evidence run:

```sh
uv run --locked python -m decisionops evaluate --backend all --output-dir reports/milestone-20260927
```

Each worker writes `predictions.jsonl`, `summary.json`, `summary.md`, and `run-status.json`. The all command writes `all-summary.json` and `all-summary.md`, including a comparison table, worker status, core misses, prediction disagreements, and provenance consistency. Failed reruns clear old worker results first. No worker runs concurrently. `reports/baseline/` is historical evidence from the earlier implementation and must not be overwritten; see [reports/README.md](reports/README.md).

The first 32 examples are unambiguous, eight per class. The final 16 are challenge cases. Core metrics use only the first group; abstentions count as wrong for accuracy and also reduce reported coverage. The seven labeled challenge cases are scored separately. The nine review cases have no forced gold class; reports count abstentions and forced predictions without assigning review accuracy. The challenge-04 annotation classifies the explicit database timeout as `database_failure`.

## Scores and measurements

- Rules return a selected class or abstain and never invent probabilities.
- GLiClass uses the pinned pipeline's single-label softmax and complete `return_hierarchical` score map, with flat short human-readable candidate names. The controlled format diagnostic found that the tested checkpoint performed better and more consistently with these native short names than with descriptive or hierarchical strings; see `reports/gliclass-format-diagnostic-20260927/`. GLiClass names and Laya's description-bearing criteria are deliberately different representations. Scores are model probabilities, not calibrated confidence.
- Laya's native probability output, `confidence` (one minus normalized entropy), and `answer_confidence` are retained under separate names when returned. `action_act_probability` records the separate action head and is not a class score or authorization to act.
- One explicit warm-up prediction per model is omitted from inference latency statistics. Sample count, linearly interpolated p50/p95, model loading time, and Linux worker-process high-water RSS are recorded separately. RSS includes the whole process, not only model weights.
- Reports record Git HEAD and dirty paths, hashes of the implementation files and dataset, candidate IDs/names/descriptions and exact backend input representation/order, package versions, checkpoint revisions, Python/platform/hardware details, four PyTorch CPU threads, and batch size one.

The rules baseline uses a small list of readable category/failure patterns and abstains when it sees multiple current fault categories, weak evidence, negation, or historical evidence. It is intentionally incomplete: English phrasing, clause structure, and unseen terms can cause misses or false matches. The classifiers are also not validated for calibration. No threshold fitting or calibration is done on this dataset. Measurements on 48 short examples are noisy and should not be read as a definitive speed or quality comparison.

## Recorded diagnostic workflow milestone

The workflow is a bounded **offline synthetic simulation**, not live incident response. Its four tools only reveal a checked-in fixture observation when requested. It never executes shell commands, contacts a service, or changes the host. The policy receives only the initial report, observations requested so far, attempted tools, budgets, and visible harness feedback. Scenario IDs, gold outcomes, evaluation evidence annotations, and unrequested fixture observations stay with the evaluator/simulator.

There are four unique tool calls maximum and six decisions maximum per episode. A tool cannot be repeated. The available terminal actions are database failure, authentication failure, disk full, healthy, and review. The harness rejects malformed/unknown/ineligible proposals and unseen evidence references. One rejected diagnosis may be retried; a second unsupported diagnosis ends the episode. A high score cannot bypass action eligibility.

Diagnosis evidence is checked deterministically from current successful observations. Database, authentication, and disk diagnoses require an explicit current failure fact; conflicting current signals or multiple fault categories fail the check. Healthy requires explicit passing current observations from all four tools. Any unresolved timeout/error blocks diagnosis. The harness rejects unsupported diagnoses and reports its reason; it never substitutes the hidden gold diagnosis. Observation IDs on accepted diagnosis proposals are attached by the harness from the structured facts when the policy omits them. These IDs are provenance references, not model explanations or chain of thought.

The fixed-order policy checks database, authentication, storage, then service health before using the evidence check. The rules policy prioritizes tool cues in the visible report, then supported evidence, then the fixed fallback order; a visible tool failure leads to review. `gliclass` and `laya` choose among all harness-eligible actions. Their `*_evidence_masked` variants use the same policies and models but remove diagnoses that fail the existing visible-state evidence check before scoring. Both variants always retain `request_review`; neither uses hidden scenario data. The policies share deterministic candidate selection, and the harness validates every proposal after selection.

GLiClass receives the rendered visible-state text plus an ordered list of stable action IDs and readable names. Laya receives the same visible-state text through its native choice API, with stable action IDs mapped to readable choice names and fixed concise descriptions. Laya's question and descriptions are fixed before evaluation and recorded in provenance. Since the model families receive different native input formats, this comparison does not isolate architecture. Laya's native choice probabilities are retained separately from its optional `confidence`, `answer_confidence`, and `act_probability` metadata; none is calibrated for this workflow or authorizes action execution. One-choice Laya questions still go through model inference; the installed API supports a single criterion.

Each v3 trace records both the harness-eligible actions and model-scored candidate IDs, deterministic exclusion reasons, exact model inputs, and Laya's native output metadata. Replay accepts v1, v2, and v3 traces without loading a model. Reports list every terminal status and reason, count failed episodes, and separate unsupported diagnosis attempts from invalid proposals; see [FINDINGS.md](FINDINGS.md) for definitions and results.

`data/diagnostic_scenarios.jsonl` is the frozen synthetic suite: 12 development and 12 evaluation scenarios. It includes the supported faults, healthy cases, vague and historical reports, multiple and contradictory faults, unavailable tools, insufficient evidence, and unrelated requests. It is not independently validated real-world performance. Policy changes after viewing evaluation results should be recorded and evaluated on development scenarios first.

Run a single scenario (available IDs are in the JSONL file) and save its replay trace:

```sh
uv run --locked python -m decisionops workflow episode \
  --scenario-id dev-database-clear --policy rules \
  --trace-file runs/workflow-database-example.jsonl
```

Run the development-only comparison first, then the full two-split comparison with both pinned local checkpoints. GLiClass and Laya each run in a separate sequential worker process; each process reuses its model for the two variants and exits before the next family loads. Use fresh output directories. Replay a saved trace without invoking a policy/model:

```sh
uv run --locked python -m decisionops workflow evaluate --split development \
  --output-dir reports/workflow-model-comparison-development-final-20260927
uv run --locked python -m decisionops workflow evaluate --split all \
  --output-dir reports/workflow-model-comparison-20260927
uv run --locked python -m decisionops workflow replay \
  --trace-file reports/workflow-model-comparison-20260927/examples/fixed-order-database-example.jsonl
```

Each invocation requires a new output directory. `run-status.json` distinguishes evaluation execution and worker completion from policy outcomes; an incomplete worker leaves no `all-summary.json` and cannot publish staged results as a complete run. The prior reports at `reports/diagnostic-workflow-20260927/` and `reports/gliclass-evidence-mask-20260927/` remain historical and are not overwritten. This scenario suite has been inspected; the evaluation split is a synthetic regression comparison, not untouched held-out evidence. The full report compares six policies and all terminal outcomes. Each model's load time and worker-process peak RSS are recorded independently. The two variants share their model family's load time and worker high-water RSS. Fixture latency does not represent live tool latency.

The comparison creates per-policy JSON summaries, one JSONL trace per scenario, an example trace, `all-summary.json`, a Markdown comparison, and `provenance.json`. Diagnosable and review-required scenarios use separate denominators, so review-everything scores no supported diagnoses and its unnecessary reviews remain visible. Reports separate unsupported diagnosis proposals, invalid proposals rejected by the harness, terminal reasons, failed episodes, budget exhaustion, tool-related failures, simulator failures, tool calls, per-episode end-to-end latency, model load time, and peak process RSS. For every policy/split, terminal-reason counts sum to episode count; any failed terminal episode marks that policy run failed. Tool fixture timeouts/errors are recorded observations; they are not simulator failures. Provenance captures code and scenario hashes, package versions, checkpoint revision, candidate names/order, and runtime settings.

The tests for the workflow are model-free and run with the existing suite. The explicit cached-checkpoint workflow smoke test is separate:

```sh
uv run --locked python -m unittest discover -s tests
uv run --locked python scripts/workflow_smoke.py
```

The smoke test makes one bounded GLiClass episode; its selected outcome is diagnostic smoke evidence, not an accuracy claim. The full comparison command above is the reproducible synthetic evaluation.

Model loading can emit upstream PyTorch/Transformers/GLiClass warnings, including TorchScript deprecation and model-type warnings. They are not globally suppressed. Laya can warn that a checkpoint choice-head temperature is clamped; that warning is retained and does not establish calibration for this four-choice task.
