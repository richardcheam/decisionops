# Cached local Commerce routing: integration results

Agent-executed offline CPU integration on Richard’s MSI, 2026-10-14. No API charge,
no downloads/upgrades, no CUDA. Four threads, batch1, one family per process.

Only **one distinct meaningful scored input** exists: all seven facts are true.
The seven tri-state facts allow 2,187 vectors, but 2,186 have one permitted choice
and require no inference. An unknown-history example verifies this forced path.
Repeated executions verify integration; they are not additional quality samples.

| Provider | Eligible choice / real effect | Present / review score | Load s | Inference s | Wall s | Peak child RSS MiB |
|---|---|---|---:|---:|---:|---:|
| Rules | present / awaiting_review | deterministic | — | — | — | — |
| gliclass | staff_review / escalated | 0.3367 / 0.6633 | 19.077 | 0.534 | 21.417 | 741.8 |
| laya | staff_review / escalated | 0.3518 / 0.6482 | 14.660 | 1.539 | 18.072 | 2592.9 |

Both models disagreed with the reference policy on the sole scored input. Neither
result created approval or executed a replacement. Unknown history produced
needs_review for rules and forced deterministic review for both models, with zero
dispatch/load. Approval remains mandatory; confidence never grants permission.

GLiClass uses the existing corrected flat-label single-label pipeline; its scores
are softmax probabilities across allowed labels. Laya retains native choice
probabilities, confidence, answer_confidence and action_act_probability separately.
All are uncalibrated. Its action head was 1.0 despite choosing review; this value
was recorded and never treated as authority. Native input formats differ.

Loading includes imports/checkpoint/tokenizer loading. Wall includes subprocess
startup/cleanup. RSS is the child high-water mark in KiB, not incremental model
memory or total system use. First probe loading took about 19–24 seconds; final
measurements reflect cache warmth and concurrent host work, not a speed benchmark.
No invented token counts or simulated USD prices are attached to local inference.
Zero API charge does not mean zero CPU/memory/power cost.

Pins: GLiClass 21edefaf7951f68c68c505f9139ba536d3b448f7;
Laya 55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851.
Packages: torch 2.14.0+cpu, transformers 5.17.0, gliclass 0.1.20, laya 0.3.20,
huggingface-hub 1.33.0 (existing locked environment).

[Final comparison and implementation hashes](comparison.json) includes dirty-tree
provenance (pre-commit), permitted features, native results and actual routing.
[First comparison](first-comparison.json) is preserved; it had the same choices
and distributions. It predates explicit validation-outcome trace metadata.
The initial direct adapter probe is retained in ignored runs/local-providers.
No prompt/label tuning followed the measured disagreement.

This establishes adapter integration and limited reference-policy agreement only.
It does **not** establish held-out generalisation, business value or production
accuracy. Historical incident results remain separate and unchanged.

Reproduce from [RUNBOOK](../../docs/commerce/RUNBOOK.md#optional-cached-local-laya-and-gliclass-routing).
Source-review/CI contract doubles do not load/download models. All runs here were
agent-executed; no Richard-run commands or model verification are claimed.
