# DecisionOps: local incident classification evaluation

This is a small CPU-only development harness comparing a readable rules baseline with GLiClass and Laya. It classifies recorded text only and never runs operational actions. The 48 hand-authored examples are development data, not a held-out benchmark or evidence of production accuracy.

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

Each smoke run loads one model, performs one excluded warm-up call, then predicts a database-timeout, healthy, and disk-full example. Loading and per-example inference times are printed separately. It is only a load/API smoke test, not a quality evaluation.

## Evaluations

Run one backend per process:

```sh
uv run --locked python -m decisionops evaluate --backend rules --output-dir reports/baseline
uv run --locked python -m decisionops evaluate --backend gliclass --output-dir runs/gliclass
uv run --locked python -m decisionops evaluate --backend laya --output-dir runs/laya
```

Run the three workers sequentially, each in a fresh process:

```sh
uv run --locked python -m decisionops evaluate --backend all --output-dir runs/all
```

Each worker writes `predictions.jsonl`, `summary.json`, and `summary.md`. The all command writes `all-summary.json` and `all-summary.md`, including each worker's exit status and error tail. No worker runs concurrently. Outputs under `runs/` are ignored by git; the committed baseline under `reports/` is retained for review.

The first 32 examples are unambiguous, eight per class. The final 16 are challenge cases. Metrics use only the first group; abstentions count as wrong for accuracy and also reduce reported coverage. Challenge cases and annotation expectations are reported separately. Review-needed cases have no forced gold class.

## Scores and measurements

- Rules return a selected class or abstain and never invent probabilities.
- GLiClass uses its pinned pipeline's single-label softmax and complete `return_hierarchical` score map. These values are model scores, not calibrated confidence.
- Laya's native probability output, `confidence` (one minus normalized entropy), and `answer_confidence` are retained under separate names when returned. `action_act_probability` records the separate action head and is not a class score or authorization to act.
- One explicit warm-up prediction per model is omitted from inference latency statistics. Sample count, linearly interpolated p50/p95, model loading time, and Linux worker-process high-water RSS are recorded separately. RSS includes the whole process, not only model weights.
- Reports record package versions, checkpoint revisions, dataset SHA-256, four PyTorch CPU threads, batch size one, platform and available hardware details.

The rules baseline uses a small list of readable category/failure patterns and abstains when it sees multiple current fault categories, weak evidence, negation, or historical evidence. It is intentionally incomplete: English phrasing, clause structure, and unseen terms can cause misses or false matches. The classifiers are also not validated for calibration. No threshold fitting or calibration is done on this dataset. Measurements on 48 short examples are noisy and should not be read as a definitive speed or quality comparison.

Model loading can emit upstream PyTorch/Transformers/GLiClass warnings, including TorchScript deprecation and model-type warnings. They are not globally suppressed. Laya can warn that a checkpoint choice-head temperature is clamped; that warning is retained and does not establish calibration for this four-choice task.
