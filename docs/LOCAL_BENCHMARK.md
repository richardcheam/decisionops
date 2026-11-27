# Local Ollama benchmark

Both modes reached all five expected outcomes on the frozen synthetic cases.
Rules reached them faster in this run. Keep rules as the demo default. Offer
Ollama as an opt-in assistant for evaluating language coverage, with all
eligibility rules and staff approval checks in place.

| Case | Result in both modes | Rules | Ollama | Ollama requests |
|---|---|---:|---:|---:|
| Lyon | Replacement created, one reservation, unshipped | 1.908 s | 5.218 s | 6 |
| Split parcel | Clarification, no report filed | 0.051 s | 0.531 s | 1 |
| Wrong owner | Access denied | 0.017 s | 0.018 s | 0 |
| Stale carrier record | Staff review, no proposal | 1.660 s | 5.013 s | 6 |
| Carrier outage | Staff review, no proposal | 1.663 s | 5.024 s | 6 |

All five pairs had matching business input hashes. Ollama returned 19 valid
choices in 19 requests, with zero timeouts, invalid replies, transport errors
or fallbacks. Median request wall time was 0.643 seconds, with a range of
0.403–0.782 seconds. Those timings include local HTTP and response
validation. Case times include application and worker work, including time
waiting for the serial request lock. They exclude seed setup and cold
warmup. This is one run on one laptop.

The split-parcel safeguard asked for clarification after the model chose to
report nonreceipt. The wrong-owner denial came from authorization without
inference. In the two review cases the shipment branch read the carrier
record and recorded stale evidence or missing evidence. No review or denial
case created a replacement or reserved stock.

The development slice also reached the replacement outcome in both arms.
It used six valid local requests. The benchmark added measurement and database
checks without changing the shipped prompts, policies or deadlines. The
preflight returns misclassification and small set of scenario templates limit
what this run says about adopting the model for everyday chat.

## Regression checks

The required PostgreSQL profile passed 272 tests. The compact browser suite
passed all eight, including Lyon's exact proposal approval and separate
execution confirmation, and Saint-Denis review. The process recovery check
reused two committed specialist steps and kept one operation, replacement and
reservation after repeated confirmation. The dependency-free profile reported
147 passes and 346 optional skips. These checks used no live inference.

## Protocol

The benchmark compares two complete product modes: built-in rules and local
Ollama. The original brief also called for a fixed-choice version of the same
specialist graph, which this run did not include. The comparison measures the
overall product trade-off and leaves the isolated effect of model-directed
reads open. Each arm starts in a fresh PostgreSQL schema
with matched source data. The five frozen cases cover a verified replacement,
a split parcel that needs clarification, wrong-owner access, stale carrier
evidence and a carrier outage. The wrong-owner case is an access control
check. These are new messages on existing scenario templates, so the benchmark
does not test generalization to new business situations.

Count a case as successful only when it reaches its labeled outcome. Track
early errors, valid and invalid model choices, timeouts, and any fallback
separately from case success. Approval and creation remain separate authorized
actions. Verify the replacement and reservation in PostgreSQL. Record model
request wall time and case wall time separately. The rules arm makes zero
model requests. The development case uses the original harness messages.

Use qwen35-local:2b and the shipped request deadlines. Start with a warmed
runner. Run timed requests serially. Cap each held-out attempt at 40 local
inference requests and the development slice at 12. A timeout or malformed
choice stays in the result. Stop on a missing local model, an unavailable
database, a mismatched source hash, or the request cap. Keep raw logs in
ignored runs/. Do not change behavior based on held-out results.

## Machine and preflight

The installed model was `qwen35-local:2b`, ID `806d46073db0`, a Qwen3.5
1.9B model quantized to Q4_K_M. Ollama 0.40.18 reported 100% GPU inference
and a 4096-token context on a GTX 1050 Ti Max-Q with 4 GiB of VRAM.
The host CPU was an Intel Core i7-8750H.

`scripts/check_local_model.py` warmed the model in 6.53 seconds. Three of
four choices passed both times. The returns question took 0.43 seconds and
then 0.42 seconds on retry. Both responses were valid `support_help` choices
where the check expected `returns_help`. Local connectivity, structured
output and the deadline worked on these calls. The error was a
misclassification. The prompt, model and deadlines stayed fixed.

## Reproduce the comparison

Install the locked Commerce dependencies with `uv sync --locked --only-group
commerce`. Point `COMMERCE_TEST_DATABASE_URL` to a disposable PostgreSQL
database on loopback. Warm the installed model with
`COMMERCE_LLM_MODEL=qwen35-local:2b python3 scripts/check_local_model.py`.
Run from the repository root with no other Ollama jobs active.

```bash
mkdir -p runs/benchmark
COMMERCE_OLLAMA_URL=http://127.0.0.1:11434 \
  .venv/bin/python -B -m decisionops.commerce.customer_evaluation \
  --local-model qwen35-local:2b --max-calls 40 \
  --cases data/commerce/local-benchmark/heldout.json > runs/benchmark/heldout.json
```

The held-out file was committed in `2f51227`. Its SHA-256 is
`2989008435a44c73c8bc94d1db233ced84a4cb126768ed902316d5226544645c`.
