# Customer-to-staff portfolio implementation plan

> **For agentic workers:** Use superpowers:executing-plans for lead integration and independent delegated checks.

**Goal:** Customer report through staff replacement and verified customer update.
**Architecture:** Extend current app with owned customer records and redacted views;
reuse canonical parcel admission, existing business services and LangGraph workers.
**Tech stack:** React/TypeScript, Python/FastAPI, PostgreSQL, LangGraph, Playwright;
opt-in LangSmith; Compose, Kubernetes manifests, prepared Terraform.
**Spec:** ../specs/2026-11-17-customer-staff-portfolio-design.md

## Global constraints
- Synthetic records; model-free repeatable tests and default demo.
- No paid calls, hosted telemetry export, real integrations, AWS apply, push or publish.
- Preserve original checkout and reviewed branch; local commits use owner's identity.

## Review focus
- Ownership on guessed IDs, conversation replays and every related route.
- Explicit missing-parcel intent and unambiguous owned parcel before admission.
- Canonical admission and scan/report concurrency without inverse locks.
- Verified customer projection, no internal data or invented shipping.
- Fail-open sanitized tracing, restart and no duplicate effects.

## Task 1: Customer backend and migration (lead)
Files: schema.py, migrations/versions/0011_customers.py, schema_readiness.py,
customer.py, customer_api.py, api.py, customer_seed.py, tests/test_commerce_customers.py.
- [ ] Write ownership/admission/projection/migration tests and observe initial failure.
- [ ] Implement configured customer principal, ownership and durable conversations.
- [ ] Reuse delivery.report_nonreceipt; preserve reports separately; test concurrency.
- [ ] Verify permissions, replay, split clarification, verified result and regressions.
- [ ] Commit backend with command evidence.

## Task 2: Customer browser and end-to-end runner (delegated)
Files: frontend/src/customer.tsx, frontend/src/main.tsx entry dispatch, frontend tests,
scripts/commerce_customer_browser.py, dedicated Playwright configuration.
Interface: /customer-api/session, orders, orders/{id}, parcels/{id}, cases/{id};
POST conversations {}, GET conversations/{id}, POST conversations/{id}/select
{order_id,shipment_id|null}, POST conversations/{id}/messages {message,request_id}.
Responses and screen integration coordinated with lead before backend contract changes.
- [ ] Write real-browser failing customer/staff flow and unauthorized-session checks.
- [ ] Implement separate entry points and original-conversation polling.
- [ ] Run frontend build and full browser flow; SQL exactly one effect set.

## Task 3: Bounded model adapter and tracing (lead after customer API)
Files: role_actions.py, observability.py, worker integration, focused tests/evaluation.
- [ ] Test invalid outputs, forbidden authority, ambiguity and fallback with fake transport.
- [ ] Add optional bounded typed adapter shared across role classification interfaces.
- [ ] Test sanitized attempt correlation, resume/failure and exporter outage locally.
- [ ] Record rules/simulated adapter comparison; live metrics pending authorization.

## Task 4: Packaging/deployment/restore (delegated)
Files: compose.yaml, deploy/kubernetes/*, infra/terraform/*, local verification script,
docs/PORTFOLIO_DEPLOYMENT.md; preserve single Compose quickstart.
- [ ] Probe local container/cluster tooling; continue static checks if blocked.
- [ ] Add same-app manifests and Terraform preparation without cloud apply.
- [ ] Exercise isolated deployment/browser/recovery/rollback where runtime permits.
- [ ] Try disposable DB backup/restore and record actual evidence and blockers.

## Task 5: Integration and exact-SHA independent review (lead + Sol High)
- [ ] Run PostgreSQL, migrations, browser, recovery and applicable repository checks.
- [ ] Commit candidate; send SHA, changed files, evidence to read-only supervisor.
- [ ] Reproduce/fix blocking findings; rerun affected tests; repeat exact-SHA review.
- [ ] Finish short demo guide, dependency-purpose notes and updated checkpoint.
