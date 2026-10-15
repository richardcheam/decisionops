# Commerce local reproduction

## Eligibility function

No dependencies or model calls are needed. Run from the isolated worktree:

```bash
cd /path/to/decisionops
python3 -B -S -m unittest discover -s tests -p test_commerce_eligibility.py -v
python3 -B -S -m unittest discover -s tests
```

Demonstrate all-true, unknown loss, mixed blocker/unknown, and malformed input:

```bash
python3 -B -S - <<'PY'
from decisionops.commerce.eligibility import REQUIREMENTS, evaluate_eligibility

facts = dict.fromkeys(REQUIREMENTS, True)
print("all true:", evaluate_eligibility(facts))
facts["loss_confirmed"] = None
print("unknown loss:", evaluate_eligibility(facts))
facts["stock_available"] = False
print("blocker plus unknown:", evaluate_eligibility(facts))
facts["loss_confirmed"] = "false"
try:
    evaluate_eligibility(facts)
except ValueError as error:
    print("rejected malformed input:", error)
else:
    raise AssertionError("malformed input was accepted")
PY
```

Expected statuses: eligible_to_propose, needs_review, ineligible. The mixed
result retains stock_available in blockers and loss_confirmed in unknowns.
Malformed input raises ValueError naming loss_confirmed, even with a known
stock blocker. These examples do not approve, create, or reserve anything.

## Evidence intake: component map

- `data/commerce/eligible.json`: fictional read-tool attestations and trusted
  source/freshness configuration. Not actual order or inventory persistence.
- `decisionops/commerce/demo.py`: validates the fixture envelope, selects the
  clock, invokes assessment and optionally saves a new JSON artifact.
- `decisionops/commerce/evidence.py`: validates provenance, timestamps and
  records; establishes True/False/None facts or records why evidence is unresolved.
- `decisionops/commerce/eligibility.py`: unchanged collect-then-decide function.
- `tests/test_commerce_evidence.py` and `tests/test_commerce_demo.py`: guard
  missing/contradictory/stale records, unsupported cases, malformed input and
  safe artifact publication. Existing eligibility tests remain intact.

Source allowlists and scope are trusted demo configuration. Real adapters will
derive them server-side from store records. Do not feed model/customer claims
into this boundary as authoritative attestations.

## Start and inspect the local demo

This is a one-shot command, so there is no server, port, database or worker to
start. Every run terminates after assessment. No installs or paid inference.

```bash
cd /path/to/decisionops
mkdir -p runs
demo_dir=$(mktemp -d runs/commerce-walkthrough.XXXXXX)
python3 -B -S -m decisionops.commerce.demo data/commerce/eligible.json \
  --as-of 2026-10-12T12:00:00Z --output "$demo_dir/eligible-assessment.json"
```

Expected: exit 0, `eligible_to_propose`, no blockers/unknowns. Inspect:

```bash
python3 -B -S - "$demo_dir/eligible-assessment.json" <<'PY'
import json, sys
from pathlib import Path
result = json.loads(Path(sys.argv[1]).read_text())
print(result["decision"])
print(result["evidence"]["loss_confirmed"])
print("input hash:", result["fixture_sha256"])
PY
```

The carrier record identifies demo-carrier, source version v1, order ORD-1042,
observed_at 2026-10-12T11:00:00Z, accepted true. `--as-of` freezes the clock for
this historical fixture. Omitting it uses current UTC; the fixture eventually
becomes stale by design. It is not an option for production approval overrides.

## Failure walkthrough: stale carrier evidence

Make a new local fixture, leaving the committed baseline intact:

```bash
python3 -B -S - "$demo_dir" <<'PY'
import json, sys
from pathlib import Path
fixture = json.loads(Path("data/commerce/eligible.json").read_text())
carrier = next(r for r in fixture["observations"] if r["requirement"] == "loss_confirmed")
carrier["observed_at"] = "2026-10-09T11:00:00Z"
(Path(sys.argv[1]) / "stale.json").write_text(json.dumps(fixture, indent=2) + "\n")
PY
python3 -B -S -m decisionops.commerce.demo "$demo_dir/stale.json" \
  --as-of 2026-10-12T12:00:00Z --output "$demo_dir/stale-assessment.json"
python3 -B -S - "$demo_dir/stale-assessment.json" <<'PY'
import json, sys
from pathlib import Path
result = json.loads(Path(sys.argv[1]).read_text())
print(result["decision"])
print(result["issues"]["loss_confirmed"])
print(result["evidence"]["loss_confirmed"])
PY
```

Expected: `needs_review`, unknown loss_confirmed, issue `stale`. The carrier
record retains its timestamp/version but has accepted false and reasons stale.
It is older than configured max_age_seconds=86400. Exit 0 means assessment
completed; it does not mean eligibility passed. No exception is needed for
an unresolved business case.

## Smallest appropriate fix, verification and undo

Operational fix: retrieve a current authoritative carrier result. Do not
manufacture timestamps, infer loss, or widen freshness just to clear a case.
For this fictional demo only, simulate a refreshed result in a separate copy:

```bash
python3 -B -S - "$demo_dir" <<'PY'
import json, sys
from pathlib import Path
directory = Path(sys.argv[1])
fixture = json.loads((directory / "stale.json").read_text())
carrier = next(r for r in fixture["observations"] if r["requirement"] == "loss_confirmed")
carrier["observed_at"] = "2026-10-12T11:30:00Z"
carrier["source_version"] = "v2"
(directory / "refreshed.json").write_text(json.dumps(fixture, indent=2) + "\n")
PY
python3 -B -S -m decisionops.commerce.demo "$demo_dir/refreshed.json" \
  --as-of 2026-10-12T12:00:00Z --output "$demo_dir/refreshed-assessment.json"
python3 -B -S -m unittest discover -s tests -p 'test_commerce*.py' -v
python3 -B -S -m unittest discover -s tests
```

Expected refreshed result: eligible_to_propose with accepted carrier v2 and
no carrier issues. Eligibility permits proposing only; staff approval and
transactional execution are not implemented yet.

Safe undo: reuse the untouched stale copy; keep previous artifacts as evidence.

```bash
python3 -B -S -m decisionops.commerce.demo "$demo_dir/stale.json" \
  --as-of 2026-10-12T12:00:00Z --output "$demo_dir/undo-assessment.json"
```

Expected: needs_review again. The walkthrough has changed no application code,
tracked fixture, database, or services. Output artifacts refuse overwrite; use
a fresh output filename or a fresh walkthrough directory for another run.

## Errors, settings and shutdown

Malformed input (for example a string "true" in a boolean field), unsupported
schema versions, missing input files, and existing output paths exit 2 and
emit a JSON `input_error` event on stderr. Failed input validation creates no
assessment artifact. Inspect the named field/path before retrying. Convert
values in the responsible read adapter; never use bool("false"), which is true.

`max_age_seconds` is configurable in a local fixture copy and must be positive
and finite. Keep a copy before a setting change, use a new assessment artifact
to compare results, and restore the original copy to undo. Source authority and
real freshness thresholds require store-specific review before live adapters.

Shutdown: normal command completion leaves no background process. Ctrl-C can
interrupt an in-progress command; any partially written artifact from an
interruption is diagnostic output only, not business state. Retain it and rerun
with a new output path. No Compose services or cloud resources need teardown.

Participation is optional: inspect a saved artifact or reproduce the stale
case when useful. These are operating references, not prerequisites for development.

## PostgreSQL records to assessment

`schema.py` declares order/line, payment, shipment/line, inventory, resolution,
policy-version and seed-marker tables. `migrations/versions/0001_business_records.py`
is a frozen initial schema; Alembic applies it and records revision 0001.
`seed.py` inserts the known fictional scenarios transactionally once.
`read_tools.py` queries actual records and produces typed `ReadToolResult`
objects. Their record digests, bindings, quantities and diagnostic details pass
through the existing evidence checks and eligibility function.
`store_demo.py` is the new read-only database CLI; `demo.py` remains fixture mode.

Database mode has no clock-override flag. Source observation time is the
database read time, while carrier event time is independently checked against
the order's policy. Seed timestamps use the first database seed time and remain
unchanged on repeat seed commands. If the demo is left for more than 24 hours,
confirmed-loss records become stale rather than silently refreshing themselves.

### Install the commerce-only environment

```bash
cd /path/to/decisionops
uv sync --locked --only-group commerce --no-python-downloads
uv lock --check
```

Expected: SQLAlchemy, Alembic and psycopg plus their required dependencies.
Existing ML requirements remain unchanged in the lock. Do not use a bare
`uv sync` for this walkthrough: it selects historical ML dependencies.
Commands below use the already synced `.venv` directly and do not contact models.

### Docker prerequisite and database startup

If Docker/Compose are absent, Ubuntu installation requires your administrator
session. This is a real environment prerequisite, not a learning exercise:

```bash
sudo apt-get update
sudo apt-get install docker.io docker-compose-v2
sudo systemctl enable --now docker
```

Use `sudo docker compose` for the commands below if your current session lacks
Docker socket access; don't change socket permissions. If you choose Docker
group access, adding your account to that group and opening a new login session
enables it. Engine access grants administrative control over the machine.

If docker info succeeds but docker compose reports unknown command, check the
plugin package rather than restarting the engine:

```bash
dpkg-query -W docker-compose-v2
sudo apt-get install docker-compose-v2
docker compose version
```

In the observed setup, this package was absent while docker.io was installed.
Installing the CLI plugin needs no daemon reload or Docker restart. If package
installation reports conflicts, inspect that output before retrying or removing
packages.

```bash
docker compose version
docker compose config --quiet
docker compose up -d --wait postgres
docker compose ps
docker compose exec -T postgres pg_isready -U commerce -d commerce
docker compose logs --tail=30 postgres
```

Expected: healthy postgres, readiness reports accepting connections, and logs
show database ready. Compose pins the official PostgreSQL 16.15 image by digest,
binds host port 55432 on loopback only, and uses a named persistent volume.
The hardcoded credential is for this fictional local demo only.

### Migrate, seed and inspect

```bash
export COMMERCE_DATABASE_URL='postgresql+psycopg://commerce:local-demo-only@127.0.0.1:55432/commerce'
.venv/bin/alembic upgrade head
.venv/bin/alembic current
.venv/bin/python -B -m decisionops.commerce.seed
.venv/bin/python -B -m decisionops.commerce.seed
docker compose exec -T postgres psql -U commerce -d commerce -c '\dt'
docker compose exec -T postgres psql -U commerce -d commerce -c "SELECT o.id,o.policy_id,l.variant_id,l.quantity,p.status,p.amount_minor,o.resolution_history_complete FROM orders o JOIN order_lines l ON l.order_id=o.id LEFT JOIN payments p ON p.order_id=o.id ORDER BY o.id;"
docker compose exec -T postgres psql -U commerce -d commerce -c "SELECT s.id,s.order_id,s.carrier_status,s.carrier_observed_at,l.variant_id,l.quantity FROM shipments s JOIN shipment_lines l ON l.shipment_id=s.id AND l.order_id=s.order_id ORDER BY s.id;"
docker compose exec -T postgres psql -U commerce -d commerce -c "SELECT store_id,variant_id,on_hand,reserved,on_hand-reserved AS available FROM inventory ORDER BY variant_id;"
docker compose exec -T postgres psql -U commerce -d commerce -c "SELECT * FROM resolutions ORDER BY id;"
docker compose exec -T postgres psql -U commerce -d commerce -c "SELECT * FROM policy_versions ORDER BY version;"
```

Expected: Alembic revision 0001; first seed reports seeded, repeat reports
already_seeded. Eight orders, two policy versions, two inventory rows and two
resolution rows. Blue shirt has 9 available; red shirt has zero available.
The eligible order pins demo-policy-v1; demo-policy-v2 denies replacement and
does not retroactively change orders pinned to v1.

### Assess and inspect provenance

```bash
mkdir -p runs
db_demo_dir=$(mktemp -d runs/postgres-walkthrough.XXXXXX)
.venv/bin/python -B -m decisionops.commerce.store_demo \
  --order ORD-1042 --shipment SHIP-1042 --item shirt-blue-M:1 \
  --output "$db_demo_dir/eligible.json"
.venv/bin/python -B - "$db_demo_dir/eligible.json" <<'PY'
import json, sys
from pathlib import Path
result = json.loads(Path(sys.argv[1]).read_text())
print(result["decision"])
print(result["request"], result["policy_id"], result["database_status"], result["read_only"])
print(result["evidence"]["loss_confirmed"])
print(result["evidence"]["no_previous_compensation"])
PY
```

Expected: eligible_to_propose, correct order/shipment/variant/quantity binding,
policy-v1, available database and read_only true. Evidence includes actual
carrier status/timestamp and history completeness, plus content digests.
Outputs refuse overwrite. Each new run needs a new artifact path.

Other seeded scenarios use the same CLI with these exact arguments:

| Order | Shipment | Item | Expected result |
| --- | --- | --- | --- |
| ORD-STOCK | SHIP-STOCK | shirt-red-M:1 | ineligible; stock_available blocker |
| ORD-COMP | SHIP-COMP | shirt-blue-M:1 | ineligible; no_previous_compensation blocker |
| ORD-PARTIAL | SHIP-PARTIAL | shirt-blue-M:2 | needs_review; partial_shipment |
| ORD-PARTCOMP | SHIP-PARTCOMP | shirt-blue-M:2 | needs_review; partial_compensation |
| ORD-HISTORY | SHIP-HISTORY | shirt-blue-M:1 | needs_review; compensation history unknown |
| ORD-TRACKING | SHIP-TRACKING | shirt-blue-M:1 | needs_review; in-transit does not confirm loss |
| ORD-POLICY | SHIP-POLICY | shirt-blue-M:1 | ineligible; pinned policy denies replacement |

Example:

```bash
.venv/bin/python -B -m decisionops.commerce.store_demo \
  --order ORD-STOCK --shipment SHIP-STOCK --item shirt-red-M:1
.venv/bin/python -B -m decisionops.commerce.store_demo \
  --order ORD-1042 --shipment SHIP-STOCK --item shirt-blue-M:1
```

The second command demonstrates wrong-order binding: review with
shipment_order_mismatch, and no accepted loss evidence from SHIP-STOCK.
Exit 0 means a completed assessment, including an ineligible/review decision.
Exit 2 means invalid configuration/input/output path. Exit 3 means the
database snapshot was unavailable; it is not a business refusal.

### Database integration tests and independent model-free checks

```bash
export COMMERCE_TEST_DATABASE_URL="$COMMERCE_DATABASE_URL"
.venv/bin/python -B -m unittest discover -s tests -p test_commerce_postgres.py -v
.venv/bin/python -B -m unittest discover -s tests
unset COMMERCE_TEST_DATABASE_URL
python3 -B -S -m unittest discover -s tests
```

Integration creates a random test schema, applies the actual migration, seeds
fixed-clock records and cleans up only that schema. It never resets the public
demo tables. Tests cover wrong binding, stock shortage, prior compensation,
partial scope, incomplete/failed history, source age, schema consistency,
seed idempotence and PostgreSQL rejection of accidental writes.

Without COMMERCE_TEST_DATABASE_URL, integration tests explicitly skip.
The last command requires neither PostgreSQL nor database/ML packages.
Do not set the integration URL while deliberately running Python with -S.

### Failure walkthrough: unavailable database, diagnosis and recovery

Stop only this demo service, preserving data:

```bash
docker compose stop postgres
.venv/bin/python -B -m decisionops.commerce.store_demo \
  --order ORD-1042 --shipment SHIP-1042 --item shirt-blue-M:1 \
  --output "$db_demo_dir/unavailable.json"
```

Expected: exit 3 and stderr database_unavailable. Stdout/saved JSON shows
needs_review with all seven requirements unknown, including compensation;
the application does not mistake a failed query for an empty history.

```bash
docker compose ps -a
docker compose logs --tail=30 postgres
.venv/bin/python -B - "$db_demo_dir/unavailable.json" <<'PY'
import json, sys
from pathlib import Path
result = json.loads(Path(sys.argv[1]).read_text())
print(result["database_status"], result["decision"])
print(result["read_tools"][4])
PY
docker compose up -d --wait postgres
.venv/bin/python -B -m decisionops.commerce.store_demo \
  --order ORD-1042 --shipment SHIP-1042 --item shirt-blue-M:1 \
  --output "$db_demo_dir/recovered.json"
docker compose exec -T postgres psql -U commerce -d commerce -c "SELECT * FROM seed_versions; SELECT * FROM inventory ORDER BY variant_id;"
```

Smallest fix for a stopped container: start it; don't reseed or loosen business
checks. If it is healthy but assessment still reports unavailable, check the
URL/port, credentials and Alembic revision before changing code. Raw URLs and
SQL exception messages are omitted from assessment errors to avoid secret leakage.
Recovery should restore eligibility with unchanged seed marker and stock.
You can undo the recovery by stopping the service again; data remains intact.

### Restarting versus deleting persistent data

```bash
docker compose restart postgres
docker compose exec -T postgres pg_isready -U commerce -d commerce
docker compose stop postgres
```

Restart preserves the named volume, schema and records. Readiness may briefly
fail during restart; wait before assessing. Stop is the normal shutdown command.
`docker compose down` removes this project's containers/network while keeping
the named volume. `docker compose down --volumes` also deletes the persistent
database and is destructive; it is not a repair command and was not executed.
Do not use it without intentionally choosing to discard this demo's data.
Do not use Alembic downgrade-to-base as an outage fix: migration 0001's downgrade
drops the business tables. Data restore/backup exercises remain a later slice.

### Verification status

Compose runtime verification completed on 2026-10-12 after owner Docker setup.
The owner supplied the healthy-container, seed and eligible assessment output.
Agent independently verified revision 0001, idempotent seed, all 120 tests
(118 passed, two optional ML checks skipped), outage/recovery and container
recreation with unchanged business records and migration revision.
The named volume is decisionops-commerce_commerce_pgdata. PostgreSQL was left
healthy and running on loopback port 55432. No volume was deleted.

Artifacts: runs/compose-verification-sy7ham2y. Inspect the failure evidence:

```bash
python3 -B -S - <<'PY'
import json
from pathlib import Path
directory = Path("runs/compose-verification-sy7ham2y")
for name in ("unavailable", "recovered", "recreated"):
    result = json.loads((directory / (name + ".json")).read_text())
    print(name, result["database_status"], result["decision"])
print("persisted records unchanged:",
      (directory / "records-before.json").read_bytes() ==
      (directory / "records-after.json").read_bytes())
PY
```

Expected: unavailable/review, available/eligible, available/eligible and records
unchanged True. shutdown.log and recovery.log identify the PostgreSQL lifecycle;
unavailable.stderr.log contains the database_unavailable event.

The agent's existing shell retained older supplementary groups. It used
`sg docker -c 'docker compose ps'` (and corresponding scoped Compose commands)
to activate the already granted group. This is unnecessary in an owner shell
where Docker commands already work.

### Verified native fallback in this checkout

The unpacked runtime and initialized data directory already exist in this
checkout from initial agent verification before Docker was available. Compose
is now the normal demo environment; this retained fallback is not another
deployment target. It uses trust
authentication on loopback for fictional data and must not be exposed publicly.
Startup after agent shutdown:

```bash
native_pg_dir="$PWD/runs/pg-runtime"
"$native_pg_dir/root/usr/lib/postgresql/16/bin/pg_ctl" \
  -D "$native_pg_dir/data" -l "$native_pg_dir/postgres.log" \
  -o '-p 55433 -h 127.0.0.1 -k /tmp' start
export COMMERCE_DATABASE_URL='postgresql+psycopg://commerce@127.0.0.1:55433/commerce'
.venv/bin/python -B - <<'PY'
from decisionops.commerce.database import database_engine
engine = database_engine()
with engine.connect() as connection:
    print("ready:", connection.exec_driver_sql("SELECT 1").scalar_one())
    print(connection.exec_driver_sql("SELECT version()").scalar_one())
    print("migration:", connection.exec_driver_sql("SELECT * FROM alembic_version").all())
    print("stock:", connection.exec_driver_sql("SELECT * FROM inventory ORDER BY variant_id").all())
engine.dispose()
PY
.venv/bin/alembic current
.venv/bin/python -B -m decisionops.commerce.store_demo \
  --order ORD-1042 --shipment SHIP-1042 --item shirt-blue-M:1
```

Expected readiness 1, PostgreSQL 16.15, revision 0001 and preserved stock.
The database is already migrated and seeded; no setup writes are necessary.
Assessment is eligible while the original seeded carrier snapshot remains
within its 24-hour policy freshness window, otherwise it honestly needs review.

For outage reproduction, substitute this stop command for docker compose stop:

```bash
"$native_pg_dir/root/usr/lib/postgresql/16/bin/pg_ctl" -D "$native_pg_dir/data" stop -m fast
tail -n 30 "$native_pg_dir/postgres.log"
```

Assessment now exits 3 with unavailable evidence. Repeat the startup command to
recover. Stop is also the final shutdown command; it preserves the native data
directory. Do not delete that directory as a recovery step. This fallback uses
port 55433; Compose uses 55432, so update the URL when switching environments.

## Durable investigations and proposals (2026-10-13)

### What runs and which files matter

PostgreSQL is the only long-running service in this slice. Each Python CLI starts,
reads/writes its bounded transaction, prints JSON and exits; there is no API,
worker, LangGraph process or frontend yet.

- commerce/store_demo.py remains the original read-only assessment command.
- commerce/read_tools.py and evidence.py derive/check the seven facts unchanged.
- commerce/proposals.py builds immutable proposal contents and compares them
  with current records. It uses only the Python standard library.
- commerce/investigations.py stores original assessment snapshots and proposals.
- commerce/case_demo.py exposes investigate, inspect and check commands.
- schema.py and migration 0002 add commerce_investigations/commerce_proposals.
  PostgreSQL triggers reject UPDATE/DELETE on these audit tables.
- scripts/commerce_proposal_walkthrough.py runs success, stock drift and undo in
  an isolated schema, then removes only that generated schema.

Investigation writes audit records, never order, inventory or compensation records.
Only eligible supported assessments produce a proposal. The proposal binds exact
order/shipment/items, applicable policy and all seven evidence content versions.
A check rereads current records in a read-only snapshot. Matching contents AND
current eligibility yield valid_for_review. That is not approval or permission
to execute. The snapshot can become outdated as soon as its transaction ends.

### Startup, migration and ordinary use

Run from the commerce worktree. Existing commerce dependencies suffice; no install
or model download is needed if you followed the previous slice's setup.

```bash
cd /path/to/decisionops
export COMMERCE_DATABASE_URL='postgresql+psycopg://commerce:local-demo-only@127.0.0.1:55432/commerce'
docker compose up -d --wait postgres
docker compose exec -T postgres pg_isready -U commerce -d commerce
.venv/bin/alembic upgrade head
.venv/bin/alembic current
.venv/bin/alembic check
.venv/bin/python -B -m decisionops.commerce.case_demo investigate \
  --order ORD-1042 --shipment SHIP-1042 --item shirt-blue-M:1
```

Expected readiness accepting connections; revision 0002 (head); no new upgrade
operations. Investigate returns an INV- identifier and a PROP- identifier only
if eligible. Exit 0 means the investigation was saved, including an ineligible
or review result. Each deliberate invocation creates a new investigation.

The original carrier observation was seeded on 2026-10-12 and expires after
24 hours under demo-policy-v1. On 2026-10-13 the original order correctly produces
needs_review with loss_confirmed unknown and proposal_id null. Reseeding is a
no-op and does not make tracking fresh. Never change its timestamp merely to
force eligibility. Real recovery requires a new authoritative carrier observation.
Use the isolated walkthrough below to demonstrate fresh fictional evidence.

Copy actual identifiers from the returned JSON into these commands:

```bash
.venv/bin/python -B -m decisionops.commerce.case_demo inspect \
  --investigation INV-REPLACE_WITH_ACTUAL_ID
.venv/bin/python -B -m decisionops.commerce.case_demo check \
  --proposal PROP-REPLACE_WITH_ACTUAL_ID
```

Inspect returns the original saved assessment and optional proposal, even when
business records have since changed. Check returns current_assessment,
changed_requirements, binding_matches and current_decision. It never changes
saved audit rows. Do not run check with a null proposal ID.

Exit codes: 0 saved/inspected/valid for review; 2 malformed input or missing ID;
3 database failure; 4 proposal requires reinvestigation. A stale check is a
business result, not a container crash. All checks include execution_authorized
false. Errors are JSON on stderr; successes/business results are JSON on stdout.

### Inspect the actual records

```bash
docker compose exec -T postgres psql -U commerce -d commerce -c \
  "SELECT id, order_id, created_at, assessment->'decision' AS decision FROM commerce_investigations ORDER BY created_at DESC LIMIT 5;"
docker compose exec -T postgres psql -U commerce -d commerce -c \
  "SELECT id, investigation_id, created_at, content_hash, document FROM commerce_proposals ORDER BY created_at DESC LIMIT 5;"
docker compose exec -T postgres psql -U commerce -d commerce -c \
  "SELECT id, carrier_status, carrier_observed_at, CURRENT_TIMESTAMP - carrier_observed_at AS age FROM shipments WHERE id='SHIP-1042';"
```

The investigation's assessment stores records, accepted evidence, issues and
scope reasons. Carrier_event_stale_or_future identifies why loss is unknown.
These business snapshots are not graph checkpoints or model-performance traces.

### Reproduce success and a meaningful stock-change failure

```bash
export COMMERCE_TEST_DATABASE_URL="$COMMERCE_DATABASE_URL"
.venv/bin/python -B scripts/commerce_proposal_walkthrough.py
```

Expected:

```text
before: valid_for_review
stock changed: requires_reinvestigation
stock restored: valid_for_review
artifacts: runs/proposal-walkthrough-<generated suffix>
isolated schema removed; public demo data unchanged
```

The script creates a random walkthrough_ schema, migrates and freshly seeds it,
then runs real CLI subprocesses. It changes blue-shirt on_hand from 10 to 9;
reserved remains 1. Eight units still cover the request, so current eligibility
is still true, but the old proposal's stock evidence version no longer matches.
Check exits 4 and changed_requirements contains stock_available. Inspect still
shows the original nine available units. stock-changed.json contains the current
inventory rows and original-snapshot.json contains the saved evidence.

The script restores on_hand to its known isolated starting value, verifies that
contents match again, and removes its isolated schema in finally. It never edits
public demo stock. Returning to identical contents permits review again in this
slice; there is no approval lifecycle or durable approval invalidation yet.

Smallest appropriate response to real stock drift: investigate again and review
the new proposal. Do not edit a saved proposal or restore inventory merely to
make an old proposal pass. Real inventory correction requires an authoritative
stock reconciliation. An intentional SQL edit to an audit row is rejected by
PostgreSQL with 'Commerce audit snapshots are immutable'. Administrators can
bypass guards; staff roles/authentication remain necessary before exposure.

### Database failure and recovery

Demonstrate a bad connection without stopping the healthy database:

```bash
COMMERCE_DATABASE_URL='postgresql+psycopg://commerce:local-demo-only@127.0.0.1:1/commerce' \
  .venv/bin/python -B -m decisionops.commerce.case_demo inspect \
  --investigation INV-REPLACE_WITH_ACTUAL_ID
```

Expected exit 3, sanitized database_error on stderr, no successful JSON output.
The inline setting affects only this command; the exported working URL remains
unchanged. Diagnose with docker compose ps, pg_isready, docker compose logs
--tail=30 postgres, and .venv/bin/alembic current. If stopped, run docker compose
up -d --wait postgres, then repeat inspect. If tables are missing, apply upgrade
head. Do not reseed or downgrade as an outage fix.

An investigate failure reports outcome not_confirmed. A connection can fail
while reporting a commit that actually succeeded: inspect recent investigations
using the SELECT above before repeating. Repeated investigation can create a new
audit snapshot, but there are still no replacement actions to duplicate. Durable
operation IDs and reconciliation must precede later execution.

### Tests, shutdown and safe rollback

```bash
python3 -B -S -m unittest discover -s tests -p test_commerce_proposals.py -v
python3 -B -S -m unittest discover -s tests
export COMMERCE_TEST_DATABASE_URL="$COMMERCE_DATABASE_URL"
.venv/bin/python -B -m unittest discover -s tests -p test_commerce_investigations.py -v
.venv/bin/python -B -m unittest discover -s tests
docker compose stop postgres
```

Pure tests require neither PostgreSQL nor third-party packages. Integration tests
use generated schemas and remove those schemas only. Shutdown preserves the
named volume and all saved investigations. Restart with up -d --wait postgres.
Never use down -v to restart; that deletes persistent demo data.

The smallest code rollback is to stop using case_demo and continue the previous
store_demo/fixture commands; migration 0002 is additive and those commands work
with it. Preserve audit tables. Downgrading to 0001 deletes all saved
investigations/proposals and is appropriate only for deliberate disposal of an
isolated test schema, after preserving any needed evidence. Backups/restoration
and release rollback are future operating slices, not yet verified deployment
capabilities.


Latest verification (agent, 2026-10-13): 138 tests run against PostgreSQL, 136
passed and two optional ML checks skipped. Dependency-free mode ran the same
138 tests, with 109 passing and 29 optional database/ML skips. Focused binding
6/6 and investigation 12/12 passed. Migration 0002 matches metadata. PostgreSQL
was left healthy and running on 127.0.0.1:55432; no background application process
was started. Self-review only; changes remain local and uncommitted.

## Local cases, explicit review and approved execution (2026-10-13)

### Components and transaction boundaries

cases.py is the authoritative lifecycle service; case_demo.py exposes local CLI
commands. proposals.py/investigations.py still preserve original evidence and
proposal contents. execution.py owns revalidation, atomic stock changes and
ledger reconciliation. Migration 0003 supplies database constraints/guards.
PostgreSQL remains the only background service. No model, network fulfilment,
customer communication, API or graph worker is involved in this business slice.

A case begins open. Investigation produces awaiting_review, needs_review or
blocked. Only an explicit local operator review can approve its exact current
proposal ID, hash and generation. Reinvestigation supersedes the proposal and
clears approval. Reject/escalate cannot execute. Executed is terminal.

Execution locks case, order, immutable policy (shared key lock), order lines,
payment, shipments/lines and sorted inventory rows. It then rereads current
facts and proposal bindings. Clock freshness includes time waiting for locks.
Changed/expired evidence commits an invalidation event, clears active approval,
and returns needs review. Restoring old data never restores that approval.

A successful transaction creates the operation, replacement header/lines,
reservation records and replacement compensation, increments inventory.reserved,
and moves the case to executed. These changes commit together. on_hand does not
change: reservation is a promise against stock, not a shipment. Resolutions are
append-only; the compensation trigger serializes inserts through the parent order
revision and forbids cumulative compensation above original quantities. Historical
coverage is still resolution_history_complete, never inferred from revision zero.

### Start and reproduce the entire flow safely

```bash
cd /path/to/decisionops
export COMMERCE_DATABASE_URL='postgresql+psycopg://commerce:local-demo-only@127.0.0.1:55432/commerce'
export COMMERCE_TEST_DATABASE_URL="$COMMERCE_DATABASE_URL"
docker compose up -d --wait postgres
docker compose exec -T postgres pg_isready -U commerce -d commerce
.venv/bin/alembic upgrade head
.venv/bin/alembic current
.venv/bin/python -B scripts/commerce_execution_walkthrough.py
```

Expected migration 0003; walkthrough reports stock drift revoked approval,
reinvestigation/new approval executed one replacement, and duplicate execution
reserved only once. It uses a freshly seeded random isolated schema and removes
only that schema afterward. All JSON and diagnostics remain under the printed
runs/execution-walkthrough- directory. Your original public demo is untouched.
This script deliberately performs local-demo-operator reviews in fictional test
records; it is not auto-approval behavior in the application.

The original ORD-1042 carrier evidence is now stale. Opening/investigating it in
public should produce needs_review. Do not refresh the timestamp to obtain a
proposal. The walkthrough provides fresh fictional data for the success path.

### Individual staff commands

```bash
.venv/bin/python -B -m decisionops.commerce.case_demo open \
  --order ORD-1042 --shipment SHIP-1042 --item shirt-blue-M:1
```

Copy the returned case ID; inspect and investigate:

```bash
case_id='CASE-REPLACE_WITH_ACTUAL_ID'
.venv/bin/python -B -m decisionops.commerce.case_demo investigate-case --case "$case_id"
.venv/bin/python -B -m decisionops.commerce.case_demo show-case --case "$case_id"
```

Only for an actual awaiting_review case, copy generation, proposal.id and
proposal.content_hash from show-case. Review the document and underlying evidence.
The approved CLI operator is explicitly a local demo identity; filesystem/database
access is the trust boundary. Staff authentication must precede public API exposure.

```bash
proposal_id='PROP-REPLACE_WITH_ACTUAL_ID'
proposal_hash='REPLACE_WITH_ACTUAL_CONTENT_HASH'
case_generation='1'
.venv/bin/python -B -m decisionops.commerce.case_demo review \
  --case "$case_id" --generation "$case_generation" \
  --proposal "$proposal_id" --hash "$proposal_hash" --decision approve
```

Expected status approved and approval.operation_id. --decision reject instead
returns rejected with no active approval or operation ID. Wrong generation, hash
or another case's proposal exits 2 and changes nothing. Duplicate identical review
returns the existing review. An approval that was revoked cannot be revived with
a duplicate submission; investigate and explicitly review a new generation.

```bash
operation_id='OP-REPLACE_WITH_ACTUAL_APPROVAL_OPERATION_ID'
.venv/bin/python -B -m decisionops.commerce.case_demo execute \
  --case "$case_id" --operation "$operation_id"
.venv/bin/python -B -m decisionops.commerce.case_demo reconcile \
  --operation "$operation_id"
.venv/bin/python -B -m decisionops.commerce.case_demo show-case --case "$case_id"
```

Expected verified, same operation/replacement identifiers, and case executed.
Repetition of execute with the same operation returns the original verified
records; it does not reserve again. Another case/operation or unapproved case
exits 2. Reconcile is read-only: verified means replacement/quantity/reservation/
compensation/lifecycle records agree and inventory counters cover recorded holds.
It does not mean the replacement was shipped. not_found or inconsistent exits 4;
a failed lookup exits 3 rather than falsely claiming no operation exists.

Escalation works for non-executed cases:

```bash
.venv/bin/python -B -m decisionops.commerce.case_demo escalate \
  --case "$case_id" --reason 'Obtain authoritative current carrier evidence'
```

### Diagnose stale approval, races and uncertain outcomes

The isolated walkthrough changes stock after approval. stale-execution.json
contains changed_requirements and the current assessment; revoked-approval.stderr.log
shows that restoring stock did not revive permission. final-case.json contains an
ordered event timeline with approval_invalidated, reinvestigation, review and execution.
The appropriate patch is a fresh investigation/new staff review, not editing saved
proposal contents, deleting compensation or resetting reservation counters.

Inspect public tables without changing them:

```bash
docker compose exec -T postgres psql -U commerce -d commerce -c \
  "SELECT id,status,generation,proposal_id,approval_id FROM commerce_cases ORDER BY created_at DESC LIMIT 10;"
docker compose exec -T postgres psql -U commerce -d commerce -c \
  "SELECT sequence,case_id,kind,details FROM commerce_case_events ORDER BY sequence DESC LIMIT 10;"
docker compose exec -T postgres psql -U commerce -d commerce -c \
  "SELECT id,case_id,order_id,completed_at FROM commerce_operations;"
docker compose exec -T postgres psql -U commerce -d commerce -c \
  "SELECT * FROM commerce_reservations ORDER BY operation_id,variant_id;"
docker compose exec -T postgres psql -U commerce -d commerce -c \
  "SELECT store_id,variant_id,on_hand,reserved,on_hand-reserved AS available FROM inventory;"
```

If execution returns database_error or the process disappears before returning,
its commit may have succeeded. Reconcile the stable approval.operation_id before
retrying. A verified record is the proof of commit; a trace/log alone is not.
not_found permits retry only through execute, which rechecks the active approval.
If the database is unavailable, first recover it; absence has not been established.
An inconsistent result requires staff investigation; do not create another operation.

Database operations have a five-second statement timeout in the CLI. Contention
or interruption can therefore roll back; identify blockers with pg_stat_activity
and logs, wait/retry the same operation after reconciliation. Do not increase a
timeout to bypass missing approval, changed evidence or stock constraints.

### Tests, rollback and shutdown

```bash
export COMMERCE_TEST_DATABASE_URL="$COMMERCE_DATABASE_URL"
.venv/bin/python -B -m unittest discover -s tests -p test_commerce_execution.py -v
.venv/bin/python -B -m unittest discover -s tests
python3 -B -S -m unittest discover -s tests
docker compose stop postgres
```

Real concurrency tests use separate connections/transactions: duplicate operation,
two cases/one order, two orders/last unit, and direct concurrent refunds. A simulated
failure after inventory update proves rollback; post-commit response-loss simulation
proves reconciliation and duplicate retry do not reserve twice. These are local
transaction guarantees, not external fulfilment exactly-once behavior.

Before commit, exceptions automatically roll back the whole slice. After commit,
there is no implemented release/cancellation/refund-reversal workflow. Do not undo
an executed replacement with direct SQL counter/history edits; that corrupts the
ledger. Disposable walkthroughs safely drop their generated schemas. Public data
recovery needs a tested backup or a future designed correction workflow.

Code rollback can retain additive migration 0003 and use previous read-only commands.
Downgrading 0003 deletes cases, approvals and replacement ledgers; it is destructive
and not an outage fix. stop/restart preserves the volume and saved approvals/operations.
Do not use docker compose down -v as a recovery command.

## Durable worker and local staff workspace (2026-10-13)

The browser sends authenticated JSON requests to the same-origin Nginx proxy.
`api.py` validates store access and inputs, then queues durable jobs. `jobs.py`
claims work with an expiring lease and fenced token. `worker.py` runs `workflow.py`
with PostgreSQL LangGraph checkpoints. `cases.py` owns the business lifecycle;
`execution.py` owns the atomic ledger, reservation and reconciliation. Graph state
cannot grant approval. `read_tools.py` still derives actual evidence, and the
original eligibility function decides false versus unknown. React lives in
`frontend/src/main.tsx`; image definitions are in `docker/`, service wiring in
`compose.yaml`. Migration 0004 adds jobs; graph tables live separately in
`commerce_graph` and are set up by the worker, not Alembic.

### Start and sign in

Run from `/path/to/decisionops`:

```bash
python3 -B scripts/commerce_local_setup.py
docker compose --profile app build
docker compose --profile app up -d --wait
docker compose --profile app ps
curl --fail http://127.0.0.1:8080/health
```

Expected: postgres, api and web healthy; worker running; init exited 0. Readiness
returns `ready` / `fictional_store_rules`. Init migrates to 0004, seeds only once,
and creates checkpoint tables. Open http://127.0.0.1:8080 and sign in as operator.
To read your password **locally**, without posting it in chat or a ticket:

```bash
sed -n 's/^COMMERCE_STAFF_PASSWORD=//p' .env
stat -c '%a %n' .env
```

Expected file mode: 600. The setup script preserves an existing secret. Browser
credentials live in memory only; sign out or reload to clear them. The app binds
loopback only. HTTP Basic is suitable for this local demo; external access needs
TLS and a reviewed identity/access setup. Do not simply expose port 8080.

Open a case, investigate, inspect evidence, explicitly approve the exact proposal,
then record the approved replacement. Approval alone creates nothing. Verified
means the fictional replacement and stock reservation exist; nothing is shipped.
Your original public ORD-1042 may now have stale tracking and require review. The
seed command deliberately does not refresh evidence to force eligibility.

### Inspect and recover worker failures

```bash
docker compose --profile app logs --tail 40 api worker init
docker compose exec -T postgres psql -U commerce -d commerce -c \
  "SELECT id,case_id,action,status,attempts,lease_until,error_kind FROM commerce_jobs ORDER BY created_at DESC LIMIT 20;"
docker compose exec -T postgres psql -U commerce -d commerce -c \
  "SELECT case_id,kind,created_at FROM commerce_case_events ORDER BY sequence DESC LIMIT 20;"
docker compose --profile app stop worker
docker compose --profile app up -d worker
```

A queued job waits for a worker. A killed worker's running job becomes claimable
after its 30-second lease expires. The replacement token fences the old claimant.
Three abandoned attempts become failed rather than retrying forever. Fix the
cause and enqueue a fresh investigation through the UI. Never manually mark a job
complete or fabricate an approval. Stop is graceful; a forced kill is a distinct
failure. Database and business state remain the authority after either.

For job/checkpoint inspection or repair (replace JOB-ID with an actual ID):

```bash
docker compose exec -T worker python -B -m decisionops.commerce.worker show --job JOB-ID
docker compose exec -T worker python -B -m decisionops.commerce.worker replay --job JOB-ID
docker compose exec -T worker python -B -m decisionops.commerce.worker resume --job JOB-ID
```

Replay accepts a completed job and repairs its graph projection from the saved
outcome; it does not execute the action twice. Resume accepts a real recorded
review; it cannot supply permission. Browser review updates authoritative case
state immediately; an old graph review pause can remain until explicit resume or
replay. Later execution uses the actual case approval, not that paused projection.
If business commit succeeded but checkpoint write failed, logs report
checkpoint_incomplete; inspect/reconcile the operation before replaying the graph.

### Reproduce failures without changing your store

```bash
export COMMERCE_TEST_DATABASE_URL='postgresql+psycopg://commerce:local-demo-only@127.0.0.1:55432/commerce'
.venv/bin/python -B scripts/commerce_worker_walkthrough.py
docker build -f docker/Dockerfile.browser -t decisionops-commerce-browser:local .
.venv/bin/python -B scripts/commerce_browser_walkthrough.py
```

The worker walkthrough demonstrates lease recovery, persisted review, rejection
of an unapproved resume, and verified execution with safe replay. The browser
walkthrough temporarily points the local app at fresh isolated records: a dialog
opened for generation 1 is rejected after reinvestigation produces generation 2;
fresh approval then succeeds. Incomplete compensation history stays unknown and
has no approval control. Screenshots and logs are saved under runs/. Both demos
remove only their generated schemas. The browser demo restores the original store
in finally; do not run it during another operator's session. If interrupted with
SIGKILL, restore with `docker compose --profile app up -d --wait` before inspecting
and cleaning only the named browser_walkthrough schema recorded in its override.

The smallest fix for a superseded proposal is to inspect the fresh evidence and
approve the fresh proposal. A configuration change cannot make incomplete history
complete; obtain an authoritative record. Do not patch unknown facts to true.

### Availability, restart, credentials and shutdown

```bash
docker compose stop postgres
curl -i http://127.0.0.1:8080/health
docker compose up -d --wait postgres
curl --fail http://127.0.0.1:8080/health
docker compose --profile app restart worker
docker compose --profile app stop web api worker
docker compose stop postgres
```

The outage returns an explicit unavailable response (503), never an empty store
or zero compensation. PostgreSQL recovery restores readiness without deleting
records. `restart` restarts an existing container with its existing environment;
changed configuration requires `up -d` to recreate it. `stop` preserves data;
`down` removes containers/network but normally preserves named volumes;
`down -v` deletes persistent business, job and checkpoint data and is destructive.

To rotate staff credentials, keep a private mode-600 backup of .env, replace only
COMMERCE_STAFF_PASSWORD with a new random value of at least 16 characters, and run
`docker compose --profile app up -d --wait api web`. Old browser sessions fail
authentication and must sign in again. Undo a mistaken rotation by restoring the
private backup and recreating api; do not print either secret in logs. Never store
credentials in frontend code, screenshots, traces or version control.

### Verification and current boundaries

```bash
env -u COMMERCE_TEST_DATABASE_URL python3 -B -S -m unittest discover -s tests
export COMMERCE_TEST_DATABASE_URL='postgresql+psycopg://commerce:local-demo-only@127.0.0.1:55432/commerce'
.venv/bin/python -B -m unittest discover -s tests
```

The first command requires neither PostgreSQL nor commerce/model dependencies.
The second runs real disposable PostgreSQL tests. Compose production builds run
the TypeScript check and locked Vite build. Browser tests use locked Playwright
and Chromium, with trace recording disabled to avoid exporting auth headers.
No model is loaded or downloaded; LangSmith tracing is explicitly disabled.
No paid provider call, external fulfilment, cloud deployment or backup validation
is implied by successful local tests. These remain separate release milestones.

## Backup, restore and local release maintenance

```bash
python3 -B scripts/commerce_backup_walkthrough.py
```

Expected: private custom-format dump under runs/backup-walkthrough-*/, restored
into a new restore_check_* database, checked business records match, migration
0004 and graph tables present, disposable database dropped. The live commerce
database is never overwritten. If writes occur during comparison, verification
may fail even though pg_dump produced a consistent snapshot; rerun during a
maintenance pause. This test retains a mode-600 dump inside a mode-700 directory.
Do not upload it to public artifacts. It is local disaster-recovery evidence, not
an off-host backup. A lost disk still loses both source and local backups.

For an explicit maintenance backup (do not include the leading $ prompts):

```bash
docker compose --profile app stop web api worker
umask 077
mkdir -p runs/manual-backups
docker compose exec -T postgres pg_dump -U commerce -d commerce -Fc > runs/manual-backups/commerce.dump
test -s runs/manual-backups/commerce.dump
docker compose --profile app up -d --wait
```

Stop clients before restoring to the original name. Prefer restoring to a new
database and verifying first, then switch the configured database URL during a
controlled maintenance window. Do not use `pg_restore --clean` against the live
store as an exploratory command. A backup contains business and graph records;
the ignored .env secret needs its own private backup. Restoring an old snapshot
can lose later approvals or operations; reconcile what happened before serving it.

Before changing code, preserve image identity and a tested database backup:

```bash
docker image inspect decisionops-commerce-app:local --format '{{.Id}}'
docker image inspect decisionops-commerce-web:local --format '{{.Id}}'
docker tag decisionops-commerce-app:local decisionops-commerce-app:previous
docker tag decisionops-commerce-web:local decisionops-commerce-web:previous
docker compose --profile app build
docker compose --profile app up -d --wait
curl --fail http://127.0.0.1:8080/health
docker compose --profile app logs --tail 30 api worker
```

If a rollout fails, inspect init/API logs first. Restore the previous image tags
only if their code supports the installed schema, then recreate services:

```bash
docker tag decisionops-commerce-app:previous decisionops-commerce-app:local
docker tag decisionops-commerce-web:previous decisionops-commerce-web:local
docker compose --profile app up -d --force-recreate --wait
```

These are prepared rollback commands, not proof that arbitrary previous releases
are compatible. Migration downgrades that delete approvals or ledgers are not
routine rollback. Current additive migrations keep original read-only commands,
but external release compatibility still needs a specific tested release pair.

Weekly local maintenance: inspect readiness/logs and failed or expired jobs;
verify backups by restoration; check disk space (`df -h .`) and Compose resources
(`docker stats --no-stream`); review pinned dependency/security updates, rebuild
and run tests before adopting them. Do not globally prune Docker or delete cached
models to free disk. Remove only identified disposable artifacts after deciding
which verification evidence and backups to retain.

## Reproduce the verified maintenance and regression checks

```bash
python3 -B scripts/commerce_release_walkthrough.py
python3 -B -S -m decisionops.commerce.evaluation --output runs/my-regression-report.json
```

The release walkthrough interrupts the workspace: a deliberately bad API startup
command exits 42; readiness fails; restoring the original image/config restores
200 readiness. It then stops PostgreSQL, observes explicit 503, restarts the same
persistent database, and compares checked business records. It recovers in finally.
This proves a **same-code configuration rollback**, not arbitrary old/new code or
destructive-migration compatibility. Run when nobody uses the local workspace.
Evidence from the agent run: runs/release-walkthrough-49i3hol8.

The regression report contains 12 AI-authored, hand-inspected evidence cases and
their expected/actual results. It uses the original evidence/eligibility path,
with fixed replay clock, fixture/dataset hashes, evidence completeness, elapsed
time and explicitly zero paid calls/tokens/cost. It includes instruction override,
unavailable/stale/conflicting/wrong-order evidence, stock/compensation/policy
blockers, unsupported scope and retained blocker-plus-unknown. It is regression
evidence, not independently held-out model performance or a database execution test.
No language model interprets the included customer text.

Expected: passed 12, failed 0, process exit 0. Wrong expected labels return exit 1
without rewriting actual decisions. Malformed input or an existing output file
returns exit 2. Use a new output path on each run to preserve prior evidence. If a
regression fails, inspect its actual decision/issues and the fixture hash; change
a label only after checking the contract, never to hide a business bug.

### Proxy failure diagnosis and smallest patches

The initial real browser run caught Nginx resolving the API address only at startup.
After API recreation, proxy logs showed connection refused to its old IP while
the API itself was healthy. `docker/nginx.conf` now uses Docker's DNS resolver
127.0.0.11 with a five-second cache and variable proxy target, so recreated API
containers are resolved again. The repeated browser demo recreates the API and
then verifies login and mutations. Rebuild/recreate web after changing its config:

```bash
docker compose --profile app build web
docker compose --profile app up -d --wait web
docker compose --profile app logs --tail 20 web api
curl --fail http://127.0.0.1:8080/health
```

As an immediate workaround for an older image with static upstream DNS, restart
web after recreating API. A browser-facing HTML 502 now produces a service
unavailable message instead of a JSON parser error (`frontend/src/main.tsx`).
Do not bypass authentication or expose API ports to work around a proxy failure.

A failed browser diagnostic initially included a password input's value in its
accessibility snapshot despite trace recording being off. The local secret was
rotated, text artifacts redacted, and login now clears password on both success
and failure. Tests additionally clear the field before diagnostics and check a
proxy failure leaves it empty. Treat any exported diagnostic with a credential
as exposure and rotate that credential; disabling trace alone is insufficient.

Current local release includes rules-only domain/workflow/API/UI, recovery and
regression evidence. See SPENDING-PLAN.md for proposed paid experiments and AWS
pilot. Provider budget/adapter implementation, independent held-out evaluation,
cloud TLS/identity/IaC/deployment and encrypted off-host backups remain uncompleted
milestones. No cost plan approval or account availability is inferred.

### Reviewed recovery and case-selection races

Independent read-only review found two minor release issues; both were reproduced
with failing tests before patching. Repeating an already committed operation uses
READ COMMITTED on the execution CLI. Two separate queries could see an older stock
counter and a newer ledger total after another order commits, incorrectly reporting
inconsistent records. `execution.py` now reads counter and ledger total in one SQL
statement/snapshot. The test commits a second real replacement between reads;
the retry now verifies without repeating the original operation. No data repair
is appropriate for this false inconsistency: reconcile through the separate
repeatable-read CLI, then adopt the tested code patch.

During a slow action response, choosing another inbox case could leave a captured
refresh displaying the first case under the second selection. Selection is now
disabled until the action and its refresh finish, and while confirmation is open.
Frozen proposal bindings still protect business approval independently. Browser
verification deliberately holds an action response and checks selection is locked.
Both patches require rebuilding their relevant images and recreating services;
undo code with a known compatible image, never by changing business records.

## Staff interface: plain language and automatic checks

Nontechnical staff use STAFF-GUIDE.md; deployment, credentials and recovery remain
operator responsibilities. `frontend/src/main.tsx` displays familiar product labels,
plain next steps and distinct failed/missing checks. Start review saves a case and
queues its investigation automatically. Approve and Create replacement remain
explicit decisions; the backend still binds their exact contents and evidence.
Unknown execution results do not claim that stock was successfully set aside.

Record IDs, proposal hashes, raw evidence and event details remain available under
Technical details (for support). Routine staff never need to open it. Browser
errors do not expose database/migration/JSON instructions. Ask for help saves a
note; no notification is sent, so staff must share the order reference with a manager.

Reproduce the staff workflow and false-versus-unknown demonstrations:

```bash
docker compose --profile app build web
docker compose --profile app up -d --wait web
docker build -f docker/Dockerfile.browser -t decisionops-commerce-browser:local .
export COMMERCE_TEST_DATABASE_URL='postgresql+psycopg://commerce:local-demo-only@127.0.0.1:55432/commerce'
.venv/bin/python -B scripts/commerce_browser_walkthrough.py
```

Tests use fresh isolated records, preserve public data, and verify automatic checks,
exact approvals, unavailable-service guidance, unknown compensation history,
insufficient-stock explanation and case-selection protection. Screenshot/log
artifacts live under the generated runs/browser-walkthrough directory. Before
patching staff wording, use the actual record-derived reason: unavailable history
is missing information, not proof of zero compensation. Before undoing a frontend
release, retain its compatible image tag as described above; no data migration or
database rollback is needed for these UI changes.

## Source review and reproducible CI

See [REVIEW.md](REVIEW.md) for fresh-checkout commands, guarantees and tests.
Operational `/path/to/decisionops` examples mean your actual repository directory.
The three CI jobs separate standard-library checks, required PostgreSQL checks,
and browser/backup/recovery checks. Run `python3 -B -S
scripts/commerce_ci_tests.py dependency-free` to list every optional skip. Run
`.venv/bin/python -B scripts/commerce_ci_tests.py postgres` with the test database
URL set: a missing URL, empty module or any skipped integration test fails.
The browser walkthrough verifies the JSON Playwright report: at least six
successful checks, zero skipped, unexpected or flaky checks. It creates `runs/`
on fresh checkouts, preserves diagnostics locally, restores its original stack
before removing only its own schemas. No private runtime artifact is uploaded.

A second checkout can avoid interrupting the working application:

```bash
export COMPOSE_PROJECT_NAME=commerce-review
export COMMERCE_POSTGRES_PORT=55433 COMMERCE_WEB_PORT=8081
export COMMERCE_WEB_URL=http://127.0.0.1:8081
export COMMERCE_ORIGINS=http://127.0.0.1:8081
export COMMERCE_TEST_DATABASE_URL='postgresql+psycopg://commerce:local-demo-only@127.0.0.1:55433/commerce'
```

Use the same startup/test/shutdown commands in that checkout. Compose gives it a
separate volume and network. `docker compose --profile app down` stops only this
project and preserves its volume. Unset these overrides before operating the
original stack. To undo this configuration patch, unset the overrides; default
ports remain 55432 and 8080. Do not delete original diagnostic evidence or data.

## Optional fake decision routing and durable simulated budgets

This is an opt-in **operator CLI** integration. The browser/API and durable worker
continue their rules-only investigation path. The current investigation gathers
all seven requirements through one bundled assessment; it does not adaptively
select individual tools. `provider_service.prepare()` calls `investigate_case()`,
saves that complete evidence/proposal, reserves a simulated budget, and commits.
Provider work happens with no open database transaction or business locks.
`apply()` then locks/rereads current records before consuming the recommendation.

The recommendation selects `present_replacement` or `staff_review`. An eligible
present choice keeps the exact proposal awaiting real staff review. A review choice
actually escalates an eligible case; it cannot be approved through the existing
review endpoint until explicitly reinvestigated. Blocked/unknown cases keep their
actual facts and deterministic status. Failure/denial explicitly falls back to
staff review. Stale results cannot overwrite a later generation, approval or
execution. Same-generation eligible proposals with drifted evidence are invalidated.
No provider creates facts, grants approval or calls execution. Confidence is only
an estimate in the simulated response, never an eligibility fact or permission.

### Safe setup: keep the working store separate

This branch adds Alembic `0005`, two budget/call tables and matching health/backup
revision expectations. Do not migrate the running milestone's `0004` database or
reuse its app image tag to test this branch. Use a separate project, volume, ports
and image names. No new dependencies or lockfile changes are required.

```bash
uv sync --locked --only-group commerce --no-python-downloads
export COMPOSE_PROJECT_NAME=decisionops-provider-check
export COMMERCE_POSTGRES_PORT=55434 COMMERCE_WEB_PORT=8082
export COMMERCE_WEB_URL=http://127.0.0.1:8082
export COMMERCE_ORIGINS=http://127.0.0.1:8082
export COMMERCE_APP_IMAGE=decisionops-provider-app:local
export COMMERCE_WEB_IMAGE=decisionops-provider-web:local
python3 -B scripts/commerce_local_setup.py
docker compose --profile app build
docker compose --profile app up -d --wait
curl --fail http://127.0.0.1:8082/health
export COMMERCE_DATABASE_URL='postgresql+psycopg://commerce:local-demo-only@127.0.0.1:55434/commerce'
export COMMERCE_TEST_DATABASE_URL="$COMMERCE_DATABASE_URL"
```

Expected: new store migrated to `0005`, seeded once, ordinary rules workspace
healthy on 8082. The original store on 8080/55432 and its image/container IDs stay
unchanged. Rules is the default in the new workspace too; no provider call is made
on startup, polling, display, approval, execution or reconciliation.

### Reproduce the complete simulated integration

```bash
.venv/bin/python -B scripts/commerce_provider_walkthrough.py
.venv/bin/python -B scripts/commerce_ci_tests.py postgres
python3 -B -S scripts/commerce_ci_tests.py dependency-free
```

Walkthrough creates and removes only its own schema. It demonstrates default rules,
consumed present/review choices, timeout retention, repeated recovery without
redispatch, explicit exhaustion, refusal/unavailability/malformed/override handling,
and exact approval -> one verified replacement despite retry. It saves traces and
business proof under an ignored `runs/provider-walkthrough-*` directory. All
provider responses, usage and USD prices are **simulated**, not paid billing or
model-performance measurements. Latency measures the local fake integration.

Expected illustrative ledger: known success and review each settle 100 input / 10
output simulated tokens at `0.00012000` USD; timeout retains `0.00260000`; three
reserved requests commit `0.00284000` total; fourth request is denied without dispatch.
The configured input/output prices are fictional `1`/`2` USD per million tokens,
version `simulated-v1`. They are not an OpenAI price quote.

### Select rules versus fake mode manually

Use a new fictional case for each independent demonstration. The original tracking
can become stale; do not refresh public seed timestamps to force eligibility.
For guaranteed fresh scenarios, use the disposable walkthrough above.

```bash
CASE_ID=$(.venv/bin/python -B -m decisionops.commerce.case_demo open \
  --order ORD-1042 --shipment SHIP-1042 --item shirt-blue-M:1 \
  | .venv/bin/python -c 'import json,sys; print(json.load(sys.stdin)["id"])')

# Default: ordinary bundled rules investigation, no ledger reservation/dispatch.
.venv/bin/python -B -m decisionops.commerce.provider_demo investigate \
  --case "$CASE_ID" --run RULES-1

# Explicit fictional budget. Existing IDs must keep identical limits/prices.
.venv/bin/python -B -m decisionops.commerce.provider_demo budget-create \
  --budget LOCAL-FAKE-1 --max-requests 3 --max-cost-usd 0.00300000

# Opt in; simulated recommendation is consumed by the actual case service.
.venv/bin/python -B -m decisionops.commerce.provider_demo investigate \
  --mode fake --case "$CASE_ID" --run FAKE-1 --budget LOCAL-FAKE-1 \
  --scenario success --deadline-seconds 5
.venv/bin/python -B -m decisionops.commerce.provider_demo show --run FAKE-1
.venv/bin/python -B -m decisionops.commerce.provider_demo budget --budget LOCAL-FAKE-1
```

Other scenarios: `review`, `unavailable`, `refused`, `invalid_choice`, `malformed`,
`instruction_override`, `timeout`. A real time-limit failure can use
`--delay-ms 1000 --deadline-seconds 0.1` on a new run/case. The bounded fake call
returns to its caller at the deadline; a later daemon-thread result is discarded
and cannot settle/rewrite the application. No SDK retry exists.

CLI exit statuses: 0 completed routing or successful inspection/setup; 2 invalid
input/binding/configuration; 3 database failure with outcome unconfirmed; 4 explicit
fallback, stale recommendation or pending/uncertain outcome. A legitimate `review`
choice can complete routing with exit 0 while the case still needs a manager.

### Inspect reservation, trace and cause

```bash
docker compose exec -T postgres psql -U commerce -d commerce -c \
  "SELECT run_id, case_id, budget_id, state, dispatch_count, reserved_cost_usd, actual_cost_usd, application_status, effective_choice FROM commerce_provider_calls ORDER BY created_at DESC LIMIT 10;"
docker compose exec -T postgres psql -U commerce -d commerce -c \
  "SELECT id, limits, pricing FROM commerce_provider_budgets;"
.venv/bin/python -B -m decisionops.commerce.provider_demo show --run FAKE-1
```

Trace contains task/case/run/provider identities, generation/proposal/hash,
order/shipment/variant/quantity/policy and seven source versions, only normalized
facts (no raw customer text/PII), allowed choices, pinned limits/prices, UTC deadline,
result/usage/status/error/latency and the effective applied choice. Pricing/costs use
Decimal and PostgreSQL NUMERIC with eight fractional places; reservation maximum
rounds upward. A request/call ID is bounded independently of the run identifier.
Never publish private .env, dumps, lease tokens or authentication headers.

Budget row locking serializes both count and maximum-cost checks. The cost committed
is settled actual simulated cost plus the maximum for reserved/dispatching/uncertain
calls. Denied calls commit zero cost and do not consume request quota. Request quota
conservatively retains every accepted reservation, even a never-dispatched expired
request. Settling known bounded usage releases only excess cost, not request count. A known
late result still settles recorded usage, but its recommendation is rejected and
routes to review; an actual timeout with no recorded usage retains the maximum.
Budget configuration/pricing and request bindings are immutable under DB guards.
This is application-accounting protection in the local privileged-demo DB, not a
security guarantee against a database administrator or future provider overbilling.

### Timeout, exhaustion and restart recovery

| Ledger state | Meaning | Safe recovery |
| --- | --- | --- |
| `reserved` | Maximum budget committed; dispatch not yet claimed | Recover SAME run; it claims once if deadline remains. If expired, settle zero known usage and review without dispatch |
| `dispatching` | Dispatch marker committed before invocation; may be running or outcome unknown | Do not dispatch again. Inspect/recover same run; after deadline it becomes uncertain |
| `settled` | Known bounded simulated usage recorded | Recover same run to apply/replay saved result; no provider call |
| `uncertain` | Timeout/malformed unknown usage/crash outcome; maximum retained | Review/reconcile same run; no redispatch and no automatic release |
| `denied` | Quota/cost exhausted; no dispatch | Staff review; inspect budget rather than silently increasing limits |

```bash
.venv/bin/python -B -m decisionops.commerce.provider_demo recover --run FAKE-1
```

Recovery reuses the saved request, configuration and deadline. It does not renew a
deadline or manufacture a new run. Never recover a timeout by automatically creating
a fresh run ID. Actual provider reconciliation/release from authoritative billing
receipts is future work; unresolved reservations stay committed in this slice.
If current case/evidence changed after dispatch, settlement still accounts for known
usage, but result application is stale and requires fresh assessment/review.

To reproduce a crash boundary before dispatch, `provider_demo prepare --mode fake
--case ... --run ... --budget ...` persists the reservation without dispatch; then
use `recover --run ...` in a new process. The cross-process test and walkthrough
also demonstrate uncertainty surviving restart. Logs/records, not process memory,
establish what was reserved, dispatched, settled or applied.

### Patch, verify and undo safely

For a timeout, first inspect `deadline`, `result.error_kind`, state and
`dispatch_count`. Fix a fake delay/deadline for a **new explicit experiment**, not
by editing the old ledger/deadline. For exhaustion, inspect count plus retained
uncertain commitments; do not treat failed/uncertain history as empty. Create a
separate explicitly configured simulated budget if another demonstration is needed.
Do not generalize that operation to paid experiments: approval is still required.

Provider result binding/freshness belongs in `provider_service.py`; contract/fake
behavior in `providers.py`; reservations/settlement in `provider_budget.py`.
The review regression verifies application takes business locks **before** the call
lock, avoiding a prepare/business -> budget -> settlement/call -> apply/business
cycle. Tests also cover 128-character run IDs, atomic budget races, stale results,
unknown retention, daemon deadlines, no locks during waiting and no duplicate dispatch.

To stop this experiment and return to ordinary use, stop only this isolated project
with `docker compose --profile app down` (no `-v`), then unset the project/port/image/
URL overrides. Use the original commerce worktree for the existing rules application.
Do not downgrade a live database, delete ledgers/volumes, switch branches underneath
running builds, or recreate original services with the provider image tag. Schema
0005 is additive, but this branch requires it; the old running image still checks 0004.

## Optional cached local Laya and GLiClass routing

This operator CLI slice shares the validated `route_investigated_case` boundary
with fake providers. Browser/API/worker stay rules-only. It runs after the full
bundled assessment, never selects individual tools, and never approves or executes.
`present_replacement` retains the exact proposal for staff approval; `staff_review`
escalates eligible cases. Evidence, permission, approval invalidation, transaction
locking and reconciliation remain deterministic.

The request retains IDs and hashes for audit/revalidation. The model sees only the
task, seven normalized tri-state facts and allowed Commerce choice descriptions.
One allowed choice means forced deterministic review: no subprocess/model load,
no scores and `dispatch_count=0`. Of 2,187 possible seven-fact tri-state vectors,
only the all-true vector permits two choices. This is one meaningful scored input,
not a broad model-quality benchmark. Repeated cases do not add independent inputs.

### Start only the isolated database

From the local-provider branch/worktree (not the original application's checkout):

```bash
uv sync --locked --only-group commerce --offline --no-python-downloads
export COMPOSE_PROJECT_NAME=decisionops-local-provider-check
export COMMERCE_POSTGRES_PORT=55435
# Starts PostgreSQL only; does not build, retag or restart application images.
docker compose up -d --wait postgres
docker compose exec -T postgres pg_isready -U commerce -d commerce
export COMMERCE_DATABASE_URL='postgresql+psycopg://commerce:local-demo-only@127.0.0.1:55435/commerce'
export COMMERCE_TEST_DATABASE_URL="$COMMERCE_DATABASE_URL"
.venv/bin/alembic upgrade head
.venv/bin/python -B -m decisionops.commerce.seed
```

Expected PostgreSQL healthy, migration `0005`, fictional records seeded. The
original migration-0004 store/volume on 55432 and application on 8080 stay intact.
This adapter slice adds no migration or lockfile/dependency changes.

### Optional dependencies and selecting a model

The commerce-only profile above intentionally excludes model dependencies. Keep
that profile for ordinary CI/development. An existing pinned model environment can
be used solely by the child process. On Richard's machine it is:

```bash
export COMMERCE_MODEL_PYTHON=/home/richard/projects/decisionops/.venv/bin/python
export HF_HOME=/mnt/hdd/data/hf
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
"$COMMERCE_MODEL_PYTHON" -B -c 'from importlib.metadata import version; print({n: version(n) for n in ("torch", "transformers", "laya", "gliclass", "huggingface-hub")})'
hf cache ls --revisions
```

Those two absolute paths are examples of Richard's existing environment; set them
for your machine. They are not model features or baked into source. The repository's
historical default dependency profile has the locked models; the Commerce-only
profile does not. To build a separate optional environment from already cached
packages, use `UV_PROJECT_ENVIRONMENT=.venv-models uv sync --locked --offline
--no-default-groups --no-python-downloads`, then set COMMERCE_MODEL_PYTHON to its
absolute `bin/python`. Do not run that command against the running application's
environment or upgrade packages to mask a cache problem. Offline install fails if
packages are missing: report that need before any download/change.

Pinned revisions are committed in model-revisions.env: GLiClass
`21edefaf7951f68c68c505f9139ba536d3b448f7`, Laya
`55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851`. Loading uses the existing
`offline_model_path`: locate cached model.safetensors with local_files_only and
use its snapshot parent without resolving the weight symlink. A snapshot need
only contain files the loader actually needs, not a complete remote repository.
Missing tokenizer/config files still need diagnosis; a weight alone is insufficient.

### Reproduce measured routing and inspect a trace

```bash
.venv/bin/python -B scripts/commerce_local_provider_comparison.py \
  --output runs/my-local-comparison.json
```

The command creates/migrates/seeds only its owned schema, opens separate cases
for rules/GLiClass/Laya, saves CLI traces, and removes only that schema. It runs
one family per process, CPU, batch one, four threads. Checkpoints are never loaded
in the parent or concurrently. Child imports/load/inference/startup/cleanup are
inside the bounded deadline (default 120 seconds for local modes, maximum 120).
No preload time is hidden. Cache warmth and host contention affect timings.

The committed example is [the integration comparison](../../reports/commerce-local-providers-20261014/README.md).
Both cached models selected review on the all-true case, disagreeing with rules;
the case really became `escalated`. Unknown history forced review without loading.
The negative result is preserved. No reference-policy agreement percentage across
repeated states is a quality estimate; no held-out generalisation/business value
is established. Historical incident performance claims do not transfer here.

For manual operator use, open a fresh case with `case_demo open` as documented
above, copy its ID, then:

```bash
.venv/bin/python -B -m decisionops.commerce.provider_demo budget-create \
  --budget LOCAL-CPU-1 --accounting local --max-requests 3 --max-cost-usd 0
.venv/bin/python -B -m decisionops.commerce.provider_demo investigate \
  --mode gliclass --case CASE-ID --run CPU-RUN-1 --budget LOCAL-CPU-1 \
  --deadline-seconds 120
.venv/bin/python -B -m decisionops.commerce.provider_demo show --run CPU-RUN-1
.venv/bin/python -B -m decisionops.commerce.provider_demo budget --budget LOCAL-CPU-1
```

Replace CASE-ID with the actual ID; `--mode laya` uses Laya instead. A fresh run
ID is required for a genuinely new attempt. `--mode rules` needs no budget and
keeps the ordinary reference workflow. `--mode fake` still requires a simulated
budget, using the previous walkthrough. Local mode cannot consume simulated
pricing and cannot invent tokens: both token fields are null. Its pricing record
says `local_no_api_charge` and USD API charge is exactly zero; CPU, memory and
power are real resources, not dollar-billing measurements.

Inspect `trace.result.metadata`: pinned revision/repository, native `scores` and
`score_meaning`, `forced_choice`, `inference_performed`, `load_seconds`,
`inference_seconds`, child `peak_rss_kib`, total `wall_seconds`, and
`process_reaped` and `validation_outcome`. Single-label GLiClass scores are softmax probabilities over the
allowed labels. Laya retains choice probabilities, native confidence,
answer_confidence and action_act_probability separately. All are uncalibrated;
even an action head of 1.0 is not permission. `trace.effective_choice`,
`application_status` and `case.status` show the actual routing effect. Stale state
or expired evidence prevents application even when a native recommendation is valid.

```bash
docker compose exec -T postgres psql -U commerce -d commerce -c \
  "SELECT run_id,state,dispatch_count,effective_choice,application_status,actual_cost_usd,result->'metadata' AS metadata FROM commerce_provider_calls ORDER BY created_at DESC LIMIT 5;"
```

### Failure diagnosis, recovery and safe undo

```bash
.venv/bin/python -B scripts/commerce_local_provider_failures.py
.venv/bin/python -B scripts/commerce_ci_tests.py postgres
python3 -B -S scripts/commerce_ci_tests.py dependency-free
```

Run the failure walkthrough in the commerce-only environment. It proves missing
model dependencies cause explicit staff-review fallback, exhausted request count
prevents dispatch, and an intentionally slow **test-double** child is killed and
reaped. No models are imported/downloaded for that failure proof or CI. The
comparison command above is the separate actual-inference proof.

`ModuleNotFoundError` in the trace: inspect COMMERCE_MODEL_PYTHON and its pinned
package versions; point it at the existing model environment, then use a new case/
run if a new attempt is wanted. Missing-cache `OSError`/local-entry failure:
inspect HF_HOME and the pinned snapshot's model/config/tokenizer files with offline
cache listing. Correct the cache path; do not resolve a weight symlink to blobs,
request a whole snapshot, or disable offline mode to fix it silently.

Timeout (`deadline_including_load` or a late result): loading may have consumed
most of the allowance. Trace wall/phase timings and RSS identify this. The smallest
configuration change is a larger explicit deadline, up to 120 seconds, for a new
run after inspecting the old outcome. A local timeout retains the request count
and uncertain state with zero maximum API charge. It never redispatches automatically:

```bash
.venv/bin/python -B -m decisionops.commerce.provider_demo recover --run CPU-RUN-1
```

Recovery inspects/applies saved results or settles an expired in-flight marker as
uncertain, preserving dispatch_count. An exit code 4 indicates fallback/stale
routing, not a container crash. Code 2 is invalid input; code 3 means database
outcome unconfirmed. Inspect/recover the same run after readiness; do not assume
an unavailable database means no dispatch occurred. Missing dependencies/cache
with a known completed failure settle zero charge but still consume request count.
No provider result may revive a later approval or execution.

To undo opt-in operation, select rules for subsequent investigations and unset
COMMERCE_MODEL_PYTHON. Reinvestigate escalated cases explicitly if staff wants a
new deterministic proposal. Never edit an audit request/proposal or provider ledger
to clear its history. Stop the isolated container with `docker compose down` while
COMPOSE_PROJECT_NAME still equals decisionops-local-provider-check. Restarting or
stopping containers preserves the named volume; `down -v` deletes it and is not a
recovery step. Do not restart or migrate the original stack for this demonstration.

### Pin rotation and historical recovery

New local configurations/requests validate against model-revisions.env and require
full checkpoint commit SHAs. `ProviderConfig.from_record` and
`ProviderRequest.from_record` validate the recorded structure, identity and bindings
without rereading current pins. Inspection and recovery of completed, in-flight or
forced deterministic calls keep the recorded revision even after pins change.
They never load a model merely to reconstruct audit history.

Dispatch policy is **current-pin-only admission**. If an eligible reserved request
is bound to checkpoint A and the configured pin is now B, recovery settles an
explicit `checkpoint_policy_changed` no-dispatch failure: dispatch_count remains
zero, actual API charge is zero, the immutable request still says A, and the case
routes to review. An unreadable policy file produces `checkpoint_policy_unavailable`
without dispatch. Forced one-choice requests need no model pin consultation.
Already-dispatched calls retain A; uncertain calls are not automatically repeated.

The worker checks admission again before loading. The admitted revision is passed
explicitly to the existing cached loaders, so a file rotation during startup cannot
load B and label it A. Historical diagnostic callers that omit this override retain
their previous pin-file behavior. No checkpoint is silently substituted or downloaded.

Inspect/recover the SAME run first. For a genuinely new attempt under B, explicitly
reinvestigate as needed and create a fresh run with the configured policy. Do not
edit old request JSON, change a reservation's identity or erase request counts.
The old recorded snapshot remains evidence of what was requested, not permission.

### Bounded subprocess output and diagnosis

The parent concurrently drains binary stdout and stderr (and writes stdin) through
nonblocking selectors. Each output stream has a fixed **65,536-byte** cap. Limits
apply during reads, not after buffering or writing an unbounded log. Reading the
first overflow byte stops consumption: the overflowing stream's consumed count is
at most 65,537, retained bytes at most 65,536. Multibyte text counts as bytes.

Overflow yields `worker_output_overflow`, an invalid recommendation and explicit
staff-review fallback. The owned process group is terminated, the direct child is
reaped, and pipe handles close. Independent deadlines still cover live children
that close their streams and descendants that retain pipes. Normal nonzero exits,
malformed JSON and timeout remain distinct outcomes. No `communicate()` accumulation
or unbounded temporary output file is used in this boundary.

Inspect `trace.result.metadata` for `overflow_stream`, `stream_limits_bytes`,
`stream_bytes_consumed`, `stream_bytes_retained`, `stream_diagnostics`,
`process_reaped` and `validation_outcome`. Diagnostics retain only the first 1,024
raw bytes per stream, decoded with replacement; these are bounded excerpts, not
complete logs. Native stdout is parsed only after bounded completion. On overflow,
no truncated/native recommendation is applied. Recovery consumes the saved fallback
without repeating dispatch; known completed failures settle zero API charge while
still consuming the request-count reservation.

The smallest response is to inspect the excerpt for unexpected dependency logging,
wrong entry points or corrupt protocol output. Keep progress/logging off stdout and
fix the noisy source. Do not weaken caps or retry an old run automatically. These
POSIX pipe/process-group controls target the supported local Linux environment.

Reproduce both fixes without model packages or checkpoints:

```bash
python3 -B -S -m unittest discover -s tests -p test_commerce_local_providers.py -v
# After starting only the isolated database as documented above:
.venv/bin/python -B -m unittest discover -s tests -p test_commerce_provider_postgres.py -v
.venv/bin/python -B scripts/commerce_ci_tests.py postgres
```

Pure tests rotate temporary pin A to B, reject new use of A, hydrate old requests
without current-pin reads, verify explicit loader revision forwarding with stubs,
and exercise stdout/stderr overflow, simultaneous streams, malformed output,
deadlines and descendant cleanup. A noisy child intentionally keeps running for
30 seconds; overflow is detected and killed well before its deadline. Database
tests cover old settled/reserved/in-flight/forced calls, controlled no-dispatch,
new B requests and bounded overflow diagnostics/fallback/recovery. These are
model-free regression evidence; historical comparison reports and negative model
results remain unchanged and were not rerun for this patch.

## Stage 1 adaptive read contracts (library/tests only)

The optional adaptive investigation is not wired into the browser, API, worker or
case lifecycle in Stage 1. Stage 2 now provides the separate opt-in CLI below. The [resolved Stage 1 contract](../superpowers/specs/2026-10-14-adaptive-commerce-stage1-contract.md)
lists exact projections, explicit supporting reads and authority rules.
`adaptive_tools.read_tool` executes one selected read; its dependencies must
already exist in `adaptive_evidence.History` and be supplied explicitly with
`dependencies=(...)`. History does not choose dependency objects for the caller. Inspection/assembly performs no SQL. `History.policy_view()` separately returns
bounded normalized requested observations without audit IDs/hashes/raw records.
A caller owns a consistent read-only transaction per tool. An unavailable result
requires rollback of any aborted transaction before a later attempt.

No database/container startup, seed, migration or shutdown is needed for the
local Stage 1 checks. In an existing commerce-only Python environment, from the
repository root:

```bash
python3 -B -S -m unittest discover -s tests -p test_commerce_adaptive_evidence.py
.venv/bin/python -B -m unittest discover -s tests -p test_commerce_adaptive_tools.py
python3 -B -S scripts/commerce_ci_tests.py dependency-free
```

Expected: 16 pure history tests pass; 22 SQLAlchemy tests pass against an in-memory
SQLite business-record mirror. The latter includes 64 complete supported record
states agreeing with the bundled reader; this is deterministic regression coverage,
not model evaluation or PostgreSQL evidence. Without commerce dependencies those
22 tests skip explicitly. The dependency-free profile reports all individual
optional/database skips.

Inspect a meaningful failure without affecting a running database:

```bash
PYTHONPATH=tests .venv/bin/python -B -m unittest \
  test_commerce_adaptive_tools.AdaptiveToolTests.test_incomplete_or_failed_history_cannot_prove_zero
PYTHONPATH=tests python3 -B -S -m unittest \
  test_commerce_adaptive_evidence.AdaptiveEvidenceTests.test_dependency_change_and_expiry_preserve_unknown
```

The first injects an unavailable lookup and incomplete history. Both yield
unknown compensation, with bounded reasons `database_error` / `history_incomplete`,
not permission to replace. The second changes manifest content: the payment
observation stays in immutable history but becomes dependency-invalid. Tests
inspect `Observation.record()` and `History.assess()` rather than application
logs for Stage 1; see the Stage 2 runtime trace guidance below.

The appropriate correction is to restore the source's availability/completeness
and explicitly refresh the affected tool, naming its same-stream predecessor.
After a dependency content change, explicitly refresh its dependent tools as well.
Never set an unknown fact to true, treat unavailable history as empty, or remove
an independent contradictory observation. Unchanged-content dependency refreshes
do not invalidate descendants. All records and supersession edges remain inspectable.
These test fixtures close/dispose their in-memory databases automatically; they
need no container teardown and cannot delete the application's volume.

Version-2 observations are not version-1 proposal inputs. Legacy readers, source
hashes and proposal validators remain unchanged. The eventual collected-evidence
to locked safety-recheck/publication bridge belongs to a later stage.

Opt-in `test_commerce_adaptive_postgres.py` adds ten PostgreSQL checks using the
existing disposable test-schema fixture; the required PostgreSQL CI profile now
collects these and the SQLite contract module and fails on any skip. Do not run
that profile against the original application to verify this slice. PostgreSQL execution against the isolated environment is recorded below; browser
and CI execution for this uncommitted slice are not claimed.

To undo this isolated slice, leave the design worktree and use the unchanged main
checkout; nothing is enabled in the running application and there is no migration
to downgrade. Keep documentation/history until the change is reviewed.

### Completing Stage 1 PostgreSQL acceptance safely

Required PostgreSQL checks run on a separate temporary test database, not port
55432 or the original Compose project. The verified completion environment was:
`decisionops-adaptive-stage1-tests`, loopback port `55436`, database
`commerce_stage1_test`, user `commerce_stage1`, default Docker bridge, and
512 MiB tmpfs at `/var/lib/postgresql/data` (no persistent volume). It used the
already-cached PostgreSQL 16.15 digest with `--pull=never`. No app containers ran
in this test environment. Existing migrations and fictional seeds were applied
only by test fixtures in disposable schemas; no new migration was introduced.

To reproduce with the cached image only (fail rather than pull if unavailable):

```bash
docker run -d --pull=never --name decisionops-adaptive-stage1-tests \
  --label decisionops.test=adaptive-stage1 --memory=512m --cpus=2 \
  --tmpfs /var/lib/postgresql/data:rw,size=512m \
  -e POSTGRES_DB=commerce_stage1_test -e POSTGRES_USER=commerce_stage1 \
  -e POSTGRES_PASSWORD=stage1-fictional-only -p 127.0.0.1:55436:5432 \
  postgres@sha256:0ea6700a3b4f0ae6ce746519073558aed4d88a79d8d07622a9a644946c7319c4
docker exec decisionops-adaptive-stage1-tests pg_isready -U commerce_stage1 -d commerce_stage1_test
docker inspect decisionops-adaptive-stage1-tests --format '{{json .HostConfig.Tmpfs}} {{json .NetworkSettings.Ports}}'
```

Wait for readiness before checks. Port/name conflicts are a blocker; never stop
another container to make room. This command starts PostgreSQL only, with no app
init service and no public-schema migrations or seed.

From `runs/worktrees/adaptive-design`, with the existing commerce-only interpreter:

```bash
export COMMERCE_TEST_PYTHON='../local-providers/.venv/bin/python'
export COMMERCE_TEST_DATABASE_URL='postgresql+psycopg://commerce_stage1:stage1-fictional-only@127.0.0.1:55436/commerce_stage1_test'
"$COMMERCE_TEST_PYTHON" -B -m unittest discover -s tests -p test_commerce_adaptive_postgres.py -v
"$COMMERCE_TEST_PYTHON" -B scripts/commerce_ci_tests.py postgres
"$COMMERCE_TEST_PYTHON" -B -m unittest discover -s tests -v
python3 -B -S scripts/commerce_ci_tests.py dependency-free
python3 -B -S -m decisionops.commerce.evaluation --output runs/stage1-verification/commerce-regression-v1-report.json
```

Use your own existing commerce-profile interpreter when this sibling worktree is
absent. Verify the container's loopback port/tmpfs and assert the database identity
before exporting the test URL. The agent verified `(current_database(), current_user,
inet_server_port()) = (commerce_stage1_test, commerce_stage1, 5432)` on host port
55436 and an empty public schema before tests. Database fixtures create/drop their
own test schemas; they do not upgrade an application schema.

Actual agent results: ten focused PostgreSQL tests passed; required PostgreSQL
profile passed all 120 collected checks with zero skips (includes SQLite contract
checks); full local commerce suite passed 276 of 278, with only two optional Laya
package checks skipped. Dependency-free profile passed 156 of 278 and explicitly
reported 122 optional/database skips. Frozen regression: 12 passed, zero failed,
zero provider calls. No CI or browser execution is claimed for this slice.

The original four container IDs and named volume were inspected read-only and
preserved. Stop/remove only the owned test container after checks; its tmpfs data
is disposable. This is not permission to restart or remove the original Compose
stack or its volume. No paid inference, model loading/downloads or dependency
changes are involved. This describes the historical Stage 1 verification; Stage 2 follows below.

Owned-container shutdown after verification:

```bash
docker stop -t 10 decisionops-adaptive-stage1-tests
docker rm decisionops-adaptive-stage1-tests
```

The agent performed this cleanup after verifying no application/test tables
remained. Logs and actual test summaries are preserved locally under ignored
`runs/stage1-verification/`; tracked historical reports are unchanged.


## Stage 2 opt-in durable model-free investigation

The ordinary browser/API/worker still use the bundled rules workflow. The CLI is
an explicit separate path. `adaptive_policies.py` selects a typed action;
`adaptive_investigations.py` serializes its reservation, calls one Stage 1 read in
a separate read-only transaction, then saves immutable steps/observations.
Migration `0006_adaptive_core.py` follows 0005. Start revokes any old approval and
binds the revision returned by the server-side case UPDATE trigger. Every case
UPDATE (including a no-op/direct SQL) increments revision. A staff edit makes the
old run stale; its late result cannot overwrite the newer case.

Publication requires seven collected valid true conditions and supported scope.
Private safety reads compare projected contents/dependencies; they never become
policy observations or fill a missing collection. Drift records invalidation;
refresh is an explicit counted read. Only exact confirmation creates a separate
legacy v1 proposal. Staff must still approve that exact proposal; existing execution
revalidation, transactional reservation, duplicate prevention and reconciliation
remain unchanged.

### Isolated reproduction and shutdown

Never use the original port 55432, migration-0004 stack or its volume for this
walkthrough. From the adaptive-core worktree, reuse a commerce-only interpreter:

```bash
export COMMERCE_TEST_PYTHON=/home/richard/projects/decisionops/runs/worktrees/local-providers/.venv/bin/python
docker run -d --pull=never --name decisionops-adaptive-stage2-tests \
  --label decisionops.test=adaptive-stage2 --memory=512m --cpus=2 \
  --tmpfs /var/lib/postgresql/data:rw,size=512m \
  -e POSTGRES_DB=commerce_stage2_test -e POSTGRES_USER=commerce_stage2 \
  -e POSTGRES_PASSWORD=stage2-fictional-only -p 127.0.0.1:55437:5432 \
  postgres@sha256:0ea6700a3b4f0ae6ce746519073558aed4d88a79d8d07622a9a644946c7319c4
docker exec decisionops-adaptive-stage2-tests pg_isready -U commerce_stage2 -d commerce_stage2_test
docker inspect decisionops-adaptive-stage2-tests --format '{{json .HostConfig.Tmpfs}} {{json .NetworkSettings.Ports}}'
export COMMERCE_TEST_DATABASE_URL='postgresql+psycopg://commerce_stage2:stage2-fictional-only@127.0.0.1:55437/commerce_stage2_test'
"$COMMERCE_TEST_PYTHON" -B scripts/commerce_adaptive_walkthrough.py
"$COMMERCE_TEST_PYTHON" -B scripts/commerce_ci_tests.py postgres
python3 -B -S scripts/commerce_ci_tests.py dependency-free
docker stop -t 10 decisionops-adaptive-stage2-tests
docker rm decisionops-adaptive-stage2-tests
```

If group membership is not active, prefix Docker commands with `sg docker -c`
as in the agent's recorded commands. Do not pull a missing image automatically.
The script verifies loopback/test database settings, creates its own disposable
schema, migrates to 0006 and seeds fictional data there. It records actual CLI
commands and complete start/run/inspect traces under `runs/stage2-walkthrough-*`,
then drops only its schema. Expected success: proposed, seven tools, eight
choices, awaiting staff review, execution_authorized false. Injected SQL failure
in order_manifest: two counted unavailable attempts, review, all seven facts
unknown; other business tables were not silently queried. The tmpfs database is
disposable and loses data on container stop; durable service state survives CLI
processes but this environment is not a persistent deployment.

For a separately prepared persistent demo database migrated to 0006, open a case
with `case_demo open --order ORD-1042 --shipment SHIP-1042 --item shirt-blue-M:1`.
Set COMMERCE_DATABASE_URL to that verified isolated environment, then use the IDs
printed by each command (replace CASE/RUN/CONTEXT below):

```bash
"$COMMERCE_TEST_PYTHON" -B -m decisionops.commerce.adaptive_demo start --case CASE --report 'Parcel has not arrived' --policy fixed
"$COMMERCE_TEST_PYTHON" -B -m decisionops.commerce.adaptive_demo run --run RUN
"$COMMERCE_TEST_PYTHON" -B -m decisionops.commerce.adaptive_demo inspect --run RUN
"$COMMERCE_TEST_PYTHON" -B -m decisionops.commerce.adaptive_demo advance --run RUN --context CONTEXT --action '{"kind":"read","tool":"order_manifest"}'
"$COMMERCE_TEST_PYTHON" -B -m decisionops.commerce.adaptive_demo recover --run RUN --context CONTEXT
```

Start also accepts cue, fake-override, fake-invalid, fake-unavailable and fake-refuse;
these are model-free policies, not simulated model performance. `run
--inject-tool-failure order_manifest` is allowed only on isolated *_test/*_demo
URLs outside port 55432. It injects a real SQL error inside the selected read-only
transaction. Remove that option to undo the injection; retry only if the run/tool
budgets permit, otherwise open a new staff-reviewed case/run.

### Inspection, failure diagnosis and smallest recovery

Inspect `steps[].data.features` to see exactly what informed a choice; compare
`decision_reserved`, `tool_result`, `choice_rejected`, `safety_drift` and terminal
steps. Raw observation provenance is separate from policy features. SQL inspection
in the configured schema (psql or database console):

```sql
SELECT id, case_id, generation, case_revision, state, context_version,
       decision_attempts, tool_attempts, pending_token, pending_context, deadline
FROM commerce_adaptive_runs ORDER BY created_at;
SELECT run_id, sequence, kind, data FROM commerce_adaptive_steps ORDER BY run_id, sequence;
SELECT run_id, step_sequence, applied, record FROM commerce_adaptive_observations ORDER BY run_id, step_sequence;
SELECT * FROM commerce_adaptive_active;
SELECT * FROM commerce_adaptive_supersessions;
SELECT * FROM commerce_adaptive_tool_counts;
SELECT id, generation, case_revision, status, approval_id FROM commerce_cases;
```

An unavailable observation is unknown, never false. Incomplete compensation
history cannot prove empty history. `safety_drift` names changed tools and keeps
old evidence; request an eligible explicit refresh, never edit old observations.
An early blocker includes unread/unknown conditions and unresolved scope. Only
supported fully established scope can set case status blocked.

Limits are 12 reads, 16 decisions, two attempts/tool and 240 seconds. Invalid
choices and fallback consume separate decisions. Server statement/lock timeouts
are min(5 seconds, remaining run time), including active case/run locks and
persistence. CLI database error exits 3; no fact is invented. Inspect after
availability/locks recover. A pending token requires explicit recover at the
current context; this records interruption without automatic redispatch. A retry
is a new attempt. Expired runs can only record bounded terminal/audit cleanup,
not continue investigation. `case_changed`/stale exits 4 and preserves newer staff
state; inspect the newer case rather than rewriting its revision. No counter reset
or audit-row patch is a safe recovery.

To undo the optional feature, stop using adaptive_demo and retain the bundled
workflow. Revert only Stage 2 source changes in its isolated worktree if needed;
extra unused tables do not enable the feature. Do not downgrade an environment
with evidence to recover: 0006 downgrade destroys adaptive audit history. Never
migrate or restart the original application as part of this procedure.


## Stage 3 opt-in adaptive worker and recovery

Use an isolated environment migrated to 0007. The original migration-0004 stack
on port 55432 must not be upgraded/restarted for these commands. Browser/API and
ordinary `decisionops.commerce.worker` stay bundled/rules-only. Adaptive jobs live
in `commerce_adaptive_jobs`, not the legacy queue. The action namespace is
`adaptive_investigate/v1`; scheduled runs bind `commerce-adaptive-jobs/v1`.

`adaptive_recommendations.py` is a pure typed model-free contract. Fixed/cue/fake
adapters see only Stage 2 bounded features/allowed actions. `adaptive_accounting.py`
reserves a decision and bounded milliseconds before dispatch, storing immutable
context/configuration/evidence bindings. API cost is exact zero, no_api_charge;
there are no invented tokens or model-performance measurements. `adaptive_jobs.py`
claims/renews/fences jobs. `adaptive_runner.py` executes outside transactions and
cancels cooperative fakes on loss of lease/staff binding. `adaptive_workflow.py`
projects committed steps/calls into a separate PostgreSQL checkpoint schema and
`commerce-adaptive/v1:<job>:<run>` thread. Checkpoint values never authorize work.

### Start, verify and reproduce in a disposable database

From the adaptive-recovery worktree, reuse the existing commerce-only interpreter:

```bash
export COMMERCE_TEST_PYTHON=/home/richard/projects/decisionops/runs/worktrees/local-providers/.venv/bin/python
docker run -d --pull=never --name decisionops-adaptive-stage3-tests \
  --label decisionops.test=adaptive-stage3 --memory=512m --cpus=2 \
  --tmpfs /var/lib/postgresql/data:rw,size=512m \
  -e POSTGRES_DB=commerce_stage3_test -e POSTGRES_USER=commerce_stage3 \
  -e POSTGRES_PASSWORD=stage3-fictional-only -p 127.0.0.1:55438:5432 \
  postgres@sha256:0ea6700a3b4f0ae6ce746519073558aed4d88a79d8d07622a9a644946c7319c4 \
  -c shared_buffers=32MB -c max_wal_size=64MB -c min_wal_size=32MB -c checkpoint_timeout=30s
docker exec decisionops-adaptive-stage3-tests pg_isready -U commerce_stage3 -d commerce_stage3_test
docker inspect decisionops-adaptive-stage3-tests --format '{{json .HostConfig.Tmpfs}} {{json .NetworkSettings.Ports}}'
export COMMERCE_TEST_DATABASE_URL='postgresql+psycopg://commerce_stage3:stage3-fictional-only@127.0.0.1:55438/commerce_stage3_test'
"$COMMERCE_TEST_PYTHON" -B scripts/commerce_adaptive_recovery_walkthrough.py
"$COMMERCE_TEST_PYTHON" -B scripts/commerce_ci_tests.py postgres
python3 -B -S scripts/commerce_ci_tests.py dependency-free
docker stop -t 10 decisionops-adaptive-stage3-tests
docker rm decisionops-adaptive-stage3-tests
```

Use `sg docker -c 'docker ...'` if required by group activation. No image pull or
package upgrade is needed. Verify loopback port/database/user and tmpfs identity.
The walkthrough owns a disposable business schema, applies migrations/seeds there,
sets up its separate checkpoint schema and exports CLI commands/full traces before
dropping both. Expected normal run: proposed, seven tools/eight decisions, job
completed, awaiting staff approval. Injected crash after dispatch: no known result;
resume pauses, explicit recover retains that reservation and the fixed fallback
adds another decision. Expected recovered run: proposed, seven tools/nine decisions,
one uncertain reservation and zero duplicate dispatches.

The container is disposable tmpfs: stopping it destroys this test database. This
is separate from a persistent deployment where restarting preserves its volume.
Never use `docker compose down -v` or delete the original application volume.

### Commands in a separately prepared persistent demo

Set COMMERCE_DATABASE_URL to that verified isolated database. Applying `alembic
upgrade head` and `decisionops.commerce.seed` is appropriate only during its own
setup, never on the original runtime. Open a fictional case via `case_demo open`
(as described above), then replace CASE/JOB/TOKEN with printed values:

```bash
"$COMMERCE_TEST_PYTHON" -B -m decisionops.commerce.adaptive_worker setup
"$COMMERCE_TEST_PYTHON" -B -m decisionops.commerce.adaptive_worker enqueue --case CASE --report 'Lost parcel' --policy fixed
"$COMMERCE_TEST_PYTHON" -B -m decisionops.commerce.adaptive_worker once
"$COMMERCE_TEST_PYTHON" -B -m decisionops.commerce.adaptive_worker inspect --job JOB
"$COMMERCE_TEST_PYTHON" -B -m decisionops.commerce.adaptive_worker resume --job JOB
"$COMMERCE_TEST_PYTHON" -B -m decisionops.commerce.adaptive_worker recover --job JOB --token TOKEN
"$COMMERCE_TEST_PYTHON" -B -m decisionops.commerce.adaptive_worker resume --job JOB --token TOKEN
"$COMMERCE_TEST_PYTHON" -B -m decisionops.commerce.adaptive_worker cancel --job JOB
```

Inspect is read-only and works from durable records even without a checkpoint.
Resume claims only queued/expired ownership; a live owner requires its current
explicit token or waiting for expiry. Recover interrupts a pending read token or
retires an unknown recommendation under current ownership. Never edit tokens,
leases, deadlines, context, counter or evidence rows to recover. A recommendation
still dispatching with no recorded result is outcome-unknown: repeated resume
cannot call it again. Recover marks uncertain and preserves reserved milliseconds;
only a new recorded fallback may proceed. A reserved-but-expired undispatched call
settles known zero work; recover releases its application gate without refunding
the consumed decision. A read-only retry is a new tool attempt, maximum two/tool.

Inspect `steps`/`recommendation_reserved` and these SQL records in the correct
business schema (not the separate checkpoint schema):

```sql
SELECT id,run_id,status,token,lease_until,claims,error FROM commerce_adaptive_jobs;
SELECT id,run_id,task,context_version,state,dispatch_count,reserved_ms,actual_ms,
       pricing_version,reserved_cost_usd,actual_cost_usd,application_status,result
FROM commerce_adaptive_calls ORDER BY created_at;
SELECT call_id,sequence,kind,data FROM commerce_adaptive_call_events ORDER BY call_id,sequence;
```

Immutable request hashes/configurations can be inspected in the calls' request
column; policy features are separate from case IDs/source hashes. Native elapsed
milliseconds describe fake adapter work, not model performance. Uncertain calls
retain resource reservations; original bounds remain 16 decisions, 12 tools,
two/tool and 240 seconds. Additional recommendation limits are 20 seconds/call,
240,000 committed/reserved milliseconds/run, and 32KiB serialized requests.

Case/run locks and selected-tool queries use the remaining lease/run deadline,
never inference-held transactions. Token-fenced renewal cannot revive an expired
lease or extend the run. Lease loss raises a controlled error or leaves unapplied
read audit; newer ownership/approval/execution cannot be overwritten. Worker
SIGINT/SIGTERM stops execution, not operator cancellation authority. Explicit
cancel ends an active matching run in review (or stale if staff changed it), but
cannot undo a terminal proposal: use the normal staff rejection/escalation flow.

After checkpoint loss, run `setup`, then `resume`: committed steps/calls are
reconstructed, settled/applied effects are not replayed. If publication committed
before job completion, terminal repair after lease expiry completes metadata only;
it cannot duplicate a proposal. If the database cannot record a result, treat the
dispatched reservation as unknown and use explicit recovery once available.

Smallest safe rollback: stop opting into adaptive_worker; leave the ordinary
worker/rules workflow in place. Do not downgrade 0007 to recover evidence:
downgrade destroys adaptive accounting/jobs. No original-runtime operation is
part of this Stage 3 procedure. Stage 4 model sessions remain pending.

### Stage 3 shutdown and checkpoint timeout diagnosis

SIGINT/SIGTERM now reaches the plain `resume --job JOB` graph path as well as
`once` and token-resume. Example in the already prepared isolated environment:

```bash
"$COMMERCE_TEST_PYTHON" -B -m decisionops.commerce.adaptive_worker resume --job JOB &
COMMERCE_ADAPTIVE_PID=$!
kill -TERM "$COMMERCE_ADAPTIVE_PID"
wait "$COMMERCE_ADAPTIVE_PID"
"$COMMERCE_TEST_PYTHON" -B -m decisionops.commerce.adaptive_worker inspect --job JOB
```

A cooperative fake stops and reports worker_stopped (exit 0). The job can remain
running until its lease expires; shutdown never acts as operator cancel. A
reserved request stays reserved. A committed dispatch intent without a known
result stays uncertain, even if the signal prevented adapter invocation. Neither
path refunds attempts or changes a newer owner's token. Inspect before explicit
recover/resume; do not automatically retry unknown work. A signal may arrive after
completion, so confirm the actual durable state instead of assuming cancellation.

A checkpoint table lock or query timeout reports adaptive_checkpoint_error,
CheckpointFailure and exit 3. Connection establishment has connect_timeout=3;
actual SQL has statement_timeout/lock_timeout, each capped at five seconds and
recomputed against the active run/lease. Setup and historical/terminal projection
use a separate five-second metadata budget. SIGTERM does not instantly interrupt
an already running checkpoint statement; these finite SQL limits bound its wait.
Stop events and runtime ownership objects are not checkpoint state.

Inspect domain state without checkpoint reads using adaptive_worker inspect, then
look for database blockers in the correctly isolated database:

```sql
SELECT pid,wait_event_type,wait_event,pg_blocking_pids(pid),query
FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock';
```

Release/finish only the identified owned locking transaction. Do not kill arbitrary
sessions, change lease tokens, reset budgets, reseed, or downgrade migrations. A
checkpoint error may follow a successful domain commit: check the run's steps,
call application_status and proposal before repair. Use setup only if checkpoint
tables were lost; after readiness/lock recovery, explicitly resume. Settled/applied
work and an existing proposal must remain unchanged. For an uncertain dispatch,
use the existing explicit recover procedure first. No automatic database operations
are required on the original application. Safe rollback is to stop opting into the
adaptive worker; keep audit tables and the ordinary rules workflow intact.

The correction's actual SIGTERM and real SQL read/write-lock regressions are in
`test_commerce_adaptive_jobs.py`. Exact commands/results and retained failures
are recorded in STAGE3-REVIEW.md and the local correction bundle. No model sessions
or Stage 4 work are introduced.


### Stage 4: optional reusable sessions (fake verification; Stage 5 pending)

The ordinary browser, API and worker still use rules. The separate
`adaptive_worker` can opt into a run-owned session. `session_protocol.py` owns its
bounded process/stream transport, `session_worker.py` loads one admitted family,
`adaptive_sessions.py` persists preload phases and maintains fenced ownership,
and `adaptive_accounting.py` retains each decision reservation. PostgreSQL is
still authoritative; graph checkpoints are recoverable projections.

Use a separate database, never the original migration-0004 application's port
55432 or volume. Stage 4 verification used disposable PostgreSQL on loopback
55440, database commerce_stage4_test, with migration 0008 in disposable schemas.
No dependencies or models were installed. From the adaptive-sessions worktree:

```bash
export COMMERCE_TEST_PYTHON=/home/richard/projects/decisionops/runs/worktrees/local-providers/.venv/bin/python
export COMMERCE_TEST_DATABASE_URL='postgresql+psycopg://commerce_stage4:stage4-fictional-only@127.0.0.1:55440/commerce_stage4_test'
"$COMMERCE_TEST_PYTHON" -B -m unittest discover -s tests -p test_commerce_sessions.py -v
"$COMMERCE_TEST_PYTHON" -B -m unittest discover -s tests -p test_commerce_adaptive_sessions.py -v
"$COMMERCE_TEST_PYTHON" -B scripts/commerce_session_walkthrough.py
```

The walkthrough refuses another database/port, verifies readiness, creates and
migrates/seeds its own fictional schema, runs actual CLI commands, exports traces,
and removes its own schemas. It does not start PostgreSQL: use the isolated
container command recorded in STAGE4-REVIEW.md. Expected: success has seven tools,
eight decisions, one fake preload; wrong-correlation case pauses with one uncertain
call, explicit recovery then fixed fallback completes without duplicate dispatch.
Inventory stays unchanged. All responses/scores are simulated integration evidence.

For an already prepared isolated case/environment (`COMMERCE_DATABASE_URL` must
point to that environment, including its schema), the operator entry points are:

```bash
"$COMMERCE_TEST_PYTHON" -B -m decisionops.commerce.adaptive_worker setup
"$COMMERCE_TEST_PYTHON" -B -m decisionops.commerce.adaptive_worker enqueue --case CASE --report 'Lost parcel' --session fake
"$COMMERCE_TEST_PYTHON" -B -m decisionops.commerce.adaptive_worker once
"$COMMERCE_TEST_PYTHON" -B -m decisionops.commerce.adaptive_worker inspect --job JOB
```

Omit `--session` for the unchanged rules path. `--session laya` or `gliclass`
selects a cached pinned family; these implementations have **not** been run in
Stage 4. Real loading/comparison is Stage 5 only. No family/revision IDs enter model
features. Changed pins prevent new or undispatched old requests from loading a
replacement revision; historical inspection remains valid. Forced single-action
choices use deterministic validation without reserving or loading a session.

Inspect `graph.session_phases`, sessions, immutable phase events and calls:

```sql
SELECT id,run_id,ordinal,state,retired,reserved_ms,actual_charge_ms,waiting_ms,load_ms,
       inference_ms,total_ms,diagnostics FROM commerce_adaptive_sessions ORDER BY created_at;
SELECT session_id,kind,data FROM commerce_adaptive_session_events ORDER BY created_at;
SELECT id,state,application_status,request,result FROM commerce_adaptive_calls ORDER BY created_at;
```

Use the correct isolated schema's search_path. Read counters, correlations,
configuration revision, process_reaped, consumed/retained bytes and error before
recovery. Unknown dispatch or preload retains reservations; do not edit rows,
refund attempts or automatically retry. Current-owner explicit recovery retires
the lost session and records fallback, not duplicate dispatch:

```bash
"$COMMERCE_TEST_PYTHON" -B -m decisionops.commerce.adaptive_worker recover --job JOB --token CURRENT_TOKEN
"$COMMERCE_TEST_PYTHON" -B -m decisionops.commerce.adaptive_worker resume --job JOB --token CURRENT_TOKEN
```

An expired owner must first use the documented claim/recover flow; never reuse a
stale token. Restart after a known committed read can reload only as a new counted
phase, at most three sessions per run. Calls bound to a dead session are not
silently rebound. Known errors select recorded rules fallback. Unknown preload
returns uncertain_session, resource exhaustion session_requires_review.

Timeout/lease-loss/shutdown kill the owned group and bound reaping, including
pipe-holding descendants. SIGTERM to plain resume, once or token-resume is worker
shutdown, never operator cancellation. A shared secure per-user host file lock
limits cooperating families; do not run legacy one-shot or external model processes
concurrently. Slot <=30s, preload <=120s, decision <=20s, run <=240s; waiting and
loading count toward run time. stdout/stderr each <=64 KiB per entire session,
retained diagnostics <=1 KiB each; oversize or wrong-correlation frames are failures.
The local API charge is exactly zero; no invented token counts or dollar estimates.

For cache errors, inspect the pinned revision and existing cache snapshot paths;
never follow the weights symlink into a blob directory as the checkpoint root.
For dependency errors, inspect the documented optional model profile without
upgrading/downloading automatically. Routine tests import no model libraries.
Stop the owned CLI with SIGTERM and inspect durable state before explicit recovery.
Rollback is to omit --session and keep rules; do not downgrade 0008, which destroys
session audit. Shutdown an isolated test container with `docker rm -f decisionops-adaptive-stage4-tests` only after verifying its name/port/database;
this disposable tmpfs contains no production records or persistent volume. Never
use that operation on the original application.

### Stage 5 blocked handoff: isolated evaluation and readiness diagnosis

Stage5 native pilots/comparison/replay are stopped. The current source's API health
requires0005 while current adaptive migration head is0008; the isolated API returns
503 and browser cannot start. Required PostgreSQL checks also failed; see
[the Stage5 review](STAGE5-REVIEW.md). Do not modify the original migration-0004
application, downgrade a database to hide the mismatch, or enable adaptive defaults.

The agent demonstrated this separate database startup (cached image, no pull):

```bash
sg docker -c 'docker run --name decisionops-adaptive-stage5-tests --pull never --memory 384m --cpus 2 --tmpfs /var/lib/postgresql/data:rw,size=512m -e POSTGRES_DB=commerce_stage5_test -e POSTGRES_USER=commerce_stage5 -e POSTGRES_PASSWORD=stage5-fictional-only -p 127.0.0.1:55441:5432 -d postgres@sha256:0ea6700a3b4f0ae6ce746519073558aed4d88a79d8d07622a9a644946c7319c4 -c shared_buffers=24MB -c max_wal_size=64MB -c min_wal_size=32MB'
sg docker -c 'docker exec decisionops-adaptive-stage5-tests pg_isready -U commerce_stage5 -d commerce_stage5_test'
export COMMERCE_TEST_PYTHON=/home/richard/projects/decisionops/runs/worktrees/local-providers/.venv/bin/python
export COMMERCE_TEST_DATABASE_URL='postgresql+psycopg://commerce_stage5:stage5-fictional-only@127.0.0.1:55441/commerce_stage5_test'
"$COMMERCE_TEST_PYTHON" -B scripts/commerce_adaptive_evaluation.py --mode baselines --output runs/stage5-baselines-2
"$COMMERCE_TEST_PYTHON" -B scripts/commerce_stage5_walkthrough.py
```

Wait for accepting connections. Both scripts reject another host/port/database and
verify actual database/user/server identity. They create/migrate/seed owned schemas
and remove them afterward. Fictional business snapshots, selected tools, exact
permitted features, hashes and immutable traces are exported. Do not reuse an output
path: preserve prior negative results. Baselines use fixed/cue/fake only; the native
CLI and execution paths explicitly reject real families while this gate is blocked.

The walkthrough actually ran adaptive_worker setup, enqueue --session fake, once,
inspect, explicit recover --job JOB --token CURRENT_TOKEN and token resume. Saved
commands/exit codes/stdout are in the stage5-session directory. Success:7 reads,
8 decisions,1 simulated load. Injected wrong-request correlation: one uncertain
reservation, reaped child; explicit current-owner recovery followed by recorded
fixed fallback,9 total decisions,zero duplicate dispatch. Stock remains10/1.
Never automatically redispatch uncertain work or reset budget counters. For an
expired owner use the documented claim/recover flow, not a stale token.

For the browser failure the agent used only runs/stage5-browser.compose.yaml,
project decisionops-stage5-browser, ports55442/8082 and its own network. Its init
command applied head, seeded and set up legacy checkpoints. Current source was
mounted read-only into cached app images; existing cached web assets were used.
These exact diagnostic commands were demonstrated:

```bash
sg docker -c 'docker compose -f runs/stage5-browser.compose.yaml ps'
sg docker -c 'docker compose -f runs/stage5-browser.compose.yaml logs --tail 15 api'
sg docker -c 'docker exec decisionops-stage5-browser-postgres-1 psql -U commerce -d stage5_browser -c "SELECT version_num FROM alembic_version"'
```

Output shows0008 and repeated GET /health503. The complete Compose recipe, health
response, browser command and all6 failures are in the local review bundle. The
smallest appropriate next correction is to settle the API/schema readiness contract
and add a positive head-migration health test, then verify browser startup against
that same isolated environment. Do not patch production/container settings to skip
health checks. The deadline/cancellation regressions must also be resolved; existing
agent/CI passes from earlier stages do not waive this red local run.

Cleanup actually performed, ONLY after exporting evidence:

```bash
sg docker -c 'docker compose -f runs/stage5-browser.compose.yaml down'
sg docker -c 'docker rm -f decisionops-adaptive-stage5-tests'
```

Both databases were tmpfs, no original persistent volume attached. Container restart
preserves a persistent volume; deleting a volume destroys its records. These
commands concern only disposable Stage5 resources and are not a backup/restore
procedure for the original application. Safe rollback is to stop opting into the
adaptive CLI and keep the ordinary rules workflow; retain audit tables/reports.

Staff approval remains exact generation/proposal/hash-bound. A recommendation,
observed blocker or all-true assessment cannot approve/execute. Execution rechecks
records and takes transactional locks/reserves stock only through the existing
approved service; duplicate prevention and reconciliation remain mandatory. Stage5
baseline and fake recovery commands performed no execution or approval.


## Stage 5 correctness follow-up: readiness and bounded diagnosis

This source explicitly requires schema0008, its mapped column shapes and required
enabled guards. `/health` returns200 with fictional_store_rules only when this
contract passes. Empty/multiple/older/future revision markers or incompatible
required objects return503. It does not migrate. Prepare an isolated environment
with the documented operator migration step; never point these commands at the
original migration0004 runtime. Full contract/evidence: [STAGE5-CORRECTION.md](STAGE5-CORRECTION.md).

The correction's actual disposable browser recipe and output are preserved in its
review archive under evidence/correction-browser.compose.yaml and verification/.
Only cached images were used. Its database is stage5_correction_browser on55444,
web8083, Compose project decisionops-stage5-correction-browser; no original volume.
The agent actually ran:

```bash
sg docker -c 'docker compose -f runs/correction-browser.compose.yaml up -d --wait'
sg docker -c 'docker compose -f runs/correction-browser.compose.yaml logs --no-color init'
sg docker -c 'docker compose -f runs/correction-browser.compose.yaml exec -T api python -c "import urllib.request; print(urllib.request.urlopen(\"http://127.0.0.1:8000/health\").read().decode())"'
sg docker -c 'docker compose -f runs/correction-browser.compose.yaml exec -T postgres psql -U commerce -d stage5_correction_browser -c "SELECT current_database(),current_user; SELECT version_num FROM alembic_version; SELECT count(*) FROM commerce_operations; SELECT status,count(*) FROM commerce_cases GROUP BY status;"'
sg docker -c 'docker compose -f runs/correction-browser.compose.yaml down'
```

Init applied head0008, seeded fictional records and set up legacy worker checkpoints
only in that tmpfs database. Health was ready/rules, browser tests proved one verified
replacement; SQL showed one operation and executed/needs_review/blocked cases.
The complete cached offline build/browser invocation and exact raw logs are in the
correction archive. These ephemeral test commands are not original-stack upgrade
instructions. Stopping this Compose project removes its tmpfs records; original
persistent storage is unrelated and must be retained.

For a timeout, inspect durable request deadline, state, dispatch_count and error
before calling it uncertain: count0 + deadline_before_dispatch + settled/zero is
known no work; count1 without a known result retains its reservation. Staff changes
before claim reject admission; staff changes after actual dispatch fence application
and cancel cooperative work. A lease-expired error before checkpoint SQL does not
prove checkpoint-lock behavior. Use explicit boundary events and pg_stat_activity
Lock evidence, as the focused regressions do. Never extend production caps or
redispatch uncertain work to make a test pass.

Rollback for this source-only health correction means retaining the accepted source
snapshot and disabling the optional adaptive CLI; do not downgrade a schema containing
audit evidence. Restore source only in an isolated test environment if needed.
Ordinary browser/API/workers remain rules-only. Native work is gated on review;
current-source CI publication remains blocked by the recorded approval rejection.

Worker shutdown tests must first prove a ready session and durable dispatch_count1.
A fixed6s delay from subprocess launch may expire during imports/preload and
therefore test pre-dispatch shutdown instead. The corrected test waits on the
actual persisted phase, bounded by existing slot/preload/decision/run limits;
its trace logs the reached dispatch and absolute deadlines before SIGTERM.
No worker or model caps were raised to establish that test boundary.
