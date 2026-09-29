# Workflow worker deadlines and cancellation

`workflow evaluate` runs each model family in a separate sequential worker process. The `--worker-timeout-seconds` option sets a deadline independently for each worker, including model loading and both of that family's policy variants. Its default is 600 seconds. The value must be finite and greater than zero; it is checked before the output directory is created. This is neither a per-inference deadline nor a whole-suite deadline.

On Linux, each worker starts in its own process session. When its deadline expires, or the evaluator receives Ctrl-C or SIGTERM, the evaluator sends a graceful termination signal to that worker's process group, waits for a bounded grace period, then escalates to a kill signal if processes remain. It reaps the worker and removes its unpublished staging files. Signal handlers are restored when evaluation finishes.

The evaluator exits 124 for a worker deadline, 130 for Ctrl-C, and 143 for SIGTERM. A normal worker error exits nonzero. `run-status.json` is written atomically and records the run outcome, configured per-worker deadline, worker elapsed time, termination reason, and workers that were not run. Completed family results remain available as partial evidence. The evaluator publishes `all-summary.json` and `all-summary.md` only after every required worker completes; timeout, cancellation, and worker failure do not create a successful aggregate comparison. No episode outcomes or replay events are fabricated for a terminated worker.

Use a fresh output directory for each retry or rerun:

```sh
uv run --locked python -m decisionops workflow evaluate --split all \
  --worker-timeout-seconds 600 --output-dir runs/workflow-evaluation-2026-09-29
```

SIGKILL, machine failure, and an uninterruptible operating-system task cannot be handled like graceful cancellation. In those cases the evaluator cannot promise that the worker or its temporary files were cleaned up. Worker stdout and stderr are written to staging files to keep memory use bounded; only their final 4,000 bytes are retained in the process status record.
