# Optional Decisions API investigation

Wrapup: [current handoff](HANDOFF.md) and [archive index](../../reports/commerce-evidence/INDEX.md)
supersede temporary file locations below. Historical runs/... references now live
under the indexed archived worktree root. Richard executed the first Decisions
operator run; its actual result is in [the live walkthrough](DECISIONS-LIVE-WALKTHROUGH.md).
No second investigation is authorized.

This is the current proposed API selection route. It uses the official Python SDK
3.26.0 and **POST https://api.openai.com/v1/decisions**, not Responses structured
output. Rules remain the browser/API/ordinary-worker default. No live Decisions
requests, access probes, credential checks or model loads were performed during
implementation. A new explicit **RUN LIVE TEST** is required for one investigation;
it grants no standing permission for subsequent runs. Configuration/key presence,
startup, background jobs and CI never grant paid-call authorization.

The Responses implementation and `commerce-responses/v1` deserialization/pricing
remain available for historical compatibility. Richard's completed nano trace and its
negative early-review result are preserved; see [the walkthrough](API-LIVE-WALKTHROUGH.md).
A pre-change source snapshot is in runs/decisions-verification/pre-decisions-source.zip.
No stopped pilot, frozen evaluation, original application or volume was changed.

## Contract and insertion point

`api_investigation.py` explicitly chooses an adapter by the recorded API version.
`DecisionsAdapter` inherits only the bounded SDK transport/deadline/cancellation
mechanism from `OpenAIAdapter`; it sends one choice question via
`client.decisions.with_raw_response.create`. This is SDK-mediated HTTP, with strict
local parsing of the returned bounded JSON. It does not call responses.create.
No inference occurs inside a business transaction or while holding case locks.

`commerce-decisions/v1` has a distinct configuration, pricing record and wire schema.
The immutable recommendation binds case/run, generation/revision, context, source
observations, deadlines and configuration; audit metadata is not a model feature.
The existing duration ledger and API monetary companion are reserved atomically.
Legacy routing validators and proposal/execution services remain unchanged.

The request contains only `model`, `input` and one `questions` entry:

- type choice, name `investigation_action`, fixed application instructions;
- allowed actions mapped in immutable request order to c000, c001, etc.;
- each value's description is its normalized action, not a case ID or opaque hash;
- input is exactly the bounded PolicyRequest.features(): report, selected observation
  summaries, attempted tools, remaining budgets and rejection feedback.

A value is stable within that persisted request. c000 need not mean the same action
in a later context: always inspect that request's allowed actions/choice mapping.
No unrequested business records, evaluator labels or complete eligibility are sent.
No Responses parameters (`max_output_tokens`, reasoning, store, service_tier,
structured-output text format), tools, conversations, images or background mode are
sent. The requested model is gpt-6-luna: current official documentation admits only
that model for Decisions. Its alias is explicitly bound; an unexpected response
model is rejected rather than silently accepted or substituted.

Admission validates one answer, exact question name, type, exact model, a string value
in the current choices, finite confidence/probabilities in [0,1], a complete unique
probability distribution summing to one (absolute tolerance 1e-5), and measured input
usage. Confidence/probabilities are uncalibrated model estimates in audit metadata;
they never count as evidence, permission, approval or execution authorization.
The returned action still passes the existing deterministic allowed-action, fencing,
context/freshness, explicit-read and final proposal safety gates. One forced allowed
action skips the SDK and records zero measured input usage.

## Resources and exact pricing

Proposed immutable configuration: [api-decisions-proposed.json](examples/api-decisions-proposed.json).
Canonical configuration SHA-256:
`b318cc81100b474bf1cad6815bd9ed8f39a064db9f1cdf55debff8eb2a54da09`.

| Resource | Bound |
|---|---|
| Endpoint/model | global /v1/decisions, gpt-6-luna |
| Pricing version | openai-decisions-standard-20261016 |
| Standard input rate | $0.10 per million tokens |
| Output/cache-read/cache-write charge | none under documented Decisions pricing |
| Complete JSON body cap | 20,480 UTF-8 bytes, including instructions/questions/choices/model/framing |
| Protocol/tokenization allowance | 4,096 tokens |
| Reserved maximum input | 24,576 tokens per request |
| Per-request reservation | $0.00245760 |
| Maximum request reservations | 12; $0.02949120 total |
| Immutable money cap | $0.03 |
| Decision/run limits | 20 seconds / 240 seconds; 16 decisions, 12 reads, at most two attempts per tool |
| Response body | continuously capped at 65,536 bytes |

There is no supported output-token-limit parameter for this endpoint. No output price
is copied from Responses. The input estimate is a conservative complete-wire-byte
upper bound plus explicit protocol allowance, **not measured usage or an API-enforced
token limit**. Oversized wire requests fail before reservation/dispatch; known native
usage exceeding the reserved bound is invalid and is still accounted. The price
assumes standard global processing and short text input. Regional premiums/long-context
multipliers are documented: do not use a regional-billed project under this plan
without revisiting its reservation and explicit authorization. Account availability
and actual invoice costs remain unverified; no access probe is included.

Settlement uses exact Decimal input pricing and records native usage separately.
Input tokens must be nonnegative integers, native output_tokens must be zero and
native total_tokens must equal input_tokens. Unknown/inconsistent usage never becomes
invented zero cost. The companion ledger records the input-only cost estimate; old
Responses rows retain their original input/output rates and cost formula. Historical
reserved_cost_usd is retained after settlement; do not add it again to actual cost.

## Failure and recovery

SDK and HTTP transport retries are both disabled. Refusal or malformed/wrong-bound
answers with known usage settle that usage but produce explicit review, never a
rules replacement or an executed read. Malformed JSON, timeout, denied access,
rate-limit errors, missing/inconsistent usage, cancellation or response overflow
retain an uncertain possibly-dispatched reservation. The run stops/reviews where
ownership permits; lease/run loss can require explicit recovery instead of immediate
terminal publication. Safe review is a negative proposal-completion result.

Restart does not redispatch an uncertain decision. Historical calls and budgets
remain authoritative. Inspect first; do not replace a budget, change models, increase
caps, erase a single-use marker or run another investigation after a failure. A
read-only interrupted tool can only retry through existing explicitly counted
recovery, never as an invisible replay. No automatic live resume is authorized.

## Local operator commands

All commands below are for the separate **commerce_decisions_test** environment on
127.0.0.1:55446, user commerce_decisions. The CLI verifies both connection settings
and server identity. The original migration-0004 application on 55432 is prohibited.
No new migration is introduced. Only the optional SDK changed from 2.26.0 to 3.26.0;
all other locked versions stayed unchanged. Existing .venv-api was preserved.

```bash
cd <historical-checkout>
UV_PROJECT_ENVIRONMENT=.venv-decisions uv sync --locked --only-group commerce --only-group commerce-api --no-python-downloads
export COMMERCE_DATABASE_URL='postgresql+psycopg://commerce_decisions:decisions-fictional-only@127.0.0.1:55446/commerce_decisions_test'
```

The agent actually used the following disposable container and verified
current_database/current_user/inet_server_port before subsequent checks. Every
integration test owns, migrates, seeds and drops its own schema. No business demo
or investigation was run on the original runtime.

```bash
sg docker -c 'docker run -d --pull never --name decisionops-decisions-tests --memory 512m --cpus 2 -e POSTGRES_DB=commerce_decisions_test -e POSTGRES_USER=commerce_decisions -e POSTGRES_PASSWORD=decisions-fictional-only -p 127.0.0.1:55446:5432 --tmpfs /var/lib/postgresql/data:rw,size=512m postgres@sha256:0ea6700a3b4f0ae6ce746519073558aed4d88a79d8d07622a9a644946c7319c4 -c shared_buffers=32MB -c max_wal_size=64MB -c min_wal_size=32MB'
sg docker -c 'docker exec decisionops-decisions-tests pg_isready -U commerce_decisions -d commerce_decisions_test'
```

Readiness expects accepting connections. For a future explicit operator demo only,
apply migrations, seed and open a case using existing services. These public-schema
setup forms were not executed in this milestone; tests migrated/seeded isolated schemas:

```bash
.venv-decisions/bin/alembic upgrade head
.venv-decisions/bin/python -B -m decisionops.commerce.seed
.venv-decisions/bin/python - <<'PY'
from decisionops.commerce.database import database_engine
from decisionops.commerce.cases import open_case
from decisionops.commerce.read_tools import AssessmentRequest
engine=database_engine()
with engine.connect().execution_options(isolation_level='READ COMMITTED') as c,c.begin():
    case=open_case(c,AssessmentRequest('ORD-1042','SHIP-1042',{'shirt-blue-M':1}))
    print(case['id'])
engine.dispose()
PY
```

To exercise SDK/CLI integration without spending, create a distinct **mock** config
from DecisionsConfig (execution='mock', separate mock budget ID) and use start. The
actual CLI start/inspect integration tests exercised this route; simulated usage is
clearly marked simulation=true. Never relabel those results as native inference.

The CLI supports `start --case CASE_ID --report REPORT --config FILE --output NEW_DIR`
and `inspect --run RUN_ID`. Live start additionally requires the exact approved
configuration hash and external OPENAI_API_KEY. No credential may be put in a file,
CLI argument, trace or report. No live command is authorized now: wait for Richard's
new **RUN LIVE TEST** for this configuration. An old nano approval hash fails.

Inspect decisions.request.features and its allowed actions, result metadata for the
selected value/native confidence/usage, run observations for validated returned
facts, and monetary_reservations for dispatch_count/state/cost. If CLI fails before
saving a trace, preserve the database and export its durable records before removing
it. Cleanup of test-only container (agent executes only after verification):

```bash
sg docker -c 'docker rm -f decisionops-decisions-tests'
```

That discards only this tmpfs database; it does not touch original volumes. To undo
the optional route, use rules; no application default or runtime migration changed.
The historical adapter still dispatches only its recorded Responses version. Do not
upgrade or restart the original runtime to try this optional operator functionality.

## Verification and attribution

Commands and complete logs are in runs/decisions-verification. The new SDK tests use
the actual SDK with httpx.MockTransport, not a mock SDK. Database tests exercise
known/uncertain usage, pre-dispatch zero work, monetary/count races, restart, stale
results, staff changes during inference and after persistence, no default-worker
adapter, refusal, complete mock proposal safety, and actual operator start/inspect.
They also run the existing Responses accounting protections on the new endpoint.

Agent-executed verification is distinct from Richard's historical live nano run.
CI/browser and real Decisions compatibility remain unexecuted. No performance or
business-value claim is inferred from these mocked integration results.

Official documentation inspected 2026-10-16:
- https://developers.openai.com/api/docs/guides/decisions
- https://developers.openai.com/api/reference/python/resources/decisions/methods/create

The installed SDK's Decisions request/response definitions were also inspected;
only fields supported by that SDK version are sent. No checkpoint/model packages
were imported or installed by the optional profile.


### Single-use manual wrapper

The manual kit is now tracked at scripts/commerce_decisions_operator/. Its
predecessor at runs/decisions-verification/operator/ is archived, unchanged. Richard
executed that predecessor once; retained original guard directories remain consumed.
Its README separates preparation, paid dispatch and evidence-preserving cleanup.
It uses an atomic live-attempt-started directory to prevent accidental repeat; a
configuration approval hash by itself is reusable and is not a single-use permit.
No wrapper invocation is authorized until Richard's next RUN LIVE TEST. Do not
remove a marker or recreate an exhausted/uncertain budget to obtain another run.


### Actual local results for this source

| Check | Result | Full log in runs/decisions-verification/ |
|---|---|---|
| Decisions SDK/mock HTTP | 10 passed, zero skips | sdk-final.log |
| Decisions PostgreSQL/accounting/CLI | 18 passed, zero skips | postgres-final.log |
| Historical Responses SDK under 3.26.0 | 11 passed, zero skips | responses-sdk-compatibility.log |
| Historical Responses accounting | 9 passed, zero skips | responses-postgres-compatibility.log |
| Required PostgreSQL profile | 194 passed, zero skips | required-postgres.log |
| Dependency-free (-S) | 190 passed, 252 explicit optional skips, collected 442 | dependency-free.log |

Initial red outputs are preserved in sdk-red.log (missing implementation) and
postgres-red.log (operator factory not yet implemented); final outputs above are
green. No failed reproduction was erased. The tests and source-only review are
agent-attributed. Richard performed no new verification commands in this slice.
Fresh source review found no blocking defect; its caution that a config hash is
reusable is addressed by the separate single-use operator wrapper and documentation.
The reviewer ran no tests, HTTP or database operations.

Exact executed commands, from the worktree:

```bash
.venv-decisions/bin/python -B -m unittest discover -s tests -p test_commerce_decisions_sdk.py -v
COMMERCE_TEST_DATABASE_URL='postgresql+psycopg://commerce_decisions:decisions-fictional-only@127.0.0.1:55446/commerce_decisions_test' .venv-decisions/bin/python -B -m unittest discover -s tests -p test_commerce_decisions_postgres.py -v
.venv-decisions/bin/python -B -m unittest discover -s tests -p test_commerce_api_decisions.py -v
COMMERCE_TEST_DATABASE_URL='postgresql+psycopg://commerce_decisions:decisions-fictional-only@127.0.0.1:55446/commerce_decisions_test' .venv-decisions/bin/python -B -m unittest discover -s tests -p test_commerce_api_accounting.py -v
COMMERCE_TEST_DATABASE_URL='postgresql+psycopg://commerce_decisions:decisions-fictional-only@127.0.0.1:55446/commerce_decisions_test' .venv-decisions/bin/python -B scripts/commerce_ci_tests.py postgres
python3 -B -S scripts/commerce_ci_tests.py dependency-free
```

The test-only decisionops-decisions-tests container was removed after verification.
No durable demo run is claimed: integration test schemas were dropped by their test
cleanup. CI/browser and live Decisions results remain **unexecuted**, not inferred
passes. Routine CI definitions now explicitly run the new mocked SDK/database
modules, but no code/artifact was pushed and no CI run was triggered here.
