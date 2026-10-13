# Durable local worker and graph checkpoints

Autonomous local continuation authorized by Richard; no paid inference/export.
Locked dependencies: langgraph 1.2.15, checkpoint-postgres 3.1.3. Existing model
package versions remain untouched and excluded from commerce-only installation.

PostgreSQL jobs own scheduling: queued/running/completed/failed, maximum three
attempts, database-clock lease, opaque claim token and one queued/running job per
case (partial unique index). Claim uses FOR UPDATE SKIP LOCKED. Expired leases can
be reclaimed; a stale token cannot commit. Node locks job, then case/business in
one READ COMMITTED transaction; checks lease again before committing the domain
result and job outcome. Crash/timeout rolls back or leaves a reclaimable lease.
Enqueue serializes on case, never locks an existing job while holding case, avoiding
job->case/case->job inversion. Failure logs contain error type only, no SQL/secrets.

LangGraph observes job result and routes eligible investigations to a persisted
review interrupt. Checkpoints live in a separate graph schema derived from the
business schema, managed by PostgresSaver.setup, not Alembic business migrations.
No transaction is held while waiting for review. Resumption reads durable case
review: interrupt payload cannot grant approval. Execution is an explicit queued
job with the approved stable operation ID; domain service enforces approval.

Business result/job completion commits before graph checkpoint. If the checkpoint
write fails after commit, replay uses saved job outcome and does not rerun the
business operation. A completed job may be explicitly replayed to repair graph
projection. Pending review graph does not count as an actively running job.
Worker runs once or polls until SIGINT/SIGTERM; no paid calls, model loads, or
LangSmith export even if unrelated tracing environment variables exist.

Tests: separate claims, expired-lease recovery, stale-worker fencing, post-commit
checkpoint failure/replay, paused approval survives process restart, fake resume
cannot approve, execution job reconcile/idempotency, attempt exhaustion. Operational
CLI commands: setup, enqueue, once, run, show, replay, resume. Persistent business
cases remain authoritative when workflow projection is incomplete.
