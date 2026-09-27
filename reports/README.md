# Evaluation evidence

`baseline/` is historical evidence from the earlier implementation at commit `bc56acb51110bec8e1bfc92905c041caaf0245d1`. Its results are retained unchanged, including its older annotations and report format.

The first corrected reproducible evaluation milestone is written to `milestone-20260927/`. It records corrected dataset annotations, adapter input representations, output validation, separate core/challenge/review metrics, sequential worker status, and provenance. Reproduce from the repository root with:

```sh
uv run --locked python -m unittest discover -s tests -v
uv run --locked python scripts/model_smoke.py gliclass
uv run --locked python scripts/model_smoke.py laya
uv run --locked python -m decisionops evaluate --backend all --output-dir reports/milestone-20260927
```

The model commands set Hugging Face offline mode and require the pinned weights to already be cached. The aggregate report marks failed workers and omits its comparison table unless all three workers complete with matching dataset, candidate specification, Git HEAD, and implementation hashes. Predictions contain evaluation annotations for audit after inference; adapters receive only incident text.

`gliclass-format-diagnostic-20260927/` records a controlled investigation of GLiClass’s input format and candidate order. Its findings and exact reproduction commands are in [FINDINGS.md](gliclass-format-diagnostic-20260927/FINDINGS.md), with raw per-call logits and scores in `diagnostic.json`. The adapter update is evaluated separately in `milestone-20260927-flat-short-gliclass/`; it preserves the earlier report unchanged.
