# Fake decision provider implementation plan

> Execute natively using executing-plans, TDD and a final requesting-code-review pass.

Goal: exercise a consumed post-assessment recommendation with durable simulated
budget accounting and restart-safe fake dispatch.
Spec: ../specs/2026-10-13-fake-provider-budget.md
Stack: existing Python standard library, SQLAlchemy/Alembic/PostgreSQL; no new deps.

- [x] Pure typed contract/fakes: providers.py; test_commerce_providers.py.
      RED tests for permitted evidence/choices, exact decimals, malformed result,
      instruction override, confidence non-authority, deadline and configuration.
- [x] Ledger: schema.py, migration0005, provider_budget.py;
      test_commerce_provider_postgres.py. RED real races/count/cost limits,
      pricing versions, idempotent reserve, known settlement, uncertain retention.
- [x] Integration: provider_service.py and provider_demo.py. RED tests for consumed
      offer versus escalation, fresh revalidation, concurrent state/evidence change,
      no locks while awaiting work, crash before/after dispatch/settlement, no duplicate
      redispatch, timeout/refusal/unavailability, budget denial.
- [x] Operational slice: disposable provider walkthrough, RUNBOOK/DECISIONS/LEARNING,
      CI required-module guard, additive schema revision expectations and separate
      image tag configuration. No migration of live store. Verify provider races,
      full existing regressions, browser and worker/execution recovery as appropriate.
- [ ] Independent review, correct findings, coherent commits, publish new branch and
      separate unmerged PR. Report actual evidence and simulated/provider limitations.

Review focus: unknown billing remains reserved; stale approval cannot revive;
settlement/apply restart does not call again; simultaneous claims dispatch once;
provider context excludes arbitrary customer text; budget caps fail closed.
