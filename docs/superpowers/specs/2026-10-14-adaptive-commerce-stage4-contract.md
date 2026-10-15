# Stage 4 reusable session contract — frozen before implementation

Accepted baseline: 5ecee30fdcead58a97402af624984f6bab0b429c, preserved on
feat/commerce-adaptive-recovery. New branch/worktree: feat/commerce-adaptive-sessions,
adaptive-sessions. Stage 4 only; real cached checkpoint loading/comparison is Stage 5.
Supervisor verified reconstruction, mocked guards, CI success and changed-source
identity; PostgreSQL executions are agent/CI attributed. No original runtime writes.

## Wire protocol commerce-adaptive-session/v1

Four-byte unsigned big-endian payload length followed by strict UTF-8 JSON object.
Reject zero length, duplicate keys, nonfinite numbers, invalid UTF-8, trailing JSON,
unknown keys/types and premature EOF. One serialized outstanding request, no replay.
Envelopes carry protocol, type, session_id and sequence. Preload is sequence 0 with
configuration (family/revision; audit only); readiness echoes configuration and
reports measured load/RSS. Requests sequence 1..16 contain request_id and features;
results echo all correlation fields with action_index, native scores/meaning,
inference_ms and RSS. Error echoes the corresponding correlation with bounded kind.
Close (or cancel) ends the child, no acknowledgement required. Correlation/config
metadata is never model text: only six existing PolicyRequest.features fields enter
inference. Parent maps action_index to its immutable allowed list, then existing
recommendation/application validators recheck current state. Confidence is an
uncalibrated native estimate, never permission. Legacy one-shot/routing unchanged.

Exact byte caps (headers count toward stream/session totals):
- Parent payload/frame: 32,768 bytes, header 4; at most 18 frames (preload, 16
  requests, one close/cancel), cumulative stdin 589,896 bytes.
- Child payload/frame: 65,536 bytes; cumulative stdout 65,536 bytes and stderr
  65,536 bytes over the entire session, never reset per request.
- Whole output: 131,072 bytes; whole duplex maximum 720,968 bytes. A maximal output
  payload plus its header exceeds stdout total and is therefore rejected.
- Retained diagnostics: first 1,024 bytes/stream; framing storage bounded by stdout
  cap, result queue at most two frames. Overflow detected while draining, at most
  one proof byte beyond a cap. No communicate(), unbounded files or EOF waits.

Continuous reader drains both streams while idle/working; unexpected or mismatched
frames fail immediately. Parent terminates its owned process group, closes pipes
without waiting for descendant EOF, and reaps the direct child within one second
(plus at most 0.2s reader join). Cleanup timeout is reported, never an unlimited wait.
Child watchdog kills its group on parent loss or absolute run deadline, including
loading; no idle persistent daemon. Parent cancellation/lease loss kills the group.

## Resource/ownership and persistence

One child per live run session, one pinned family loaded once, CPU four threads,
batch one. Shared host-local advisory file lock across all cooperating adaptive
families (including fake sessions), securely owned by current UID, non-symlink,
held by parent and inherited child. External non-cooperating model processes and
legacy one-shot invocation are not controlled by this lock; operators must not
run them concurrently with a local session. Slot wait <=30s, preload <=120s,
each decision <=20s, absolute run <=240s including queueing/wait/load/checkpoints.
Optional smaller test/operator bounds are admitted; never larger ones.

Current unexpired job ownership is checked/renewed during waiting/loading/decision
work; renewal never extends run deadline. No database transaction/business lock
spans model work. Existing case revision, pending/context tokens, result admission
and deterministic publication/approval/execution guards remain authoritative.
Shutdown closure events/fences are not graph checkpoint state.

Add migration 0008 after actual 0007: immutable session bindings plus measured
waiting/load/inference/total phases, reload index, diagnostics and disposition.
Reserve waiting+preload maximum (<=150,000ms and remaining run/resource limit)
atomically before waiting/launch. Combined phase reservations/known waiting+load
and decision ledger reservations/known inference <=240,000ms. Max three session
attempts/run (two reloads); restart cannot reset phases/counters. Known readiness
settles waiting/load, inference stays in existing decision ledger; total lifetime
is reported separately, not double-counted. API charge exact Decimal zero; no token
counts or artificial dollar pricing. Fake measurements clearly labelled simulated.

Unknown preload/session state requires explicit current-owner recovery, retains
its reservation, never automatic relaunch. Ready child lost on restart also needs
explicit retirement before a new counted reload. Dispatched decision uncertainty
uses unchanged explicit recovery/no redispatch. Known failure can record bounded
fixed fallback/review. Old undispatched configuration no longer admitted by current
pins produces controlled no-dispatch; historical inspection uses recorded revision
without consulting pins. Never substitute another checkpoint. Forced single-choice
requests skip slot/phase reservation/child/model entirely and record zero inference.

## Delivery/verification rulings

Implement optional CLI session selection only; browser/API/ordinary worker remain
rules-only. Fake children prove framing/cumulative caps, continuous draining,
deadlines/descendants, actual CLI shutdown, lease loss, restart/resource retention,
load once, and legacy one-shot compatibility. Cached integration reuses exact
existing offline loaders and corrected GLiClass/Laya choice mapping but is not run.
A source-only CI mirror may exclude local docs; no rejected uploads repeated.
Stage 5, training/downloads/upgrades/paid calls/AWS/runtime migration remain excluded.

## Resolved implementation decisions

The parent records immutable configuration/session correlation separately from the
six-field feature object. The child receives metadata for admission and framing,
but model text contains only report, requested observations, allowed actions,
attempt history, remaining budgets and rejection feedback. One-child lifetime is
one live invocation of a durable run; explicit restart retirement can allocate a
new ordinal, never pretend it continued the old process. No idle daemon exists.

Session-backed graph resume advances domain work outside the checkpoint saver and
projects committed state using a freshly renewed lease afterward. Otherwise a
valid long preload would incorrectly exhaust the saver connection's original
lease deadline. Rules-only graph advancement remains unchanged. Unknown preload
and resource-review outcomes are returned immediately, with persisted phases in
inspection, rather than hidden behind repeated graph projections.

Known correlated child errors settle the applicable measured resource use and
record permanent fixed-policy fallback for subsequent decisions. Malformed frames,
timeouts, cancellation after launch and lost responses remain uncertain. A
no-child launch/admission failure has known no-dispatch disposition. A recorded
request referring to a vanished session never silently acquires a replacement
session; its controlled known failure permits counted fallback. Inspection reads
recorded checkpoint identity without consulting current pins.

Parent measured waiting/load includes startup and admission overhead; child native
load_ms measures its narrower loader phase. Decision inference is charged once in
the existing ledger. Session total/run wall time is telemetry, not another charge.
Preload diagnostics and audit updates do not mutate case/context or invalidate the
reserved decision. Both bounded lease deadlines and shutdown are checked by the
session even if its database renewal thread stalls.

After direct-child exit the reader drains all immediately available buffered
output through the cumulative caps before finalizing a valid last frame. It never
waits for descendant EOF. A known error followed by clean EOF stays known; buffered
surplus or overflow after a valid response fails. Deterministic buffered-stderr
regression consumes exactly 65,537 bytes and retains 1,024, including the overflow
proof byte. Cleanup remains group kill plus bounded direct-child reaping.

Three allowed child-session attempts bound whole-run transport by stdin 1,769,688 bytes, stdout 196,608, stderr 196,608, output 393,216 and duplex 2,162,904 bytes. Each individual session retains at most 2,048 diagnostic bytes (6,144 across the three session rows). Audit events can repeat these bounded snapshots; they are not another process stream.
