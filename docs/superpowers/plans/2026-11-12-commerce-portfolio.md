# Fictional portfolio deployment path

Base f8ce67917ad7c2dc8a137877a6659c4a04857fd0; preserve original/staff runtime.
User authorizes routine bounded packaging fixes and local verification, no publication.

Design: a dedicated compose.portfolio.yaml, project decisionops-portfolio-verify for
verification and decisionops-portfolio for normal use, web127.0.0.1:8091 only,
internal network and private PostgreSQL volume. Rules only. Separate init, API,
ordinary worker, staff investigator, nginx web. Retain existing LangGraph/domain
services. Build current source offline over verified cached locked runtime and
browser dependencies; use distinct portfolio image names. No dependency installation.
Do not inherit .env, credentials or image names from original Compose.

1. Add explicit Compose path + offline cached image builds. Test normalized Compose
configuration for service set, no published DB, isolation, rules mode and credentials
not inherited. Source images/versions and cache requirements recorded.
2. From a clean detached checkout, build --network none / --pull=false, start,
migrate/seed only the new dedicated volume and prove health + browser eligible and
incomplete cases with existing suite. During eligible investigation stop/restart the
staff worker after a committed read; retain before/after durable rows and prove
one run, no duplicate dispatch/publication/execution. Respect real30s lease/240s run.
3. Inspect restart failures before fixing domain behavior. Add focused regression
only for demonstrated defects, retaining uncertainty/fencing and explicit recovery.
4. Verify shutdown, restart persistence and evidence export. Preserve test volume;
remove only clean temporary checkout after artifact equality checks. Do not alter
original app/55521 staff demo. Document one operator path, short portfolio walkthrough,
prior live trace pointer and limitations; propose hosting resources/cost from official
current primary sources, no provisioning. Local commits and handoff, no push.

Acceptance evidence: clean-source builds/readiness, actual browser business assertions,
restart boundary/counts, private networking/ports, shutdown persistence, exact logs.
Re-use f8ce679 test evidence for unchanged core; run appropriate packaging/model-free
checks for final source. CI/live models remain unexecuted in this milestone.
