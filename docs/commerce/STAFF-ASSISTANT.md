# Try the local staff assistant

Open **http://127.0.0.1:55521**. Login: `operator` /
`fictional-staff-demo-password` (public fictional credentials, loopback only).
Over SSH, forward port 55521. Rules are the default; this app makes no paid calls.
Richard reported trying the browser and that it seemed to work. The detailed checks
below were agent-executed, including automated fictional approvals/replacements.

1. Select **ORD-1042** and **Start review** to open a case. This existing action runs
   the older bundled check. On the case screen, enter a **Shipment report** and click
   **Investigate shipment** for the new independently selected evidence workflow.
2. Follow progress and the evidence list, including inventory. You can use other
   cases or refresh; sign in again after refresh. The selected case stays in the URL.
3. An eligible investigation creates a proposal. **Approve replacement → Confirm
   approval** approves that exact proposal. **Create replacement → Confirm replacement**
   is a separate staff action. Only then is one fictional replacement reserved/created.
4. Try **ORD-HISTORY** for incomplete compensation history: it remains unknown,
   staff review is needed, and no proposal or replacement can be created.

Starting a genuinely new investigation revokes the old proposal/approval. Repeating
an accepted request ID replays the original run. A different ID with the same report
joins matching active work; a different report conflicts until that work finishes.
No unread evidence counts as true. Reports are bounded context, not evidence.

## Inspect or restart this demo

```bash
cd <historical-checkout>
.venv-decisions/bin/python -B scripts/commerce_staff_demo.py status
curl --fail http://127.0.0.1:55521/health
```

Expected: three owned processes; health `ready`. If deliberately restarting only
this demo, retain the database/volume:

```bash
.venv-decisions/bin/python -B scripts/commerce_staff_demo.py stop
sg docker -c 'docker start decisionops-staff-demo-postgres'
sg docker -c 'docker exec decisionops-staff-demo-postgres pg_isready -U staff_demo -d commerce_staff_demo'
.venv-decisions/bin/python -B scripts/commerce_staff_demo.py start --mode rules
```

Stop just the helper's recorded processes with its `stop` command. Stopping the
`decisionops-staff-demo-postgres` container is optional and affects this isolated
demo only. Never remove its volume to restart. Never target the original app on
8080/55432 or migrate its migration-0004 volume.

## Clean checkout with existing cached dependencies

The following method was exercised in a detached clean checkout, port **55523**,
using new `staff_demo_` schemas on the isolated PostgreSQL at 55520. It reuses the
existing locked Python environment and browser image; it does not install anything.
Set `STAFF_CHECKOUT` to your separate clean checkout. Do not replace a live checkout.

```bash
STAFF_CHECKOUT=/home/richard/projects/decisionops/runs/worktrees/staff-repeatability
STAFF_PYTHON=<historical-checkout>/.venv-decisions/bin/python
cd "$STAFF_CHECKOUT"
mkdir -p runs/staff-assistant/web-dist
sg docker -c "docker run --rm --pull never --network none -v '$STAFF_CHECKOUT/frontend:/source:ro' -v '$STAFF_CHECKOUT/runs/staff-assistant/web-dist:/output' --entrypoint sh decisionops-commerce-browser:local -c 'cp -r /source/. /workspace/ && npm run build -- --outDir /output --emptyOutDir'"
sg docker -c 'docker exec decisionops-staff-demo-postgres pg_isready -U staff_demo -d commerce_staff_demo'
# Create a NEW owned schema once; do not reuse/reset a completed browser fixture.
sg docker -c 'docker exec decisionops-staff-demo-postgres psql -v ON_ERROR_STOP=1 -U staff_demo -d commerce_staff_demo -c "CREATE SCHEMA staff_demo_my_trial;"'
"$STAFF_PYTHON" -B scripts/commerce_staff_demo.py start --mode rules --schema staff_demo_my_trial --port 55523
curl --fail http://127.0.0.1:55523/health
"$STAFF_PYTHON" -B scripts/commerce_staff_demo.py status
# When finished, retains schema/data and does not stop the 55521 demo:
"$STAFF_PYTHON" -B scripts/commerce_staff_demo.py stop
```

The clean verification checkout was removed after evidence preservation. Recreate it
with `git worktree add --detach runs/worktrees/staff-repeatability <reviewed-commit>`
from the main repository before using these commands. Existing caches are prerequisites,
not included in Git. See the [operator guide](README.md) for the locked commerce-only
profile. No clean dependency installation or fresh-machine provisioning was attempted.

If the dedicated DB does not yet exist, its one-time creation with the cached image is:

```bash
sg docker -c 'docker run -d --pull never --name decisionops-staff-demo-postgres --memory 512m --cpus 2 -e POSTGRES_DB=commerce_staff_demo -e POSTGRES_USER=staff_demo -e POSTGRES_PASSWORD=fictional-staff-demo-only -p 127.0.0.1:55520:5432 -v decisionops_staff_demo_data:/var/lib/postgresql/data postgres@sha256:0ea6700a3b4f0ae6ce746519073558aed4d88a79d8d07622a9a644946c7319c4'
```

The helper checks database/user/TCP port before applying migrations through 0008,
seeds only an unseeded schema, sets up checkpoints, then starts API/static UI, ordinary
worker and staff investigator. No business locks span inference. Only allowlisted
non-secret environment settings reach children; external API keys are not forwarded.
An occupied port or missing frontend build fails before database changes. `--port`
allows another checkout; it does not allow another database or paid provider.

## Evidence, modes and diagnosis

- [Rules and mocked-browser evidence, review map and exact checks](../../reports/commerce-staff-assistant-repeatability-20261112/README.md).
- [Proposal screenshot](../../reports/commerce-staff-assistant-repeatability-20261112/rules-proposal.png)
  and [incomplete screenshot](../../reports/commerce-staff-assistant-repeatability-20261112/rules-incomplete.png).
- Logs/PIDs/build: `runs/staff-assistant/`; follow-up evidence/review archive:
  `runs/staff-assistant/followup/`. Failed outputs remain preserved.
- To test mock mode, start a **fresh separate schema** with `--mode mock-decisions`.
  It uses injected SDK HTTP transport, not an external key. Original model review
  choices and deterministic continuation steps are separate durable records. The
  expandable explanation appears only when a continuation actually occurred.
- Missing history stays unknown. Manual review, refusal/error, stale evidence and
  exhaustion are not overridden. Decisions cap16, reads12/two per tool, wall time240s.
- An unavailable DB causes health failure; inspect only this demo's `uvicorn.log`
  and `pg_isready`. A stopped worker leaves queued progress; restore the owned
  services, do not reset counters/tokens. Overdue staff runs become review, while
  possible-dispatch reservations remain held. No automatic paid retry exists.
- Rollback: stop this isolated stack and preserve its data/evidence. Use the
  preserved original rules app if needed; do not downgrade its database.

The historical live nano and Decisions runs both ended in review, not a completed
proposal. They were not repeated. [Actual Decisions walkthrough](DECISIONS-LIVE-WALKTHROUGH.md).
The narrow continuation is demonstrated with rules/mocks, not a new live model.
Stage5/native cached-pilot monitor failure remains unresolved; no deployment claim.
See [one-shop read-only pilot handoff](PILOT-HANDOFF.md) for the next bounded milestone.
