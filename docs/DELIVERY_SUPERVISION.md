# Dedicated delivery workspace supervision

This audit continues the isolated `feat/commerce-delivery-workspace` branch from
implementation head `60325788d02844711667e55e8aca240ef75fe25d`, against base
`3eccbdf2db4a5db1a8a749c6c3a3112b751648c3`. The original checkout is preserved.
A dedicated read-only supervisor was explicitly spawned as **gpt-6.1-sol** with
**high** reasoning effort and retained across review rounds. No profile fallback
was needed. Its scope is the committed diff, actual API/browser/worker entry points,
actual assertions, and the original A1–A9 matrix—not the prior completion claims.

## Confirmed findings and corrections

- A message naming two distinct orders selected the first and could start its
  investigation. The server now detects all normalized explicit references before
  invoking any router, clears the selection, and returns only authorized case links.
  Repeated references to the same order remain unambiguous.
- A configured intent router could replace or omit a single explicit order and
  choose another case. An explicit staff reference now governs scope regardless of
  the router reply; without one, the existing server-owned session selection governs.
  Model-generated order IDs do not create a new case binding.
- An older specialist run could mask a new, valid rules proposal after the existing
  browser `Check again` action. Old observations stay masked and explicitly
  historical. Current rules proposals govern status and actions. Cached chat
  freshness is bound to case ID and generation rather than a persistent boolean.

Regressions use real PostgreSQL, real API routes and existing workers. The added
browser fixture completes a real simulated-specialist investigation, changes its
inventory source record, observes a stale follow-up, refreshes through the rules
worker, and approves the new exact proposal while preserving historical evidence.
The browser also exercises multi-order clarification, genuine staff permissions,
and an existing foreign-store case. No stale or historical evidence was promoted
into current proposal authority to make the tests pass.

Recovery assertions now directly check replacement heads and lines, reservation
rows and units, stock counters, and verified reconciliation in addition to the
existing proposal/operation counts. These augment the original real process-exit,
fenced specialist restart, execution worker replay and duplicate-confirmation checks.

## Reproduction and evidence

Use the setup in [DELIVERY_WORKSPACE.md](DELIVERY_WORKSPACE.md). The full repository
suite retains its guarded loopback database identity; do not relax those guards.
With the locked Commerce dependencies, Node24 and system Brave available, run:

```bash
python3 -B -S scripts/commerce_ci_tests.py dependency-free
.venv/bin/python -B scripts/commerce_ci_tests.py postgres
.venv/bin/python -B -m unittest discover -s tests -v
.venv/bin/python -B -m unittest discover -s tests -p test_commerce_conversations.py -v
COMMERCE_COMPARISON_POSTGRES=1 .venv/bin/python -B -m unittest discover -s tests -p test_commerce_comparison.py -v
.venv/bin/python -B scripts/commerce_delivery_recovery.py
.venv/bin/python -B scripts/commerce_worker_walkthrough.py
.venv/bin/python -B scripts/commerce_execution_walkthrough.py
COMMERCE_BROWSER_PATH=/usr/bin/brave-browser .venv/bin/python -B scripts/commerce_delivery_browser.py
```

The browser runner builds the frontend and creates its own fresh migrated schema,
carrier/permission/stale-evidence fixtures and local app, checks SQL uniqueness,
then cleans up its processes and schemas. Direct Playwright invocation needs all
the runner-created fixture IDs, not merely the ordinary demo seed.

New command logs and JSON metadata are saved outside tracked product source at
`/tmp/decisionops-supervision-20261115/`. Metadata records command arguments, SHA
before/after, working-tree state, exit code and duration. The broad run on6032578
was deliberately terminated after a confirmed finding; it is **not** a passing
suite. Red/green logs establish the reproduced regressions. Final verification
uses a clean committed candidate; supervisor sign-off must name that exact SHA.
The supervisor's per-round matrix and final verdict live in that same directory.

The 33 comparison investigations are eleven frozen cases across three actual
PostgreSQL controller modes using simulated choices. They test implementation
outcomes, evidence/read accounting and bounded orchestration; they do not measure
live model quality or establish specialist superiority. Adversarial chooser tests
are separately labelled controller simulations. The original four safe-review
outcome misses remain scored, rather than relabelled as successes.

**Docker image build/launch and live-model decision quality/cost remain unverified.**
Direct local PostgreSQL/FastAPI/Brave checks do not establish Docker launch. No paid
product/evaluation calls, real integrations, push, PR or deployment are authorized
or performed by this audit. The final supervisor matrix must preserve these limits.
