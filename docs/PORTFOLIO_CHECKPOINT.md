# Portfolio session checkpoint

## Workspace
- Original checkout preserved: /home/richard/projects/decisionops (main).
- Reviewed baseline: feat/commerce-delivery-workspace at 8307701fceb9438527e9649257695d982dd8cc71.
- Working branch: feat/customer-staff-portfolio.
- Worktree: /home/richard/.codex/worktrees/portfolio-customer/decisionops.
- Current checkpoint: integrated customer/staff candidate; final SHA verification pending.
- Session date: 2026-11-17.

## Checklist
- [x] Locate local reviewed SHA and check remote heads read-only.
- [x] Write design and implementation checklist before product changes.
- [x] Start dedicated GPT-6.1 Sol / high read-only supervisor.
- [x] Customer backend, identity, ownership, canonical reports and conversation projection.
- [x] Separate customer entry and real browser customer/staff flow (five browser checks).
- [x] Typed customer/staff/specialist adapter, redacted bounded tracing and five-case local comparison.
- [x] Compose, Kubernetes, prepared Terraform, deployment/restore attempts (runtime blocked).
- [ ] PostgreSQL/browser/migration/recovery checks and supervisor review on final SHA.
- [ ] Short demo guide and final acceptance matrix.

## Commands and observations
- git worktree list --porcelain: reviewed local worktree found at exact requested SHA.
- git ls-remote --heads origin main feat/commerce-delivery-workspace: main at 3eccbdf;
  delivery branch absent remotely. No fetch mutation, push or publication.
- git worktree add ... -b feat/customer-staff-portfolio 8307701...: created successfully.
- docker info: permission denied connecting to /var/run/docker.sock.
- command -v: Docker available; kubectl/kind/k3d/helm/terraform/psql/pg_ctl absent on PATH.
- Existing reviewed worktree has a locked Commerce .venv and frontend node_modules.
- Continuity helper resolve: project continuity not enabled; no registry changes made.

## Open items and authorization
No paid model calls, hosted LangSmith export, AWS provisioning, external integrations
or publishing authorized. Test these interfaces with local simulations; pending items
must be reported explicitly. Docker socket limitation currently blocks Docker runtime;
probe alternate local options without changing host permissions or using sudo.

Design: superpowers/specs/2026-11-17-customer-staff-portfolio-design.md.
Plan: superpowers/plans/2026-11-17-customer-staff-portfolio.md.
Update this file with commits, exact commands, results and review findings as work proceeds.

## Integrated implementation evidence (before candidate commit)
- Baseline dependency-free: 583 collected, 247 passed, 336 optional skips.
- Reviewed baseline PostgreSQL: 246/246, zero skips (log in reviewed worktree runs/).
- Customer tests: 16 passed, including first-admission race, report FK integrity,
  explicit case ownership, changed reconciliation, 0010->0011 upgrade and untrusted text.
- Browser agent: five real-browser tests passed, build passed; SQL one operation,
  replacement, reservation, reserved unit and canonical parcel case link.
- Typed adapter: four pure tests passed; injected specialist contract validated.
- Tracing: four pure/local tests and two real graph tests passed; export outage,
  redaction, off-thread enrichment, resume after committed reads and correlation.
- Five frozen scenarios x rules/injected adapter simulation: ten product runs,
  matched source hashes and expected public outcomes. Live-model metrics unmeasured.
- First integrated required PostgreSQL profile: 264 passed, zero skips; later
  evaluation/module refinements require final rerun.
- Packaging: Compose config, 12 Kustomize objects/OpenAPI, Terraform fmt/validate,
  locked optional deployment profile passed. No cloud calls.
- Restore: 49 user tables plus two populated worker graphs restored; replacement
  reconciliation verified. Final candidate rerun pending.

## Review fixes and ordinary decisions
- Customer ambiguity clears previous scope, including an explicit split order.
  Questions/hypotheticals do not file reports; model intent cannot override this.
- Explicit customer case references bind the owned case rather than reuse selection.
- Conversations join customer/store identity, including empty threads and replay.
- Reports have immutable ownership/canonical-case/parcel foreign-key bindings.
- Staff see customer words as bounded untrusted context; carrier/source rules retain authority.
- Customer success is freshly reconciled; approval alone and inconsistent ledgers are not success.
- UI fences stale responses across logins and preserves original conversation on transient503.
- Supervisor reproduced trace inspection blocking; enrichment moved to bounded background queue.
- New model adapter supports the specialist graph; historical RecommendationAdapter is separate.
- Continue using explicit demo credentials/Basic auth, no production identity claim.

Final verification commands/results and exact SHA will be retained in
`runs/portfolio-verification/manifest.json` and the supervisor report in this worktree.

## Supervisor review round 1 and corrections
Reviewed exact candidate 760d8cf646e7601e45b535da7812f8631ac9d01a. Browser
5/5 customer and4/4 staff, recovery/worker/execution, deployment static/restore
passed on that SHA. Supervisor held sign-off for two reproduced findings:
1. An instruction question or negated report could file. Positive imperative
   requests/direct first-person nonreceipt statements now gate admission; embedded
   mentions, instructions, negated history and conditional requests clarify.
   Regression: role action5tests and customer16tests green after observed RED.
2. Backup contract test still expected0010. Current pair now0011; stale0010,
   mismatched and future0012 remain rejected. Packaging4tests green after RED.

Final candidate will supersede that SHA. Do not attribute the first candidate's
in-flight/mixed-SHA runs to the final candidate. Every final manifest records
before/after SHA and clean status. Supervisor must sign the new exact SHA.

## Supervisor review round 2 and whole-message correction
Reviewed exact9d4441e35efd68a5413c6ae6fb7cc578a34ad22b. Original negative intent
examples and packaging contract passed; review caught a quoted multi-sentence help
example. Reproduced that and personal-statement-plus-guide-context as RED. Filing
now validates the entire supported utterance, with every sentence matching a positive
request/direct personal nonreceipt statement; no embedded imperative can authorize it.
Unknown narrative clarifies. Canonical template is documented in the demo guide.
Role5tests and customer16tests are GREEN after this correction; supervisor's independent
working-tree parser probes found no further blocker. Exact committed re-review pending.

A concurrent earlier265-test PostgreSQL run hit two existing checkpoint-metadata
statement timeouts in AdaptiveSessionTests (plain resume preload cases). Its SHA/tree
also changed during review; it is not final evidence. Final broad SQL suites will be
serialized after review fixes, without increasing product deadlines or weakening tests.
Earlier candidate browser/deployment/restore checks remain historical; final commands
and supervisor report are under this worktree's `runs/portfolio-verification/`.
