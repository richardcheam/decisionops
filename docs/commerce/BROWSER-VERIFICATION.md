# Browser harness gate — agent-executed local verification

Historical preparation record: the current offline release candidate and forced-function
protocol are documented in [PORTFOLIO-RC.md](PORTFOLIO-RC.md). The old v1 live command
below is superseded; its original configuration/evidence remain historical.

Source branch `feat/browser-investigation`; base
`b85a23e620e5e3428e4954da58cf22eb4735ebed`. Initial corpus freeze is
`d50e22bfefeb16a134678364f851c8a8ef0c98cc`. The final review commit contains this
record; `evaluation/FROZEN.json` identifies exact implementation/build/input bytes.
No commands in this milestone are attributed to Richard or to a supervisor.

All commands below ran in `/home/richard/projects/decisionops/runs/worktrees/browser-investigation`.
Existing Docker group access used `sg docker -c` when needed. No dependencies were
installed, no credentials were read by verification, and no API/model calls occurred.
Only the new `decisionops-browser-fixtures` containers/network were started/recreated/
stopped. No database was connected, migrated or seeded; no preserved app was operated.

| Actual command | Result | Saved output |
|---|---|---|
| `sg docker -c 'bash scripts/browser_fixture.sh build'` | frontend TypeScript + Vite build and standalone harness TypeScript compile passed, cached images/network-free | `formatted-build.log`, `final-gate-browser.log` build section |
| `sg docker -c 'bash scripts/browser_fixture.sh test runs/browser-investigation/final-gate'` | 15 passed, 0 failed, 0 skipped, 18.3s | `final-gate-browser.log`, `final-gate/browser-report.json` |
| `python3 scripts/grade_browser_evaluation.py runs/browser-investigation/final-gate` | 6/6 scripted cases accepted on evidence/outcome/safety axes; no transfer score | `final-gate-grades.json` |
| `python3 -B -m unittest discover -s tests -p test_browser_evaluation.py -v` | 10 passed, 0 skipped | `final-admission-tests.log` |
| `python3 -B -m unittest discover -s tests -p test_browser_grading.py -v` | 3 passed, 0 skipped | `final-gate-grader.log` |
| `../stage5-correction/.venv-decisions/bin/python -B -m unittest discover -s tests -p test_browser_evaluation_sdk.py -v` | 3 passed, 0 skipped, actual locked SDK with fake HTTP only | `final-sdk.log` |
| `sg docker -c 'BROWSER_FIXTURE_TESTS=1 <historical-checkout>/.venv-decisions/bin/python -W error::ResourceWarning -B -m unittest discover -s tests -p test_browser_bridge.py -v'` | 1 passed, 0 skipped; 3 simulated choices; owned container removed/client reaped/pipes closed | `final-bridge-after-review.log`, `bridge-smoke.json` |
| `sg docker -c 'bash scripts/browser_fixture.sh stop && bash scripts/browser_fixture.sh start'` | isolated services/network stopped and recreated; both ready with source/record identities | `stop-start-readiness.log` |
| `python3 scripts/browser_evaluation.py --describe` | frozen source/build hashes valid, config hash printed; no credential/SDK/client access | `proposed-api-configuration.json` |
| `python3 -c 'from scripts.browser_evaluation import validate_frozen,verify_serving_identity; validate_frozen(); verify_serving_identity()'` | 44 frozen files match, both running fixture identities and served assets match | packaging verification, also checked during archive creation |

Paths in the last column are under `runs/browser-investigation` (local generated
evidence, ignored by Git). Source and tests are committed; review archive includes
the relevant outputs/screenshots/audits and their SHA-256 index.

## Boundary evidence and negative results

`frontend/browser-tests/boundaries.spec.ts` checks pre-send denial of staff/API/body
reads, encoded/credentialed URLs, POST and subframes; same-document stale refs;
fabricated/truncated citations; one counted known-read retry; distinct operational
versus missing-evidence stops; deadline/action/network caps; read-only protection
even when page instructions ask to approve; actual slow-drip absolute timeout and
socket closure. `harness.spec.ts` runs the six fixture-specific scripted paths,
wrong-order rejection and redirect-target denial. `fixtures.spec.ts` checks the tab/
disclosure UX and screenshots. These scripts are excluded from policy imports/context.

The API tests verify exact decimal reservations/caps, no ledger replenishment,
full-request byte bound, metadata exclusion, malformed/refused/wrong-model/incomplete
responses, unknown usage, timeout uncertainty/no retry, late unapplied results,
validated action application, stale executable hashes and served identity mismatch.
SDK tests use a mock transport for serialization, timeout/500 retry denial and
streamed output overflow. No real account availability is established.

Retained initial failures include wrong test mounts/collection paths, a real
intercepted-fetch/render race, strict handle typing, an over-restrictive parcel/item
same-block check (corrected to an explicit saved relationship), and open pipe warnings
(corrected; final smoke used ResourceWarning as error). The independent source review
identified three Important issues: absolute HTTP lifetime, stale build admission and
serialization-sensitive missing-evidence grading. All have focused corrections and
regressions. No external supervisor or CI execution is implied by that source review.

## Not executed / limits

No CI jobs, PostgreSQL/staff-browser regression suites, live browser model evaluation,
model loading or telemetry export ran. Commerce implementation, dependency locks,
frozen first Shop component/styles and release worktrees were preserved byte-for-byte.
The new harness is isolated and has no business-record writes. Broad unchanged
Commerce suites were not repeated for a fixture-only change. The proposed graph,
PostgreSQL browser-run authority and Langfuse outbox remain design only.

The existing SDK environment and cached browser image are local prerequisites. A fresh
host image download/build was not executed. The proposed single-use manual evaluation
has not demonstrated autonomous navigation or compatibility with an actual account;
all model-free successes use explicitly scripted test choices. It must preserve any
future early review/failure, not manufacture evidence or replace it with rules.
