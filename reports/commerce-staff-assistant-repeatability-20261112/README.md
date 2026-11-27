# Staff-assistant review and repeatability evidence

Baseline preserved: `1a0e685fa0e865b002410a85db1678a1b36e313c`.
Initial staff checkpoint preserved: `3916e5da6fd9362a14fadcc270c6997ad5614d4a`.
Reviewed follow-up source: `1baf05e685a5a662267ec2add9661324fd6b4812`, branch
`feat/commerce-staff-investigation`. Final documentation commit follows that source.
No publication, paid calls, model loads, dependency changes or original-runtime work.

[Staff instructions and exact clean-checkout startup/stop](https://github.com/richardcheam/decisionops/blob/a816f6191af1b2ebda9863e1fa20ffdcf6416a14/docs/commerce/STAFF-ASSISTANT.md).
[One-shop read-only pilot boundary](https://github.com/richardcheam/decisionops/blob/a816f6191af1b2ebda9863e1fa20ffdcf6416a14/docs/commerce/PILOT-HANDOFF.md).
The temporary clean checkout was stopped/removed after 28 generated files were
copied and individually SHA-256 verified. The original staff demo stays on 55521;
its processes/data were retained and only the tested generated UI assets updated.
The original migration-0004 app on 8080/55432 was not operated on.

## Observed behavior, separated by mode

| Local evidence | Rules | Mocked Decisions HTTP transport |
|---|---|---|
| Eligible browser case | 7 reads, valid proposal, exact staff approval and separate confirmation, 1 verified replacement | Same; 7 additional deterministic continuation steps |
| Incomplete compensation history | Review, history unknown, no proposal/operation | Same; 8 continuations, decision budget reaches16 |
| Full page reload and duplicate admission | Passed | Passed |
| Model inference / paid calls | None / 0 | None / 0; simulated usage only |

See [summary.json](summary.json) for actual run IDs, counters and complete terminal
summaries. Successful fictional execution was agent-driven Playwright clicking
explicit staff controls; neither rules nor the mock approved/executed anything.
The two modes used fresh different schemas, not repeated compensated orders.
Richard reported trying the browser and that it seemed to work; no exact test or
approval/execution result is attributed to him.

Screenshots: [rules proposal](rules-proposal.png), [rules incomplete](rules-incomplete.png),
[rules progress](rules-progress.png), [mock proposal](mock-proposal.png),
[mock incomplete](mock-incomplete.png), [mock progress](mock-progress.png).
The original screenshots/report at ../commerce-staff-assistant-20261112 remain unchanged.

## Focused source/test review map

| Guarantee | Source | Existing executed evidence |
|---|---|---|
| Same request ID replays; changed content conflicts | `staff_investigations.enqueue`, durable case events and case lock | `test_duplicate_admission_refresh_and_rules_proposal`; `test_mode_cannot_enable_paid_provider_and_report_is_bounded`; browser eligible test repeats identical POST |
| Different ID, same report joins active work; accepted aliases replay after completion | Same admission function | `test_all_accepted_request_ids_replay_after_completion` |
| Different active report cannot compete | Same admission function,409 conflict | `test_different_report_cannot_compete_with_active_request` (new) |
| Refresh resumes persisted progress, no advancement from GET | `api.get_case`, `staff_investigations.view`; React hash selection/polling | Both browser eligible runs reload/re-authenticate and see saved report/proposal; backend repeated GET |
| New investigation invalidates old approval/proposal | `adaptive_investigations.start` increments generation, captures revision and clears both pointers; immutable history retained | `test_new_staff_request_revokes_exact_old_proposal_approval` (new), legacy core `test_start_captures_resulting_revision_and_revokes_approval` |
| Execution requires current exact approval | `cases.review_case`, `execution.execute`: case/generation/proposal/hash/request/operation bindings, business locks and final recheck | Focused `test_duplicate_execution_queues_one_job_after_exact_approval`, new revocation regression; both browser eligible tests reject unapproved execution, click two confirmations and see one executed event |
| Incomplete evidence cannot propose | `adaptive_investigations.allowed/publish/safety_check`, seven-tool summary and legacy attestation | `test_missing_history_reviews_and_no_execution`; both browser incomplete tests; required core `test_incomplete_propose_has_no_safety_reads` |
| Original provider recommendation remains separate | `adaptive_investigations.advance` records `deterministic_continuation` linking recommendation ID, then validates/counts read; `staff_investigations.adapter_for` injects mock transport | `test_mock_early_review_continues_with_separate_audit`; mock browser expands continuation explanation; durable mock export contains original review results AND continuation steps |
| Legitimate review, cap, expiry, stale evidence retained | Same deterministic service/worker | Focused manual/refusal, budget16, overdue job and discarded-true-read regressions;194 required database checks |
| Paid operator jobs cannot be claimed by web workers | `adaptive_jobs.claim(staff_only=True)` and legacy partition; staff adapter rejects live config | `test_staff_and_ordinary_workers_do_not_claim_operator_api_jobs`; launcher rejects live mode |

Paths: [focused backend tests](../../tests/test_commerce_staff_investigation.py),
[browser tests](../../frontend/staff-tests/shipment-assistant.spec.ts),
[admission/worker](../../decisionops/commerce/staff_investigations.py),
[adaptive validation/publication](../../decisionops/commerce/adaptive_investigations.py),
[approval](../../decisionops/commerce/cases.py), [execution](../../decisionops/commerce/execution.py),
[API](../../decisionops/commerce/api.py), [UI](../../frontend/src/main.tsx),
[launcher](../../scripts/commerce_staff_demo.py), [launcher tests](../../tests/test_commerce_staff_demo_launcher.py).

## Actual verification and exact commands

The database commands below used this explicit fictional test setting:

```bash
export COMMERCE_TEST_DATABASE_URL='postgresql+psycopg://staff_demo:fictional-staff-demo-only@127.0.0.1:55520/commerce_staff_demo'
```

All new checks are **agent-executed locally**. No GitHub CI was run/published.
No checks below are supervisor executions. Paths relative to staff worktree unless noted.

| Command/check | Actual output | Evidence under runs/staff-assistant/ |
|---|---|---|
| `.venv-decisions/bin/python -B -m unittest discover -s tests -p test_commerce_staff_investigation.py -v` | 13 passed,0 skips | followup/backend.log |
| `python3 -B -S -m unittest discover -s tests -p test_commerce_staff_demo_launcher.py -v` | 4 passed,0 skips | followup/launcher-final.log |
| `.venv-decisions/bin/python -B scripts/commerce_ci_tests.py postgres` | 194 passed,0 skips | followup/required-postgres.log |
| `python3 -B -S scripts/commerce_ci_tests.py dependency-free` | 459 collected;194 passed;265 explicit optional skips;0 failures/errors | followup/dependency-free-final.log |
| Clean-checkout cached `npm run build -- --outDir /output --emptyOutDir` | TypeScript and Vite passed, no install/network | followup/clean-build-corrected.log |
| Cached Playwright staff config, rules mode | 2 passed,0 skips,20.7s | followup/browser-rules-verified.log |
| Same config, mock-decisions mode | 2 passed,0 skips,21.6s | followup/browser-mock-verified.log |

Verified TCP database identity: `commerce_staff_demo`, `staff_demo`, server port 5432,
host endpoint 127.0.0.1:55520. Each backend test creates/drops its own schema. Clean
checkout rules schema `staff_demo_repeat_rules_verified`, mock `staff_demo_repeat_mock`;
all browser records are retained, not reseeded after execution. Migrations through 0008,
seed, checkpoint setup, readiness, start/stop were actually exercised there. Existing
runtime package versions matched uv.lock; clean checkout reused .venv-decisions,
not a fresh dependency installation. `followup/locked-versions.json` records nine
runtime package pins. An offline lock check matched all 27 installed frontend packages;
50 absent optional/platform entries were reported explicitly. Build used cached frontend
dependencies and unchanged package-lock.

The exact browser command for each mode (substitute that existing test mode/schema
and output folder, NEVER run against Richard's public demo) was:

```bash
sg docker -c 'docker run --rm --pull never --network host -e COMMERCE_WEB_URL=http://127.0.0.1:55523 -e COMMERCE_STAFF_TEST_MODE=rules -e COMMERCE_STAFF_USERNAME=operator -e COMMERCE_STAFF_PASSWORD=fictional-staff-demo-password -v /home/richard/projects/decisionops/runs/worktrees/staff-repeatability/frontend/staff-tests:/workspace/staff-tests:ro -v /home/richard/projects/decisionops/runs/worktrees/staff-repeatability/frontend/playwright.staff.config.ts:/workspace/playwright.staff.config.ts:ro -v /home/richard/projects/decisionops/runs/worktrees/staff-repeatability/runs/staff-assistant/browser-rules-verified:/workspace/artifacts --entrypoint sh decisionops-commerce-browser:local -c "npx --no-install playwright test --config playwright.staff.config.ts"'
```

Mock run changed `COMMERCE_STAFF_TEST_MODE=mock-decisions` and output to
`browser-mock-verified`; start command used `--mode mock-decisions --schema
staff_demo_repeat_mock --port 55523`. Rules startup used
`--schema staff_demo_repeat_rules_verified`. Full launch commands are in the staff guide.

Reused, not rerun here: the 3916e5d legacy browser6 passes, legacy API8 passes and
Decisions SDK/database28 passes. Their tested backend/SDK and legacy flow are
unchanged; the UI fix is confined to the new continuation explanation. Logs remain
`browser-legacy.log`, `legacy-api-final.log`, `decisions-regressions-corrected.log`.
Historical viewer was not rerun in this staff follow-up. Current CI is unexecuted.
Dependency-free optional skips include PostgreSQL/API/model-required tests; actual
required DB and staff browser execution are separately evidenced above.

## Failures, corrections and limits

- First rules browser:1 passed/1 failed because an empty continuation panel was
  rendered even with zero continuation steps. Corrected the UI condition, kept the
  assertion, then 2 passed on a fresh schema. Retained `browser-rules-red.log`, failure
  screenshot and `rules-failed-durable.json`.
- First mock startup failed before DB work: port preflight mistook TIME_WAIT for a
  live owner. Subsequent browser attempt could not connect (2 failed); no investigation
  ran in that schema. Matched normal socket-reuse semantics without permitting an
  active listener. Focused RED/GREEN and successful same-port startup retained.
- Offline launcher regression first failed for missing port interface. All red logs
  remain. Test/environment setup failures are not model failures.
- Temporary checkout deletion encountered root-owned generated browser assets after
  ordinary Git removal. All 28 artifact copies were hash-verified first; a network-
  disabled helper fixed ownership only there, then removed the unregistered remainder.
  No forced worktree removal or unrelated cleanup occurred.

Browser tests open cases through the real HTTP API and then test the report UI;
they do not independently cover the full new flow starting with the browser's
Start review control. The unchanged older browser suite covers case creation.
Different-ID and stale-approval rejection are backend HTTP tests, not simultaneous
two-browser-user demonstrations. Browser refresh is exercised during normal work,
not a killed-worker/restarted-browser chaos test; required database recovery tests
cover other boundaries. No production authentication, external-shop connector,
fresh-host installation or live-model continuation verification was performed.

Prior live Responses nano and Decisions traces stay unchanged in the evidence archive.
Both ended in review; the Decisions model left inventory unread. This milestone's
rules/mock completion does not retroactively change either live result. No model
performance or Stage5/deployment-complete claim. Read-only pilot gaps are enumerated
in PILOT-HANDOFF.md; the smallest next milestone is an authorized read-only connector
and evidence mapping with server-side execution disabled, not a deployed assistant.
