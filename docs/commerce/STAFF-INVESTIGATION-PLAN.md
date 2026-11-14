# Staff shipment investigation slice

Baseline: 1a0e685, clean, preserved on feat/commerce-openai-investigation. New work
on feat/commerce-staff-investigation. User authorized coherent implementation without
routine approval gates. Reuse existing adaptive services, queue, fencing and exact
proposal/review/execution services; no migration or paid transport in web workers.

Admission: authenticated/store-scoped POST shipment-investigation with bounded report,
request_id and expected_generation. Case lock serializes idempotent event/run creation.
Same request ID replays its original run; changed content conflicts. Existing matching
active run is returned. Stale generations and concurrent legacy work conflict.
Case GET exposes a staff-safe progress projection; GET never advances work.

Worker claims only staff-tagged adaptive jobs. Rules are default; explicit server mock
mode uses DecisionsConfig execution=mock and injected MockTransport, never credentials
or a live client. Existing legacy worker continues approval/execution. No inference
or delay under locks. Browser polls durable state; selection survives page reload via
URL fragment, credentials still require sign-in. Disabled buttons plus synchronous
in-flight guard supplement server idempotency; no client-only guarantee.

Missing-evidence continuation is an explicit staff-run contract flag, preserving
historical runs/frozen evaluations. Only valid unknown_evidence review with a current
applicable read and remaining budgets may become a deterministically selected read.
Record original recommendation and continuation separately, charge the additional
choice, retain tool/deadline caps. Known blockers, stale observations, manual review,
refusal, uncertainty and exhaustion keep review/blocker paths. Never invent evidence.

Checks: focused PostgreSQL API/engine continuation/idempotence tests first, real
browser/API/two workers in an independent fictional DB/ports; eligible all seven
reads including stock -> proposal -> exact human approval before execution; missing
history -> review/no execution. Refresh and duplicate requests create one adaptive
run and at most one execution. Mock early review exercises continuation visibly.
Use cached frontend/browser dependencies/images only. Keep isolated demo running for
Richard after demonstration; record precise start/stop commands and screenshots.
