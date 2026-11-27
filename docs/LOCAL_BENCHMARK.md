# Local Ollama benchmark

## Protocol

Compare the built-in rules and the app’s Ollama mode on paired fictional
customer and staff workflows. Each arm starts in a fresh PostgreSQL schema
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
